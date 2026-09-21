# ToolHive 平台设计文档 v0.2

> 状态：待评审
> 范围：**本文档只描述 ToolHive 平台本体**（工具注册、工具检索、受控执行、授权、审计）。
> 前提：目标工具规模 **1w+**，但**逐步导入**——架构按 1w 设计，实现按阶段放量。

---

## 1. 定位与范围

### 1.1 一句话

> **ToolHive 是工具的控制面 + 唯一的执行内核 + 可插拔的协议前端。**
> 它回答两个问题：**"你能调什么"** 和 **"帮你安全地调"**。
> 它**不**回答：**"你该调什么"**。

### 1.2 如果你在写 Agent，只需要知道三件事

| # | 你要做的事 | 怎么用 ToolHive |
|---|---|---|
| 1 | **知道有哪些工具能选** | 调 `POST /v1/tools/search`（自然语言 → 候选列表），或用 MCP 的 `search_tools` 元工具 |
| 2 | **把选中的工具跑起来** | 调 `POST /v1/tools/{code}/execute` 传参数，或用 MCP 的 `call_tool` |
| 3 | **不用管的事** | 目标地址、HTTP 方法、上游凭据、限流、重试、熔断、超时、审计——**全部由 ToolHive 负责** |

**ToolHive 不做的事：不替你决定调哪个工具。** 选哪个永远是你的决定；平台只决定"你能不能调"和"怎么调"。

这条分工是硬边界，理由见 §15。

### 1.3 ToolHive 是 / 不是

| 是 | 不是 |
|---|---|
| 工具的注册表（登记、版本、发布、下线） | Agent / 意图理解 |
| 工具的检索服务（自然语言 → 候选工具） | 工具的选定者 |
| 工具的受控执行网关（凭据注入、限流、重试、熔断） | 业务逻辑的宿主（业务工具代码不住在平台里） |
| 治理与审计层 | 编排引擎（不做多步工具编排） |

### 1.4 明确的非目标

- ❌ 不做"一段话进 → 最终答案出"的决策与执行一体化接口
- ❌ **不在请求路径上调用 LLM**（只有 embedding，用于检索）
- ❌ 不做多步工具编排、不做对话记忆
- ❌ 不实现通用 Workflow / DAG 编排
- ❌ 不代管业务文档知识库

---

## 2. 设计约束

来自上一版（已清空，历史见 git `d672d4d`）的六条教训，是本文档所有选择的依据：

| # | 教训 | 约束 |
|---|---|---|
| C1 | 上一版有**两套并行编排**（REST 一份、MCP 一份），导致 MCP 通道没有配额/幂等 | **协议前端必须是薄适配器，执行逻辑只能有一份** |
| C2 | 接一个工具要十几步手工填写，没有导入 | **接入自动化是核心产品循环** |
| C3 | 治理重量远超价值（39 个操作码 / 118 个管理接口 / 31 张表服务于 1 个占位工具） | **治理能力可配置，默认轻** |
| C4 | 不代持凭据 → 真实工具接不进来 | **凭据保管与注入是必选项** |
| C5 | 嵌入式向量库 + 单 worker + 进程内并发计数 | **无状态 + 分布式限流 + 可扩展的单一存储** |
| C6 | 手写 `init.sql` 与 ORM 双份 DDL、无 CI、无前端测试 | **迁移单一来源 + 质量基线第一天就有** |

---

## 3. 核心概念与分层

### 3.1 三个核心概念

| 概念 | 做什么 | 输入 → 输出 | 是否用 LLM |
|---|---|---|---|
| **授权与可见性** | 一个**贯穿始终的约束**：调用方只能看见、只能调用自己被授权的工具 | 调用方身份 → 可见工具集合 | 无 |
| **工具检索** | 把一句自然语言变成候选工具列表 | `query (+范围过滤)` → top-k 候选 | 无（仅 embedding） |
| **执行内核** | 把"工具 + 参数"安全地跑出结果 | `(工具, 参数)` → 结果 | 无 |

> 三者都**不引入 LLM**。平台的确定性资产就在这里，不能在请求路径上被概率性组件污染。

### 3.2 分层架构

```
┌─ 协议前端（薄，只做协议翻译，禁止业务逻辑）────────────────────┐
│   MCP 前端（搜索式暴露）   REST 前端   管理前端/API              │
└──────────────────────────┬──────────────────────────────────┘
                           │ 统一内部契约 ToolInvocation
┌──────────────────────────▼──────────────────────────────────┐
│  执行内核（唯一实现）                                          │
│  版本解析 → 授权判定 → 配额/并发/熔断 → 确认 → 幂等             │
│  → 参数校验 → 凭据注入 → 出站执行 → 输出校验 → 审计/Trace       │
├──────────────────────────────────────────────────────────────┤
│  工具检索                                                     │
│  权限过滤 → 粗排(BM25 ∥ 向量, RRF) → 精排(cross-encoder) → top-k│
├──────────────────────────────────────────────────────────────┤
│  接入管线：导入器(OpenAPI/MCP) → 元数据规范化 → 富化 → 索引     │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  适配层：PostgreSQL(+pgvector) · Redis · 密钥保管 · 上游客户端  │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 一条硬规则（可 CI 强制）

> **`core/` 不允许 import `fastapi`、`starlette`、`mcp`、`uvicorn`。**

理由：执行逻辑一旦长在 Web 框架里，加一种协议就要复制一遍（C1 的根因）。
落地为架构适应度函数（见 §14.2）。

---

## 4. 领域模型

### 4.1 实体总览

| 实体 | 职责 | 关键字段 |
|---|---|---|
| `Principal` | 调用主体（**统一**人与机器） | `id, type(user\|service\|agent), tenant_id, name, status` |
| `Credential` | 上游凭据（加密存储，只写不读） | `id, name, kind, ciphertext, kek_id, rotated_at` |
| `Provider` | 上游连接定义 | `id, code, type(http\|mcp\|local), base_url, auth_ref, tls_config, limits, status` |
| `Tool` | 逻辑工具 | `id, code, source_ref, name, description, domain, system, tags[], risk, review_required, input_schema, output_schema, status, owner` |
| `ToolVersion` | 不可变版本快照 | `id, tool_id, version, 上述定义字段快照, status, published_at` |
| `Channel` | 发布通道 | `tool_id, name(stable\|beta\|canary), version_id` |
| `Binding` | 执行绑定 | `id, version_id, provider_id, method, path_template, param_mapping, timeout_s, retry_max` |
| `Grant` | 主体 × 范围 × 配额 | `id, principal_id, scope_type(domain\|system\|tag\|tool), scope_value, quota, constraints, status` |
| `Invocation` | 每次调用记录 | `id, trace_id, principal_id, tool_id, version_id, protocol, outcome, duration_ms, request_digest, result_digest, error_code` |
| `AuditLog` | 治理事件（谁改了什么） | `id, actor_id, action, object_type, object_id, before/after_summary` |
| `OutboxEvent` | 索引/通知的异步投递 | 沿用上一版的 outbox 模式 |

### 4.2 三个关键设计选择

**① `source_ref` 是稳定身份，`code` 是展示身份。**

```
source_ref = "openapi:crm-api#getCustomer"      ← 跨重新导入稳定
          | "mcp:crm-server#query_customer"
code       = "crm.customer.query"                ← 可读、可改、可重命名
```

**用途区分**：`source_ref` 用于重导时的幂等匹配（保住历史用量、授权、审计关联）；`code` 用于人读和调用。上一版只有 `code`，导致重导即丢历史。

**② Channel 替代"唯一默认版本"。**

```
tool_id=crm.customer.query
  channel=stable → version=1.4.0    ← 生产默认
  channel=beta   → version=1.5.0-rc ← 灰度
```

调用方可指定 `channel=stable`（默认）或钉死具体版本。上一版用 `default_version_id` 唯一约束表达默认版本，想做灰度只能绕。

**③ 用 `tags[]` + `domain/system` 做分组，不引入"能力包"实体。**

授权按 `domain` / `system` / `tag` 层级继承，1w 规模下**不可能逐个工具授权**。

### 4.3 版本状态机（默认轻）

```
draft ──(review_required=false)──→ published ──→ deprecated ──→ retired
  └──(review_required=true)──→ pending_review ──→ published
                                    └──→ rejected → draft
```

- `Tool.review_required` 默认 **false**：内部工具导入后可直接发布
- 高风险工具、对外工具、跨域工具才置 true
- 支持**按来源的信任策略**：来自白名单 Provider 的变更自动发布

---

## 5. 工具接入管线（核心）

> 1w 工具不可能手工登记。**接入管线是平台能否成立的前提，不是效率优化。**

### 5.1 两路导入

| 来源 | 输入 | 稳定标识 | 说明 |
|---|---|---|---|
| OpenAPI 导入 | OpenAPI 3.x / Swagger 2.0 文档（URL 或文件） | `operationId`（缺失时用 `method+path` 哈希） | 一个 `operation` → 一个 Tool |
| MCP 导入 | 一个 MCP Server 地址 | `server_code + tool.name` | 一个 `tools/list` 条目 → 一个 Tool |

### 5.2 字段映射（两路归一到同一个规范化层）

| 目标字段 | 来自 OpenAPI | 来自 MCP | 缺失时的处理 |
|---|---|---|---|
| `source_ref` | `operationId` | `server+name` | 必填，缺失则导入失败并报错 |
| `name` | `summary` | `tool.title` | 回退到 `code` |
| `description` | `description` | `tool.description` | **进入富化管线** |
| `input_schema` | `parameters` + `requestBody` | `tool.inputSchema` | 直接采用 |
| `output_schema` | `responses.2xx.schema` | `tool.outputSchema` | 可为空（不阻塞） |
| `domain` / `system` | **通常没有** | **通常没有** | **靠推断或导入时配置** |
| `tags` | `tags` | 无 | 推断 + 人工补 |
| `risk` | 按 method 推断（GET=low，写=high） | 同上 | 人工可改 |
| `binding` | method + path + 参数落点 | 由 MCP 协议承担（不需 binding） | — |

> **注意最后几行**：业务域、系统、标签在这两种来源里**通常都不存在**，而它们是检索精度的基础。这就是富化管线存在的理由。

### 5.3 命名规范（导入时强制）

```
<domain>.<system>.<entity>.<action>
例：crm.customer.query / aftersale.ticket.create / erp.inventory.adjust
```

- 由导入配置提供 `domain` / `system`，`entity` / `action` 从 operationId 或路径推断
- 冲突时**不覆盖**，生成 `xxx.2` 并要求人工确认
- 规范由 CI 断言（见 §14.1）

### 5.4 富化管线（离线，可用 LLM）

```
原始条目
  → [1] 结构化提取：实体、动作、参数语义、读写属性
  → [2] 描述补全：summary + 参数 + 示例 +（离线 LLM 生成）
  → [3] 打标：domain / system / tags / risk
  → [4] 去重与相似检测：识别"多个团队各写了一个查客户"
  → [5] 置信度评分：低于阈值的进入人工审核队列
  → [6] 生成 embedding，写入索引
```

**这条管线的工作量可能大于检索算法本身，但它才是产品。**

### 5.5 重导的幂等与差异比对

同一来源再次导入时：

```
匹配：source_ref
  → 新增 3 个 / 描述变更 1 个 / 参数变更 2 个 / 上游消失 0 个
差异处理：
  - 新增   → 建 draft
  - 变更   → 建新 ToolVersion（旧版本保留）
  - 消失   → 标记 stale，人工决定 deprecated / retired
绝不覆盖已有版本，绝不丢失历史用量与授权。
```

---

## 6. 工具检索

### 6.1 接口契约

```
POST /v1/tools/search
{
  "query": "查一下这个客户的投诉记录",
  "scope": {                        // 可选，一等参数
    "domain": "aftersale",
    "system": "ticket",
    "tags": ["read"]
  },
  "k": 30,
  "cursor": null                    // 翻页（可选）
}
→ {
  "items": [
    {
      "code": "aftersale.ticket.list",
      "name": "查询工单列表",
      "one_liner": "按客户查询售后工单",
      "matched_reason": "命中『投诉』『客户』",
      "score": 0.87
    }
  ],
  "total_candidates": 187,          // scope 过滤后的候选总量
  "degraded": false,                // 向量不可用时降级为关键词
  "trace_id": "..."
}
```

```
GET /v1/catalog/taxonomy
→ { "domains": [ { "code": "aftersale", "name": "售后",
                   "systems": [ { "code": "ticket", "name": "工单", "tool_count": 42 } ] } ] }
```

**`taxonomy` 接口的意义**：调用方（通常是 Agent）不知道这 1w 个工具是怎么分域的。给它一个"缩小范围的抓手"，就能把检索从 1w 缩到几百——**这是 1w 量级下提升精度最有效的杠杆**。

### 6.2 检索流水线

```
query + scope
  → [1] 权限过滤：得到该调用方可见的工具集合（1w → 可能 200）
  → [2] scope 缩小：按 domain/system/tags 进一步收窄
  → [3] 粗排（召回）：BM25 ∥ 向量相似度 → RRF 融合 → top-100
  → [4] 精排：cross-encoder 重排 top-100 → top-k
  → [5] 轻量返回：只带 name/one_liner/score，不带完整 schema
```

**必须是"先过滤再排序"**，不能"先取 top-100 再丢掉无权限的"——后者在窄权限调用方那里会返回个位数甚至空结果。

### 6.3 上下文预算控制

1w 工具下，返回完整 schema 会撑爆上下文。因此**两段式取详情**：

```
search(k=30) → 轻量候选（每个约 30 token，合计 ~900 token）
   ↓ 调用方挑出 3 个
GET /v1/tools/{code} → 完整定义（含 input_schema）
```

### 6.4 索引版本化（换 embedding 模型）

1w 工具换一次 embedding 模型 = 全量重嵌。因此：

- 向量表带 `index_version`，支持**双版本共存**
- 新版本索引后台重建完成后再切流
- 配置项 `retrieval.active_index_version`

### 6.5 降级策略

| 故障 | 行为 |
|---|---|
| 向量服务不可用 | 退回纯关键词检索，`degraded=true` |
| 精排服务不可用 | 直接返回粗排结果，`degraded=true` |
| 两者都不可用 | 返回空并明确报错，**不返回未经排序的全量列表** |

### 6.6 指标：平台对"找得到"负责

> **平台保证"正确工具出现在候选里"，调用方负责"从候选里选对"。**

调用方的 Agent 只能从返回的 top-k 里选。正确工具排在第 21 位而 k=20，它永远找不到，**而且不会知道自己错过了**。所以平台必须对召回率负责：

| 指标 | 目标 | 说明 |
|---|---|---|
| `recall@30` | ≥ 0.95 | 正确工具出现在前 30 的比例 —— **最重要的指标** |
| `recall@5` | ≥ 0.70 | |
| `MRR@10` | ≥ 0.60 | |
| `nDCG@10` | ≥ 0.65 | |
| p95 延迟 | ≤ 200ms | 含精排 |

**评测集是 M0 交付物，不是后期优化项**（见 §14.4）。

---

## 7. 执行内核

### 7.1 阶段时序

```
调用方 ──execute(tool, args, channel?, idempotency_key?, deadline)──→ 前端
                                                                     │
前端：翻译协议 → ToolInvocation ─────────────────────────────────────┘
                                                                     ↓
执行内核：
  1. 解析工具与版本（code/channel → ToolVersion；不存在 → 404）
  2. 授权判定（无权限 → 404，与"不存在"不可区分）
  3. 策略：配额 / 并发 / 熔断 / 时间窗 / IP 约束
  4. 确认令牌校验（高风险或写操作）
  5. 幂等认领（Redis SET NX + 结果缓存）
  6. 输入 schema 校验
  7. 凭据注入（从 Credential 解密 → 注入 header/query/mTLS）
  8. 出站执行（Provider 适配器，SSRF 防护 + 整体 deadline）
  9. 输出 schema 校验
 10. 记录 Invocation + 写审计
 11. 返回统一结果
```

### 7.2 横切关注点（只实现一次）

| 关注点 | 做法 |
|---|---|
| 配额 | **Redis + Lua 原子计数**（令牌桶/滑动窗口），第一天就是分布式的 |
| 并发 | Redis 信号量（不是进程内） |
| 幂等 | `SET NX` 认领 + **缓存结果**（重试要能拿回同一个结果，不只是拒绝重复） |
| 确认 | 一次性令牌，条件 UPDATE 原子消费 |
| 超时 | 一个**整体 deadline** 从入口贯穿到出站，所有阶段共享 |
| 重试 | 仅幂等方法 + 抖动退避 + 受 deadline 约束 |
| 熔断 | 按 Provider 维度 |
| 审计 | 结构化事件；**不存明文参数与结果**，只存摘要与哈希 |

### 7.3 内核唯一入口

```python
class ToolInvoker:
    async def invoke(self, req: InvocationRequest) -> InvocationResult: ...

@dataclass(frozen=True)
class InvocationRequest:
    principal: Principal
    tool: str                    # code
    version: str | None          # 版本或 channel，默认 stable
    arguments: dict
    protocol: str                # "mcp" | "rest" —— 仅用于审计，不影响行为
    idempotency_key: str | None
    deadline: float
    context: dict                # user_id/tenant_id 等业务身份透传
```

---

## 8. 协议前端与接口面

### 8.1 MCP 前端：搜索式暴露（1w 规模下唯一可行）

MCP 客户端会在会话开始拉全量 `tools/list`，**1w 个工具会直接压垮客户端与模型上下文**。因此：

| 要求 | 做法 |
|---|---|
| 不暴露全量列表 | `tools/list` 只返回**策展子集**（按客户端配置，如某业务线的 30 个） |
| 提供搜索元工具 | 注册一个 `search_tools(query, scope?, k?)` 工具 |
| 按需取详情 | 提供 `get_tool(code)` 返回完整 schema |
| 执行 | `call_tool(code, arguments)` |

> 注意：**不要把"帮我选并执行"做成一个 MCP 元工具**，否则职责边界塌陷（见 §15.3）。

### 8.2 接口清单

| 接口 | 协议 | 作用 |
|---|---|---|
| `GET /v1/catalog/taxonomy` | REST | 业务域/系统树（经权限过滤） |
| `POST /v1/tools/search` | REST | 工具检索 |
| `GET /v1/tools/{code}` | REST | 工具完整定义 |
| `POST /v1/tools/{code}/execute` | REST | 执行 |
| `POST /v1/confirmations` | REST | 高风险工具申请确认令牌 |
| `POST /v1/confirmations/verify` | REST | 一次性校验并消费 |
| MCP `search_tools` / `get_tool` / `call_tool` | MCP | 同上三件事 |
| `/api/admin/**` | REST | 管理面（目录、授权、配额、审计） |

**明确不存在**：`route_and_execute`、`ask`、`chat` —— 任何"平台自己决定调什么"的接口。

---

## 9. 授权模型

### 9.1 模型

```
Principal ──< Grant >── 范围(domain | system | tag | tool)
                         + 配额(qps, daily, concurrency)
                         + 约束(ip_cidrs, time_window, require_confirmation)
```

- 层级继承：`domain` grant 自动覆盖其下所有 `system` 与 `tool`
- 多 grant 取**并集**；配额按主体聚合
- 默认拒绝（无 grant 即不可见、不可调）

### 9.2 与检索的耦合

**授权必须先于排序**（§6.2 步骤 1）。1w 规模下建议按 `domain` 做索引分区，使每次检索在几百条内完成。

### 9.3 不可区分原则

"工具不存在" 与 "工具无权访问" **必须返回完全相同的响应**（沿用上一版做法：均为 404 + 相同的错误体）。否则可以靠错误码探测平台里有哪些工具。

---

## 10. 凭据与出站安全

### 10.1 凭据

```
Credential: { id, name, kind, ciphertext, kek_id, rotated_at }
kind: static_header | api_key | basic | oauth2_client | mtls
```

- **信封加密**：数据密钥加密内容，KEK 来自环境变量或 KMS
- API **只写不读**：查询接口返回掩码（`sk-****abcd`），永不回显明文
- 支持**轮换**（双密钥并存窗口）与**访问审计**（谁在什么时候用了哪个凭据）
- 折中方案：若合规不接受平台持有密文，可只存外部 Vault 的引用（`vault://path`）

### 10.2 出站安全（沿用上一版做法，这部分做得对）

```
① 域名白名单（精确 + *. 子域通配）
② 全量 DNS 解析 → 逐地址校验（拒绝回环/链路本地/云元数据/多播/保留；私网需显式 CIDR 放行）
③ 固定已校验 IP 发起连接（杜绝 DNS rebinding）
④ 禁重定向 · trust_env=False · verify=True · SNI/Host 保留
```

调用方永远拿不到目标 URL、HTTP 方法与凭据。

---

## 11. 审计与可观测性

| 维度 | 做法 |
|---|---|
| **审计**（治理事实） | `AuditLog`：谁改了什么、谁调用了什么、结果哈希。**不存明文参数与结果** |
| **Trace**（技术链路） | OpenTelemetry：`frontend → authorize → retrieve → execute → upstream` |
| **指标** | Prometheus：按 `tool / principal / protocol / outcome / domain` 维度的 QPS、p95、错误率、配额拒绝、熔断次数、**检索 recall（离线）** |
| **日志** | 结构化 JSON；参数与结果默认脱敏 |
| **健康检查** | liveness / readiness 分离；readiness 检查 DB、Redis、索引 |

上一版把调用参数与结果**明文**写进 `runtime_trace_log`，v0.2 默认只存摘要 + SHA-256。

---

## 12. 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言/框架 | Python 3.12 + FastAPI | 团队已有积累；此量级不是性能瓶颈 |
| 主存储 | PostgreSQL | 权威数据 + 审计 |
| 向量 | **pgvector** | 一个库搞定；备份/一致性简单；**可水平扩展**（上一版嵌入式 Chroma 是硬伤） |
| 检索 | PostgreSQL FTS/BM25 + pgvector + RRF + cross-encoder | 混合检索 |
| 缓存/计数 | Redis + Lua | 配额、并发、幂等、确认令牌 |
| 迁移 | **Alembic 唯一来源** | 不再有 `init.sql` 与 ORM 双份 DDL |
| 密钥 | KMS 或环境注入的 KEK | |
| 部署 | 容器化、多 worker、**无状态** | 上一版 `--workers 1` + 进程内信号量是硬伤 |
| 前端 | React + Vite | 管理台 |

---

## 13. 目录结构

```
src/toolhive/
├── core/                     # 领域与内核，禁止依赖 web 框架（CI 强制）
│   ├── domain/               #   Tool / Version / Provider / Principal / Grant
│   ├── invocation/           #   执行内核流水线
│   ├── policy/               #   授权、配额、熔断、确认、幂等
│   └── providers/            #   适配器：http / mcp / local（只有"怎么连"）
├── retrieval/                # 检索：索引构建、粗排、精排、评测入口
├── ingestion/                # 导入器 + 元数据规范化 + 富化管线
├── adapters/                 # db / cache / secrets / upstream
├── frontends/
│   ├── mcp/  rest/  admin/
├── observability/
└── builtin_tools/            # 平台元能力（准入规则见 §16.6）

eval/                         # 检索评测：标注集 + 指标脚本（M0 交付物）
tests/
├── unit/  integration/  e2e/
└── architecture/             # 架构断言
```

### 13.1 工具实现放哪（重要）

> **ToolHive 里不存在"工具实现"这个概念。ToolHive 只存"怎么调用它"的声明。**

| 类型 | 典型场景 | 实现放哪 | 平台侧 Provider |
|---|---|---|---|
| ① 纯声明式 | 标准 REST 接口 | 不存在代码 | `http` |
| ② 声明式 + 变换 | 类型转换、字段拼接 | 映射表达式 | `http` |
| ③ 需要写代码 | 调内网 SDK、组合多上游 | **业务方自己的工具服务**（暴露为 MCP） | `mcp` |
| ④ 平台元能力 | 时间、UUID、哈希 | 平台仓库 `builtin_tools/`，有准入规则 | `local` |

**①②占工具总数 70~80%，不写代码，平台侧 SSRF/限流/超时/熔断全部有效。**
③ 走业务方自部署的 MCP 服务，平台通过 `tools/list` 导入——与"导入已有 MCP Server"是同一条流水线。

**代价要承认**：③ 的链路是两跳，第二跳（工具服务 → 真实上游）不受平台治理。因此规则是：**能用声明式表达的，一律不要包一层工具服务。**

---

## 14. 架构约束与质量基线

### 14.1 架构约束（CI 强制）

1. `core/` 不得 import `fastapi` / `starlette` / `mcp` / `uvicorn`
2. `adapters/` 不得反向依赖 `frontends/`
3. `frontends/` 之间不得互相 import
4. 工具命名必须符合 `<domain>.<system>.<entity>.<action>`
5. `builtin_tools/` 不得 import `httpx` / `sqlalchemy`（保证纯函数）

### 14.2 架构适应度函数示例

```python
# tests/architecture/test_core_is_framework_free.py
import ast
from pathlib import Path

FORBIDDEN = {"fastapi", "starlette", "mcp", "uvicorn"}

def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots

def test_core_is_framework_free():
    offenders = [
        f"{p}: {sorted(bad)}"
        for p in Path("src/toolhive/core").rglob("*.py")
        if (bad := _import_roots(p) & FORBIDDEN)
    ]
    assert not offenders, "core/ 不允许依赖 Web 框架或协议库:\n" + "\n".join(offenders)
```

### 14.3 质量基线（第一天就有）

| 项 | 内容 |
|---|---|
| Lint / 类型 | ruff + mypy |
| 单元测试 | 内核、策略、映射、导入器 |
| 集成测试 | testcontainers（PostgreSQL + Redis） |
| **契约测试** | OpenAPI 快照 + MCP schema 快照（防止无意破坏调用方） |
| **E2E** | 导入工具 → 发布 → 检索 → 通过 MCP 调用 → 通过 REST 调用 → 断言配额与审计 |
| **检索评测** | 标注集上跑 `recall@k` / MRR / nDCG，**CI 门禁** |
| 架构断言 | §14.1 的五条 |

### 14.4 评测集怎么攒（M0）

- 初期：人工构造 200 条 `query → 正确工具` 标注（覆盖各业务域）
- 中期：从真实调用中采样，人工确认（把线上成功调用转成标注）
- 长期：把"检索后调用成功"当作弱标注，配合人工抽检
- **每次改描述 / 改索引 / 换模型都跑一遍，指标下降则禁止合并**

---

## 15. 职责边界：谁决定"调什么"

这是本平台最容易被误解的一点，单独说明。

### 15.1 分工

| 环节 | 谁负责 |
|---|---|
| 理解用户意图 | **调用方**（Agent / 业务系统） |
| 决定调用哪个工具 | **调用方** |
| 生成调用参数 | **调用方**（平台只做 schema 校验） |
| 找出候选工具 | **平台**（检索） |
| 判断"能不能调" | **平台** |
| 判断"怎么调" | **平台** |
| 实际执行 | **平台** |
| 记录与审计 | **平台** |

### 15.2 为什么平台不做"选哪个"的决定

1. **做决策需要业务上下文**：对话历史、用户画像、业务规则，这些都在调用方手里。平台要做决策，就得把它们都收进来，于是变成业务系统。
2. **确定性是平台的核心资产**：平台承诺"说调 A 就调 A"、"无权就是无权"。引入 LLM 决策就引入了非确定性，授权与审计将无法解释。
3. **上游系统会因此要求平台做更多**：一旦平台开始选工具，下一步就是"顺便帮我生成答案"，边界会一路后退到变成一个 Agent。

### 15.3 由此推出的接口约束

- **不提供** `route_and_execute` / `ask` / `chat` 这类"内容进、答案出"的接口
- MCP 前端只暴露 `search_tools` / `get_tool` / `call_tool`，**不暴露"帮我选并执行"的元工具**
- 调用方拿到的是**候选列表**和**执行结果**，永远不是"平台替你做的决定"

> 如果将来确实需要"一段话进、答案出"的能力，它应当作为**独立的上层系统**建设，把 ToolHive 当作它的工具层通过 API 消费，而不是把该能力塞进 ToolHive。

---

## 16. 规模演进与分期

### 16.1 规模分档（架构按 1w 设计，实现分阶段放量）

| 规模 | 检索要求 | 元数据要求 | 治理要求 |
|---|---|---|---|
| **< 100** | 可全量返回列表，检索可选 | 人工审可行 | 逐个审核可行 |
| **100 ~ 1k** | 需要检索；scope 缩小开始重要 | 需要规范化命名 | 需要按域授权 |
| **1k ~ 1w** | 需要 rerank；需要去重；索引分区 | **需要富化管线** | **不可能逐个审批，需要按来源信任策略** |
| **> 1w** | 多路召回融合；需要工具策展（淘汰无人用的） | 需要持续质量监控 | 需要分层授权与配额治理 |

> 当前前提：目标 1w+，**逐步导入**。因此 M0 阶段工具数会远小于 1w——**但下面这些必须从第一天就按 1w 的方式设计**，否则后期返工：
> `source_ref` 稳定身份、`domain/system/tags` 元数据、命名规范、索引版本化、批量操作、按域授权。
> 而 rerank、去重、多路融合可以等到量上来再加。

### 16.2 M0：小规模端到端闭环（目标：跑通 + 可演示）

| # | 交付物 |
|---|---|
| 1 | 领域模型 + Alembic 首个迁移 |
| 2 | Principal / Grant + 授权判定 |
| 3 | **OpenAPI 导入器**（先支持一种来源）+ `source_ref` 幂等重导 |
| 4 | 元数据规范化 + 命名规范（富化管线先只做规则，不接 LLM） |
| 5 | **工具检索（简版）**：权限过滤 + BM25 + 单路向量 + scope |
| 6 | **执行内核**：http provider + 配额 + 幂等 + 审计 |
| 7 | **REST 前端**（MCP 前端紧随其后） |
| 8 | **评测集 v0（100~200 条）+ recall@k CI 门禁** |
| 9 | 架构断言 + CI 流水线 |
| 10 | 一条 E2E：导入 → 发布 → 检索 → 执行 → 断言配额与审计 |

**M0 验收**：工具数 ≥ 100 时可演示"调用方说一句话 → 检索到正确工具 → 执行成功 → 审计可查"。

### 16.3 M1：放量到 1k

- MCP 导入器 + 统一规范化层合并两路
- **MCP 前端**（搜索式暴露）
- **凭据保管与注入**（解锁真实内部工具）
- 富化管线接入离线 LLM
- rerank 上线 + 评测集扩到 500 条
- 管理前端（目录、授权、配额、审计）

### 16.4 M2：放量到 1w

- 去重与相似工具检测
- 索引分区 + 多路召回融合
- 按来源信任策略的自动发布 + 批量操作
- 工具策展：识别长期零调用的工具
- 索引版本化切换（换 embedding 模型）演练

### 16.5 M3：治理增强（按需）

- 细粒度权限（在资源+动作模型上扩展，不枚举端点）
- 审批流（仅对高风险/对外工具）
- 计量与配额治理看板

### 16.6 `builtin_tools/` 准入规则

1. 只能是元能力：时间、UUID、哈希、编码转换
2. 不得有业务语义（禁止 `crm.*` 这类编码）
3. 数量上限 10 个
4. 不得访问网络或数据库（纯函数，CI 断言）

---

## 17. 待确认事项

| # | 事项 | 影响 |
|---|---|---|
| 1 | 是否代持上游凭据，还是只存 Vault 引用？ | 决定平台能覆盖多少真实工具 |
| 2 | 业务方是否具备独立部署工具服务的能力？ | 决定 ③ 类工具是否可行；若不可行需增加"工具托管运行时" |
| 3 | 检索的 `scope` 由调用方提供还是平台推断？ | 决定接口形态与精度上限 |
| 4 | 审批流是否一期就要？ | 决定状态机复杂度 |
| 5 | embedding 模型选型与是否自建 | 决定索引版本化与成本 |
| 6 | 向量与关键词的融合权重是否需要按域调参 | 决定评测集的分域覆盖要求 |
