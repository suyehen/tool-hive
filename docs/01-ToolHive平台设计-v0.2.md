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
| 1 | **知道有哪些工具能选** | 调 `POST /v1/tools/search`（自然语言 → 候选列表）；MCP 的 `search_tools` 元工具为 **M1** 提供 |
| 2 | **把选中的工具跑起来** | 调 `POST /v1/tools/{code}/execute` 传参数；MCP 的 `call_tool` 为 **M1** 提供 |
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
| C1 | 上一版有**两套并行编排**（REST 一份、MCP 一份），导致 MCP 通道没有配额/幂等 | **协议前端必须是薄适配器，执行逻辑与错误语义只能有一份** |
| C2 | 接一个工具要十几步手工填写，没有导入 | **接入自动化是核心产品循环** |
| C3 | 治理重量远超价值（39 个操作码 / 118 个管理接口 / 31 张表服务于 1 个占位工具） | **治理能力可配置，默认轻** |
| C4 | 不代持凭据 → 真实工具接不进来 | **凭据保管与注入是必选项** |
| C5 | 嵌入式向量库 + 单 worker + 进程内并发计数 | **无状态 + 分布式限流 + 可扩展的单一存储** |
| C6 | 手写 `init.sql` 与 ORM 双份 DDL、无 CI、无前端测试 | **迁移单一来源 + 质量基线第一天就有** |

### 2.1 合规约束（已确认）

> **数据不出境。** 平台依赖的所有模型服务（embedding、以及离线富化可能用到的 LLM）必须部署在境内，不得调用境外 API。

这条约束影响：embedding 服务选型（§6.4）、技术选型（§12）、离线富化管线的模型选择（§5.4）。

---

## 3. 核心概念与分层

### 3.1 三个核心概念

| 概念 | 做什么 | 输入 → 输出 | 是否用生成式模型 |
|---|---|---|---|
| **授权与可见性** | 一个**贯穿始终的约束**：调用方只能看见、只能调用自己被授权的工具 | 调用方身份 → 可见工具集合 | 无 |
| **工具检索** | 把一句自然语言变成候选工具列表 | `query (+范围过滤)` → top-k 候选 | 无（仅判别式模型） |
| **执行内核** | 把"工具 + 参数"安全地跑出结果 | `(工具, 参数)` → 结果 | 无 |

> **请求路径上不引入生成式模型。**
> 被禁止的是**生成式决策**——让模型生成"该调哪个工具"或"答案文本"。
> **判别式模型是允许的**：embedding 与 reranker 都只输出向量或分数，确定、无幻觉、不可被 prompt 注入。平台的确定性资产就在这里。

### 3.2 分层架构

```
┌─ 协议前端（薄，只做协议翻译，禁止业务逻辑）────────────────────┐
│   MCP 前端（搜索式暴露）   REST 前端   管理前端/API              │
└──────────────────────────┬──────────────────────────────────┘
                           │ 统一内部契约 ToolInvocation
┌──────────────────────────▼──────────────────────────────────┐
│  执行内核（唯一实现）                                          │
│  下列仅列**能力**；**能力清单须与 §7.1 的步骤一一对应**，       │
│  实际阶段顺序也以 §7.1 为准，避免两处漂移。                     │
│  版本解析 · 授权判定 · QPS 限流 · 时间窗/IP 约束                │
│  · 幂等（查询/认领）· 参数校验 · 确认令牌 · 日配额与并发        │
│  · 熔断 · 凭据注入 · 出站执行 · 输出校验 · 审计与 Trace         │
├──────────────────────────────────────────────────────────────┤
│  工具检索                                                     │
│  权限过滤 → 关键词(pg_trgm) ∥ 向量 → RRF → 精排(可选) → top-k       │
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

> **两条全局约定**（所有表都适用，下表只列业务字段，**不重复列这两组**）：
>
> **① 主键统一雪花算法**：`id bigint PRIMARY KEY`，由应用层生成（配置 `TOOLHIVE_SNOWFLAKE_DATACENTER_ID` / `WORKER_ID`），
> 数据库不用自增或序列；所有外键同为 `bigint`。
>
> **② 审计字段每表必备**：`create_by_id` / `create_by_name` / `create_time` / `update_by_id` / `update_by_name` / `update_time`。
> 三条要点：
> - `*_by_name` 是**写入时刻的名称快照**，不随账号改名而变
> - **审计字段不加外键**（操作人可能已离职、也可能是服务型 Principal）
> - **追加型表（日志/事件）只填 `create_*`**，`create_by` 即"触发该记录的操作人"——因此这些表
>   **不再单设 `actor_id` / `reviewer_id` 之类的重复字段**
>
> 完整可执行 DDL 见 `03-表结构DDL-v0.2.md`。

| 实体 | 职责 | 业务字段 |
|---|---|---|
| `Principal` | 调用主体（**统一**人与机器） | `type(user\|service\|agent), tenant_id, name, display_name, status, row_version` |
| `ApiKey` | **调用方凭证**（M0 的认证载体） | `principal_id, key_prefix`（明文前缀，便于识别与轮换）、`key_hash`（argon2）、`status(active\|revoked)`、`expires_at`、`rotated_at`、`last_used_at` |
| `Credential` | 上游凭据（加密存储，只写不读） | `name, kind, ciphertext, external_ref, kek_id, meta, rotated_at` |
| `Provider` | 上游连接定义 | `code, name, type(http\|mcp\|local), base_url, auth_ref, tls_config, limits, status, row_version` |
| `Tool` | 逻辑工具 | `code, source_ref, provider_id`（**来源**，区别于绑定的 provider_id）、`name, description, domain, system, tags[], risk, executable, discoverable, review_required, input_schema, output_schema, status, owner, row_version` |
| `ToolVersion` | 不可变版本快照 | `tool_id, version, 定义字段快照, status, review_comment, submitted_at, published_at, row_version` |
| `ToolChannel` | 发布通道 | `tool_id, name(stable\|beta\|canary), version_id` |
| `ExecutionBinding` | 执行绑定 | `version_id, provider_id`（必填）；`method, path_template, param_mapping`（**`mcp` 类型全为空**；**`local` 仅 `method="COMPUTE"`**；`http` 三者必填，见 §4.3）；`timeout_seconds, retry_max`（可空，取默认值） |
| `ReviewRecord` | 审批留痕（§4.3，**追加型**） | `version_id, action(submit\|approve\|reject), from_status, to_status, comment`（审批人即 `create_by_*`） |
| `Grant` | 主体 × 范围 × 配额 | `principal_id, scope_type(domain\|system\|tag\|tool), scope_value, quota, constraints, status` |
| `IndexMeta` | 索引版本元数据（§6.5/§6.4） | `index_version, model, dimension, status(building\|active\|retired), activated_at, retired_at` |
| `ToolEmbedding` | 向量索引数据（§6.5） | `tool_id, index_version, chunk_kind(name\|description\|combined), embedding, content_hash` |
| `Invocation` | 每次调用记录（**追加型**） | `trace_id, principal_id, tool_id, version_id, protocol, outcome, error_code, duration_ms, request_digest, result_digest, result_bytes` |
| `AuditLog` | 治理事件（谁改了什么，**追加型**） | `action, object_type, object_id, result, before_summary, after_summary, trace_id`（操作人即 `create_by_*`） |
| `SearchEvent` | **检索事件**（§11.1；评测采样的唯一来源，**追加型**） | `trace_id, principal_id, query`（截断+脱敏）、`scope, top_k, returned, total_candidates, degraded, latency_ms` |
| `OutboxEvent` | 索引/通知的异步投递 | `event_type, object_type, object_id, payload, status, attempts, next_retry_at, locked_by, locked_until, last_error` |

> **一个 `Principal` 可以有多个 `ApiKey`**（便于轮换：先建新 key、切流、再吊销旧 key）。
> 认证时按 `key_prefix` 定位候选，再校验 `key_hash`；`status=revoked` 或过期即拒绝。
> **明文 key 只在创建时返回一次**，此后只存哈希。

> **关于 `entity` / `action`**：命名规范是四段（§5.3），但实体与动作**由 `code` 字符串承载，不作为独立字段**。
> 需要在授权或检索时按实体/动作过滤时，由富化阶段把它们写入 `tags`（如 `entity:customer`、`action:query`），
> 从而通过 `scope={tags:[...]}`（§6.1）与 tag 授权（§9.1）实现——避免为每个工具维护更多字段。

> **关于 `tenant_id`**：M0/M1 **不参与任何过滤**，只是预留。
> 未来启用多租户时，语义固定为：**所有查询强制带 tenant 过滤，`Grant`、检索索引、配额计数均按 tenant 隔离**。
> 提前写下这条，是为了避免将来"字段在但语义没定义"导致返工。

> **三个状态位在 M0 的取值**（此前 `executable` / `discoverable` 只出现在文字里、不在模型中，已补为字段）：
>
> | 字段 | 含义 | M0 取值 |
> |---|---|---|
> | `executable` | 是否允许执行。**为 false 时检索结果也会把它过滤掉**（见 §16.2） | 判定条件与内核确认判定对齐：**写方法或 `risk=high`**（D14） |
> | `discoverable` | 是否出现在检索结果里（用于"可执行但不该被搜到"的内部工具） | 默认 `true` |
> | `review_required` | 该工具的版本是否必须走审批 | **M0 恒为 `true`**（M1 起支持按来源信任策略，§4.3） |

> **`Tool.status` 的取值集合**（统一在此列举一次，避免各节各写一个）：
>
> | 取值 | 含义 | 可否调用 |
> |---|---|---|
> | `enabled` | 正常 | ✅ |
> | `disabled` | 人工停用 | ❌ |
> | `stale` | **上游已消失**（§5.5 重导比对产生） | ✅ **仍可调用**，但管理侧标红提醒，等待人工决定废弃或归档 |
> | `archived` | 终态 | ❌，且不可修改 |
>
> 注意与 `ToolVersion.status`（§4.3）区分：`deprecated` / `retired` 属于**版本级**状态，不在本表。

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

> **通道不作为授权维度**（澄清）：任何对该工具有 Grant 的调用方都可以指定 `channel=beta` 或钉死具体版本。
> 这**不构成权限绕过**——因为能挂到通道上的版本**必须状态为 `published`**（§4.3），已经过完整审核。
> **灰度是运维手段，不是权限边界。**
> 若将来确实需要按通道限制（例如 beta 只对内部系统开放），在 `Grant.constraints` 里启用预留字段
> `allowed_channels` 即可（M0/M1 不实现，但语义先定死）。

**③ 用 `tags[]` + `domain/system` 做分组，不引入"能力包"实体。**

授权按 `domain` / `system` / `tag` 层级继承，1w 规模下**不可能逐个工具授权**。

### 4.3 版本状态机（含简单审批流）

**审批流为默认路径，但只做最简状态流转**——不做多级审批、不做会签、不做审批流配置引擎。

```
draft ──送审──→ pending_review ──通过──→ published ──→ deprecated ──→ retired
  ↑                   │
  └───── 驳回 ────────┘  (rejected → 修改后可重新送审)
```

| 规则 | 说明 |
|---|---|
| 审批粒度 | **按 ToolVersion**（一个版本一次审核），不是按流程实例 |
| 审核记录 | 一张 `ReviewRecord` 表：`version_id, reviewer_id, decision, comment, created_at` |
| 送审前置条件 | **`input_schema` 必需**（参数校验的依据）、**`output_schema` 可空**（为空则跳过输出校验）、必须有**执行绑定**（按 Provider 类型分支，见下方修正说明） |
| 发布前置条件 | 状态必须是 `pending_review` 且已被通过 |
| 首次发布 | 必须设置 `stable` 通道指向该版本 |
| 免审通道 | `Tool.review_required` 字段保留：置 false 时导入后可直接发布（M1 起支持"按来源信任策略"自动设置） |

**为什么保留这个开关**：1w 工具规模下不可能逐个审核（见 §16.1）。M0 阶段工具量小、逐个审可行；放量后必须能按来源免审，否则审批会成为瓶颈。因此字段从 M0 就在，只是 M0 默认 `true`。

> ⚠️ **关于执行绑定（一处规则矛盾，已修正）**
>
> 此前 §5.2 写"MCP 类型不需要 binding"，与本节"送审必须有执行绑定"**自相矛盾**。
> 推论是致命的：**MCP 导入的工具永远无法送审 → 无法发布 → 无 stable 通道 → 不可调用**，
> 把 §16.3 里 M1 最重要的一条路径（MCP 客户端接入）自己堵死了。
>
> **修正口径**：**每种 Provider 类型都必须有一条 `Binding`**，它是"这个版本通过哪个 Provider 出去"的**唯一表达**。
>
> | Provider 类型 | Binding 必须包含 |
> |---|---|
> | `http` | `provider_id` + `method` + `path_template` + `param_mapping` |
> | `mcp` | **只填 `provider_id`**，映射字段留空 |
> | `local` | `provider_id` + `method="COMPUTE"`（无出站） |
>
> 送审校验**按类型分支**：`http` 校验映射完整性；`mcp` / `local` 只校验 `provider_id` 存在且 Provider 处于启用状态。

> ⚠️ **`output_schema` 不是送审前置条件**（同类矛盾，已修正）
>
> 此前本节要求"必须有 `output_schema`"，而 §5.2 说它"可为空（不阻塞）"——直接冲突。
> 后果与上面那个 binding 矛盾**完全同类**：**OpenAPI 文档里大量接口没有 response schema**，
> 按前者这些工具**全部无法送审 → 无法发布 → 不可调用**。
>
> 统一口径：
>
> | 字段 | 是否必需 | 理由 |
> |---|---|---|
> | `input_schema` | **必需** | 它是参数校验（§7.1 第 5 步）的唯一依据，没有它无法安全执行 |
> | `output_schema` | **可空** | 为空时**跳过 §7.1 第 11 步输出校验**，其余流程不变 |
> | 执行绑定 | **必需** | 见上方 Provider 类型分支表 |

#### M0 实现的状态范围

M0 **只实现** `draft → pending_review → published / rejected`，加上工具级启停 `disabled`；
`deprecated` / `retired` 的**枚举值保留，但不提供迁移接口**，完整生命周期属于 M1。
（本节为权威口径，与 §16.2 交付物保持一致。）

#### Channel 与版本状态的交互规则

| 场景 | 规则 |
|---|---|
| 废弃 / 归档一个**被 Channel 指向**的版本 | **拒绝**，返回 `TH_CHANNEL_REFERENCES_VERSION`；必须先把通道切到别的版本 |
| 删除版本 | **不允许**。`ToolVersion` 是不可变快照，正常流程不删除（历史调用记录要能回溯） |
| Channel 指向的版本被上游标记 `stale` | **允许**，但在通道上打告警标记，管理侧可见（避免上游变更导致静默失效） |
| 创建 / 切换 Channel | 必须校验目标版本存在**且状态为 `published`** |
| 工具**没有 stable 通道** | 该工具视为**不可调用**，调用方得到 `TH_TOOL_NOT_FOUND`（与"未发布"同义，遵守 §9.3 不可区分原则） |
| 首次发布 | **必须同时把 `stable` 指向该版本**，否则工具发布后不可调用 |

> 选"拒绝废弃"而不是"自动回退到上一个 published 版本"：**自动回退会让生产流量静默切到另一个版本**，
> 这比报错更危险——调用方拿到的结果会悄悄变化。宁可让运维显式切换。

---

## 5. 工具接入管线（核心）

> 1w 工具不可能手工登记。**接入管线是平台能否成立的前提，不是效率优化。**

### 5.1 两路导入

| 来源 | 输入 | 稳定标识 | 说明 |
|---|---|---|---|
| OpenAPI 导入 | OpenAPI 3.x / Swagger 2.0 文档（URL 或文件） | `operationId`（缺失时用 `method+path` 哈希） | 一个 `operation` → 一个 Tool |
| MCP 导入 | 一个 MCP Server 地址 | `server_code + tool.name` | 一个 `tools/list` 条目 → 一个 Tool |

> ⚠️ **本文档提到两处 MCP，是两套完全不同的技术栈，不要混为一谈：**
>
> | | **MCP 客户端** | **MCP 服务端** |
> |---|---|---|
> | 做什么 | 连**上游** MCP Server，拉 `tools/list`、发 `tools/call` | 把 **ToolHive 自己**暴露为 MCP Server |
> | 出现在 | §5.1 MCP 导入；§13.1 ③ 类工具（Provider `type=mcp`） | §8.1 MCP 前端 |
> | 技术要点 | 会话管理、重连、上游超时、上游认证 | transport、transport security、Host 校验、工具暴露策略 |
> | 交付阶段 | M1（MCP 导入器） | M1（MCP 前端），**两者独立交付、无依赖关系** |
>
> **M0 两者都不做。**

> **已知边界**：MCP 的稳定标识含 `tool.name`，上游改名会被识别为"新增 + 消失"。
> 缓解手段（M1 改进项）：用 `description + inputSchema` 的哈希做辅助匹配，命中则视为同一工具的重命名而非新增。

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
| `binding` | method + path + 参数落点 | **只填 `provider_id`（映射字段留空）** | **两者都必须有 Binding**，见 §4.3 的修正说明 |

> **注意最后几行**：业务域、系统、标签在这两种来源里**通常都不存在**，而它们是检索精度的基础。这就是富化管线存在的理由。

### 5.3 命名规范（导入时强制）

```
<domain>.<system>.<entity>.<action>
例：crm.customer.query / aftersale.ticket.create / erp.inventory.adjust
```

- 由导入配置提供 `domain` / `system`，`entity` / `action` 从 operationId 或路径推断
- 冲突时**不覆盖**，生成 `xxx.2` 并要求人工确认
  （**`source_ref` 是去重主键**；`code` 冲突只影响展示名，**不影响重导匹配与历史关联**）
- 规范由 CI 断言（见 §14.1）

### 5.4 元数据富化管线

导入进来的原始数据质量通常很差：`summary` 可能是 `"GET /api/v1/t2"` 或空，`operationId` 可能是 `getT2UsingGET`，业务域与标签基本没有。**而检索质量完全取决于被索引的文本。**

因此分两级，**M0 只做第一级**。

#### ① 规则富化（M0 必做，不涉及 LLM）

```
原始条目
  → [1] 结构化提取：从路径/参数推断实体与动作（/customers/{id} → entity=customer, action=query）
  → [2] 打标：domain/system 取自导入配置；tags 取自路径与读写属性；risk 按 HTTP 方法推断
  → [3] 命名规范化：<domain>.<system>.<entity>.<action>
  → [4] 生成 embedding，写入索引
```

纯代码实现，无模型依赖。

> **注意：富化不生成 `one_liner`**。检索响应里的 `description_snippet` 是**查询时对 `description` 截断**产生的
> （§6.1），不是存储字段——避免为 1w 个工具维护一个没人写的字段。

#### ② 描述补全（**可选，由评测触发**；若启用则只在离线批处理）

**触发条件**：评测集证明"检索失败的主要原因是被索引的文本太差"，才引入这一步。用 LLM 从路径、参数、响应结构推断人类可读的描述（把 `getT2UsingGET` 补成"根据客户 ID 查询客户档案"）。

三条约束：

1. **只用于离线批处理，不进请求路径** —— §3.1「请求路径无 LLM」的原则不因此改变
2. 生成的描述**必须落库并带版本**，可人工修订、可回滚
3. **是否引入由数据决定，不预设** —— 若上游 OpenAPI 文档本身的描述质量足够好，这一步可能永远不需要

> 换句话说：**LLM 富化是"评测证明描述质量是瓶颈"之后的补救手段，不是平台的预设能力。**

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
  "k": 30                           // 1..50，上限 50
}
→ {
  "items": [
    {
      "code": "aftersale.ticket.list",
      "name": "查询工单列表",
      "description_snippet": "按客户查询售后工单",   // description 截断（默认 80 字符）
      "matched_reason": ["投诉", "客户"],           // 关键词路命中的 token，最多 3 个
      "score": 0.87
    }
  ],
  "total_candidates": 187,          // 权限过滤 + scope 收窄后的候选总数
  "degraded": false,                // 向量不可用时降级为关键词
  "trace_id": "..."
}
```

**候选条目的字段来自哪里**（此前未定义，实现者只能自己编——现予明确）：

| 字段 | 来源 |
|---|---|
| `code` / `name` | `Tool` 表字段 |
| `description_snippet` | **查询时对 `Tool.description` 截断**（默认 80 字符，长度可配）。**不新增 `one_liner` 字段**——理由：1w 工具下没人维护它，规则富化（§5.4 ①）也无从生成；截断是确定性且零成本的。若将来启用 §5.4 ② 的描述补全，snippet 质量会**自动提升，仍不需要新字段** |
| `matched_reason` | **关键词路（`pg_trgm`）命中的 token 列表**，最多 3 个；纯关键词路未命中时为空数组。**它是解释性字段，不参与排序** |
| `score` | RRF 融合分（未启用精排时即最终分） |

> `total_candidates` = **经过权限过滤与 scope 收窄后的候选总数**（不是全平台工具数），
> 供调用方判断"要不要放宽 scope 或调大 k"。

> **`description_snippet` 用数组/字符串的选择**：`matched_reason` 定为**数组**而非"命中『x』『y』"这类字符串，
> 因为**平台不该编码展示格式**——拼成人话是调用方（或上层 Agent）的事。

```
GET /v1/catalog/taxonomy
→ { "domains": [ { "code": "aftersale", "name": "售后",
                   "systems": [ { "code": "ticket", "name": "工单", "tool_count": 42 } ] } ] }
```

**`taxonomy` 接口的意义**：调用方（通常是 Agent）不知道这 1w 个工具是怎么分域的。给它一个"缩小范围的抓手"，就能把检索从 1w 缩到几百——**这是 1w 量级下提升精度最有效的杠杆**。

> **不支持翻页**（澄清）：混合检索 + 可选精排的排序**本身不稳定**（同一 query 两次可能顺序微变），
> 深翻页的 `cursor` 语义无法定义。因此检索**只返回 top-k**；需要更多候选就调大 `k`（上限 50）。
> 在"挑候选工具"这个场景里，深度翻页本来也没有意义。

### 6.2 检索流水线

```
query + scope
  → [1] 权限过滤：得到该调用方可见的工具集合（1w → 可能 200）
  → [2] scope 缩小：按 domain/system/tags 进一步收窄
  → [3] 粗排（召回）：关键词相似度 ∥ 向量相似度 → RRF 融合 → top-100
  → [4] 精排：reranker 重排 top-100 → top-k（**供应商已定，默认关闭**，见下）
  → [5] 轻量返回：只带 code/name/description_snippet/score（约 30 token），不带完整 schema
```

**必须是"先过滤再排序"**，不能"先取 top-100 再丢掉无权限的"——后者在窄权限调用方那里会返回个位数甚至空结果。

#### 关于"关键词那一半"为什么不能砍

检索是**两路并行再融合**。关键词不是向量检索的备胎，它有独立价值：

| 理由 | 说明 |
|---|---|
| 精确匹配 | 工具编码（`crm.customer.query`）、系统名、内部缩写这类**专有 token**，向量模型经常匹配不好 |
| 短文本 | 工具描述通常只有一句话，短文本的向量区分度天然有限 |
| 降级路径 | embedding 服务不可用时，关键词是唯一还能用的检索方式（§6.6） |

#### M0 的关键词实现：`pg_trgm`，不做中文分词

PostgreSQL 的全文检索（FTS/BM25）依赖**分词**，而中文分词需要额外安装 `zhparser` / `pg_jieba` 这类数据库扩展，运维成本高、效果也依赖词典。

**`pg_trgm`（字符三元组相似度）按字符匹配而非按词匹配，天然绕开中文分词问题**，且只依赖标准 contrib 扩展。

代价：没有 IDF / 词权重，相关性排序不如真正的 BM25。

**策略**：
- **M0 用 `pg_trgm`**，先把中文分词的坑绕过去
- 若评测（§6.7）显示关键词这一路贡献不足，再评估是否引入 `zhparser` + BM25（M1/M2）

> 因此 **M0 不引入任何分词方案**——这是一个被绕开的问题，不是被解决的问题。
>
> **部署前置条件**：`pg_trgm` 在 PostgreSQL 的 contrib 包里，**目标服务器当前尚未安装**
> （实测可用扩展只有 `plpgsql` 与 `vector`）。需先装 `postgresql-contrib`
> （OpenCloudOS / RHEL 系：`yum install postgresql15-contrib`）并执行 `CREATE EXTENSION pg_trgm`。
> 这属于**环境准备**，不影响本节的设计选型。

#### 精排（可选，默认关）：reranker，**不是 LLM**

精排用 **cross-encoder reranker**：**判别式模型，只输出一个相关性分数，不生成任何文本**——因此它不是 LLM，
**不受 §3.1「请求路径不引入生成式模型」的限制**。

它的工作原理、与 embedding 的本质区别、以及 O(N) 的代价分析见 **§18 附录 A**（此处不展开，避免与主线篇幅失衡）。

**是否引入精排由评测决定（不看拍脑袋）**：

| recall@k 曲线 | 诊断 | 该做什么 |
|---|---|---|
| recall@5 低、recall@30 高 | **排序问题**：正确工具在候选里但排太后 | ✅ 上精排，收益最大 |
| recall@30 也低 | **召回问题**：正确工具根本没进来 | ❌ 精排无用，改元数据 / embedding / 多路召回 |
| 两者都高 | 已经够好 | 不做，省成本 |

**供应商已确定：DashScope `qwen3.7-text-rerank`**

```
POST {RERANK_ENDPOINT}     # 形如 https://<workspace>.cn-beijing.maas.aliyuncs.com
                           #        /api/v1/services/rerank/text-rerank/text-rerank
Authorization: Bearer {DASHSCOPE_API_KEY}
{
  "model": "qwen3.7-text-rerank",
  "input": {
    "query": "查一下这个客户的投诉记录",
    "documents": ["域.系统.工具名.描述", "..."]     // ← 粗排返回的候选文本
  },
  "parameters": { "top_n": 30, "return_documents": false }
}
```

- 一次调用 = **1 个 query + N 个候选文档**，返回按相关性排序的结果（含候选下标与相关性分数）
- **`top_n` 直接设为要返回的 `k`**；`return_documents=false` 减少回传体积
- ⚠️ **响应字段名以真实调用为准**：首次接入时确认（预期形如 `output.results[].index` / `relevance_score`），
  适配器要做字段容错，**不要把猜测的字段名写死**
- **这是"平台自身的出站"**（与 §6.4 的 embedding 同类）：域名固定，**不走 Provider 的 SSRF 白名单**，
  但需要独立的超时、重试、熔断与降级；密钥由环境变量注入，**不落代码库、不落日志**
- **数据暴露**：请求包含用户的 `query` 原文与工具元数据。这与 embedding 的既有情况相同（§6.4 已如此），
  **未新增暴露类别**，但属于已接受的边界，合规评审时需一并说明

#### 延迟影响（重要，改变了检索的画像）

这是一次**跨网络的远程调用**，p95 通常在 **150–400ms**，比本地部署的 cross-encoder **高一个量级**（延迟表见 §18 A.4）。
因此**启用精排会显著改变检索延迟**，必须按 §6.7 的两套 SLO 分别考核。

可选缓解：把送排候选数从 100 降到 **20–30**（远程调用的耗时与文档数正相关）。

#### 启用策略

- **默认关闭**（`retrieval.rerank.enabled = false`）。理由**不再是"没有供应商"，而是延迟与成本**
- 管线的精排阶段保留；未启用时**等价于 no-op**，直接采用 RRF 顺序。
  这是**设计内行为，不置 `degraded` 标记**（`degraded` 只表示"发生了故障降级"）
- **由评测决定是否开启**：只有诊断出"**排序问题**"（recall@5 低、recall@30 高）时才开；
  开启前后各跑一次评测集做 A/B，用数据说话
- ⚠️ **TODO（实现时必须在代码中保留标记）**：
  - `retrieval/rerank/` 提供统一 `Reranker` 接口 + **no-op 实现（默认）** + **DashScope 适配器**
  - 配置项：`retrieval.rerank.enabled`（默认 `false`）、`endpoint`、`model`、`api_key`、`timeout_ms`、`max_candidates`
  - 降级路径按 §6.6：精排超时/失败 → 返回 RRF 顺序并置 `degraded=true`

### 6.3 上下文预算控制

1w 工具下，返回完整 schema 会撑爆上下文。因此**两段式取详情**：

```
search(k=30) → 轻量候选（每个约 30 token，合计 ~900 token）
   ↓ 调用方挑出 3 个
GET /v1/tools/{code} → 完整定义（含 input_schema）
```

### 6.4 embedding 服务（外部依赖，已选定）

已确认使用**现成的境内模型服务**，接口为 OpenAI 兼容格式：

```
POST {TOOLHIVE_EMBEDDING_BASE_URL}/v1/embeddings
Authorization: Bearer {TOOLHIVE_EMBEDDING_API_KEY}
{ "model": "kinfra-text-embedding-4b", "input": ["...", "..."] }
```

> ⚠️ **密钥不落代码库、不落文档**：通过环境变量或平台的 `Credential` 注入。上文中的 base_url / model 为配置项，实际取值见部署环境。

**它有两类完全不同的调用场景，必须分开设计：**

| 场景 | 时机 | 批量 | 要求 |
|---|---|---|---|
| **离线批量嵌入** | 导入 / 重建索引 | 1w 工具 × 若干字段 | 分批 + 限流 + 断点续传，可跑几小时 |
| **在线查询嵌入** | 每次 `search` | 1 条 | **严格超时（建议 800ms）**，失败立即降级 |

**关键设计点：**

1. **它是"平台自身的出站"，不是"调用方触发的出站"。** 因此不走 Provider 的 SSRF 白名单那套（域名固定可信），但必须有**独立的超时、重试、熔断与降级**。
2. **向量维度已实测为 2560**（`kinfra-text-embedding-4b`），写入 `index_meta.dimension`。
   2560 维**超过 pgvector 对 `vector` 类型的 2000 维索引上限**，因此列类型用 **`halfvec(2560)`**
   （上限 4000 维，已实测可建 HNSW 索引）——细节见 `03-表结构DDL-v0.2.md` §4.1。
   **换模型时维度可能变**，这也是 §6.5 索引版本化存在的原因
3. **在线嵌入失败一律降级为关键词检索**（`degraded=true`），不得让检索整体失败。
4. **成本要预估**：1w 工具全量重嵌的成本与耗时，是"换 embedding 模型"这个决策的主要代价。
5. **批量嵌入要能续跑**：中断后从上次位置继续，不要把已经嵌入的再做一遍。

### 6.5 索引版本化（换 embedding 模型）

1w 工具换一次 embedding 模型 = 全量重嵌。因此：

- 向量表带 `index_version`，支持**双版本共存**
- **检索用哪个版本由 `retrieval.active_index_version` 唯一决定**（不是"自动选最新"）——
  显式配置才能让切换成为可回滚的一步操作
- **切换流程**：新版本后台重建 → 在评测集上跑一遍指标 → 改 `active_index_version` → 观察 → 才算完成
- **旧版本保留期**：切换后**至少保留 7 天**用于回滚；只有在新版本稳定运行且没有未完成的重嵌任务时，
  才由后台任务清理旧版本数据，**不自动删除**
- **一致性约束**：在线查询 embedding **必须用与 active 版本相同的模型**，否则向量空间不一致。
  **但校验方式不能是"两个配置项必须相等"**——那会卡死重建流程：
  重建新索引本来就需要新模型，而 `active_index_version` 仍指向旧模型，两者必然不等。

  正确做法是**基于索引版本元数据校验**：

  | 环节 | 模型来源 |
  |---|---|
  | 重建任务 | 命令参数或独立配置：`toolhive rebuild-index --model <新模型> --index-version v2` |
  | 索引版本元数据 | 重建时把**模型名与维度一起写入** `index_meta`（§6.4 已要求写维度，模型同理） |
  | 在线查询 | 使用 `embedding.model` |
  | **启动校验** | `active_index_version` **元数据里的模型** == 在线 `embedding.model`，不匹配则**拒绝启动** |

  这样约束语义不变（在线查询与索引必须同模型），**但不再阻碍重建**。

### 6.6 降级策略

| 故障 | 行为 |
|---|---|
| 向量服务不可用 | 退回纯关键词检索，`degraded=true` |
| 精排服务不可用 | 直接返回粗排结果，`degraded=true`（**仅当精排已启用时**；未启用属设计内行为，见 §6.2） |
| 两者都不可用 | 返回空并明确报错，**不返回未经排序的全量列表** |

### 6.7 指标：平台对"找得到"负责

> **平台保证"正确工具出现在候选里"，调用方负责"从候选里选对"。**

调用方的 Agent 只能从返回的 top-k 里选。正确工具排在第 21 位而 k=20，它永远找不到，**而且不会知道自己错过了**。所以平台必须对召回率负责：

| 指标 | 目标 | 说明 |
|---|---|---|
| `recall@30` | ≥ 0.95 | 正确工具出现在前 30 的比例 —— **最重要的指标** |
| `recall@5` | ≥ 0.70 | |
| `MRR@10` | ≥ 0.60 | |
| `nDCG@10` | ≥ 0.65 | |
| p95 延迟（未降级路径） | ≤ 200ms | 见下方预算分解 |

**评测集是 M0 交付物，不是后期优化项**（见 §14.4）。

#### 延迟预算分解：把"预算"与"超时阈值"分开

原先把 embedding 的**超时阈值**（800ms）与检索的**p95 预算**（200ms）写在一起，口径不清。正确写法：

| 阶段 | p95 预算 | 超时阈值 | 说明 |
|---|---|---|---|
| 权限 + scope 预过滤 | 20ms | 500ms | 普通 SQL（§9.2） |
| 在线 embedding | 60ms | **800ms** | **800ms 是容错上限，不是预算** |
| 关键词检索（`pg_trgm`） | 20ms | 200ms | |
| 向量检索 | 30ms | 200ms | |
| RRF 融合 | 5ms | — | 内存计算 |
| **合计（基线，不含精排）** | **≈135ms** | | 满足 ≤ 200ms，余下 ~65ms 应对抖动 |
| 精排（启用时） | **+150~400ms** | 500ms | **远程调用，不计入基线预算**，单列场景见下 |

**三套 SLO（按是否启用精排、是否降级区分）**

| 场景 | p95 SLO | 说明 |
|---|---|---|
| **基线**（未启用精排、未降级） | **≤ 200ms** | 上表预算 |
| **启用精排** | **≤ 600ms** | 增加一次远程 rerank 调用（p95 150–400ms，见 §6.2） |
| **降级**（embedding 或精排失败） | **≤ 1s** | `degraded=true`；embedding 超时上限 800ms |

- `≤ 200ms` **只统计"未降级且未启用精排"的请求**
- **降级率**与**精排启用率**都是要监控的指标（前者衡量 embedding 可用性，后者用于成本核算）

---

## 7. 执行内核

### 7.1 阶段时序

```
调用方 ──execute(tool, args, channel?, idempotency_key?, deadline)──→ 前端
                                                                     │
前端：翻译协议 → ToolInvocation ─────────────────────────────────────┘
                                                                     ↓
执行内核：
  1. 解析工具与版本（code/channel → ToolVersion；不可调用 → TH_TOOL_NOT_FOUND）
  2. 授权判定（无权限 → TH_TOOL_NOT_FOUND，与"不存在"不可区分）
  3. QPS 限流 + 时间窗 / IP 约束   ← 保护平台自身与授权约束，幂等命中也要校验
  4. 幂等查询（按请求指纹）
       · 命中已完成结果且指纹一致 → 直接返回（不碰确认令牌、不计配额与并发、不判熔断）
       · 键已被不同参数占用       → TH_IDEMPOTENCY_KEY_REUSED
  5. 输入 schema 校验
  6. 确认判定（高风险或写操作）   ← **M0 仅判定并拒绝**；令牌发放与消费属 M1（§16.2）
  7. 日配额 + 并发占用 + 熔断判定   ← 只在"确定要真正打上游"之后才扣 / 才拒
  8. 幂等认领（Redis SET NX + 绑定请求指纹；并发后到者得 TH_IDEMPOTENCY_IN_PROGRESS）
  9. 凭据注入（从 Credential 解密 → 注入 header/query/mTLS）
 10. 出站执行（Provider 适配器，SSRF 防护 + 整体 deadline）
 11. 输出 schema 校验
 12. 记录 Invocation + 写审计
 13. 返回统一结果
```

> **这些机制为什么分布在不同位置**——按"这项资源是否真的被消耗"来分：
>
> | 机制 | 位置 | 幂等命中时 | 理由 |
> |---|---|---|---|
> | **QPS 限流** | 第 3 步（幂等查询之前） | ✅ **计** | 它保护**平台自身**不被高频打；缓存命中也是一次请求 |
> | **时间窗 / IP 约束** | 第 3 步 | ✅ **校验** | 属**授权约束**，缓存命中同样要过 |
> | **熔断** | 第 7 步（与配额同组） | ❌ **不判定** | 它保护的是**上游**；缓存命中根本没打上游 |
> | **日配额** | 第 7 步 | ❌ **不计** | 对应**上游成本**；缓存命中不产生上游调用 |
> | **并发占用** | 第 7 步 | ❌ **不计** | 缓存命中极快，不占用上游资源 |
>
> ⚠️ **熔断必须在幂等查询之后**：熔断与日配额/并发同类（都在回答"是否真的会打上游"）。
> 若把它放在第 3 步，Provider 熔断打开时，一个重试"已成功请求"的调用方会收到
> `TH_CIRCUIT_OPEN`（"目标服务暂时不可用"）——但**结果早就算出来了**，
> 这个错误纯属误导，会让 Agent 做无意义的退避。

> **第 7 步扣减的资源必须能归还**（否则"请求从未执行却消耗了配额"）
>
> 第 7 步之后仍可能失败，归还规则如下：
>
> | 失败点 | 日配额 | 并发槽 |
> |---|---|---|
> | 第 8 步 幂等认领失败（并发后到者） | **归还** | **归还** |
> | 第 9 步 凭据解密失败 | **归还** | **归还** |
> | 第 10 步 **出站前**校验失败（域名白名单 / SSRF 地址校验） | **归还** | **归还** |
> | 第 10 步 **实际出站**失败 / 超时 | 不归还（上游成本已发生） | **`finally` 无条件释放** |
> | 第 11 步 输出 schema 校验失败 | 不归还（上游成本已发生） | **`finally` 无条件释放** |
>
> **一句话原则：只有"真的打到了上游"才不归还日配额。**
> 出站前的域名白名单与 SSRF 地址校验属于**平台侧拦截**，根本没产生上游调用，因此必须归还。
> `mcp` 类型同理——那里的"上游"指上游 MCP Server。
>
> 顺序本身不改：若把"幂等认领"提到第 7 步之前，会把幂等键卡在 `processing` 状态直到 TTL，
> 反而制造更多"重复请求处理中"的误判。

> **为什么"幂等查询"必须排在"确认令牌校验"之前**
>
> 调用方带确认令牌 `T` + 幂等键 `K` 首次执行成功（`T` 已被原子消费），随后响应丢失。
> 调用方用同样的 `T` + `K` 重试：
>
> - **原顺序**（先校验令牌）：发现 `T` 已消费 → 直接拒绝 → **永远到不了幂等缓存**，幂等形同虚设
> - **新顺序**：先查幂等缓存 → 命中 → 直接返回首次结果，**根本不碰 `T`**
>
> **"查"与"认领"分离**，三种机制各司其职：
>
> | 机制 | 防什么 |
> |---|---|
> | 幂等查询（第 4 步） | 让重试能拿回原结果 |
> | 确认令牌原子消费（第 6 步） | 防令牌重放 |
> | 幂等认领（第 7 步） | 防并发重复执行 |

> **幂等键必须绑定请求指纹**：`K` 与 `(工具, 参数哈希)` 绑定。
> 同一 `K` 配**不同**参数到达时，返回 `TH_IDEMPOTENCY_KEY_REUSED`（`retryable: false`），
> **而不是返回旧结果**——否则调用方会拿到与本次请求不符的结果，比报错更危险。
>
> **保留期**：`idempotency_ttl` 默认 **24h**（§7.2）。也就是说**调用方最迟 24 小时内重试仍能拿回原结果**，
> 超过则视为新请求重新执行。

### 7.2 横切关注点（只实现一次）

| 关注点 | 做法 |
|---|---|
| 配额 | **Redis + Lua 原子计数**（令牌桶/滑动窗口），第一天就是分布式的 |
| 并发 | Redis 信号量（不是进程内） |
| 幂等 | **两段式**：先查缓存（重试拿回原结果）→ 再 `SET NX` 认领（防并发）；键与请求指纹绑定，详见 §7.1 |
| 幂等保留期 | `idempotency_ttl` 默认 **24h**。**到期后（而非"跨自然日"）** key 与缓存结果一并清除，**此时**重试才会重新执行并消耗当日配额。24h 窗口内的跨天重试（如 23:00 成功、次日 01:00 重试）**仍命中缓存**。它与日配额窗口互不相干：配额按自然日计，幂等按 24h 滑窗计 |
| 确认 | **M1**：一次性令牌，条件 UPDATE 原子消费。**M0 只做判定**——命中高风险/写操作即返回 `TH_CONFIRMATION_REQUIRED`（§16.2） |
| 超时 | 一个**整体 deadline** 从入口贯穿到出站，所有阶段共享 |
| 重试 | 仅幂等方法 + 抖动退避 + 受 deadline 约束 |
| 熔断 | 按 Provider 维度 |
| 审计 | 结构化事件；**不存明文参数与结果**，只存摘要与哈希 |

#### 幂等结果缓存的存储规则（此前未定义，与 D13 的关系现予裁决）

§7.4 硬规则 1 要求"幂等命中已完成的结果 → 返回 200 与原结果"，但 §11.1 / D13 说"执行结果不存明文"。
**要返回原结果，就必须在某个地方存着它**——这两条必须显式调和：

| 维度 | 规则 |
|---|---|
| **介质** | Redis（与幂等 key 同一存储） |
| **保留期** | `idempotency_ttl`，默认 **24h**，与 key 同生命周期，到期一并清除 |
| **是否脱敏** | **不脱敏**。理由：**调用方有权拿回自己那次调用的完整结果**；脱敏的目的是保护"长期留存与日志"，不是对调用方隐瞒结果 |
| **D13 的适用范围** | **D13 只约束审计表、日志与检索事件**，**不约束幂等结果缓存**——后者是**运行期临时状态**，与 Redis 里的配额计数同类，不属于"留存" |
| **大小上限** | `idempotency_cache_max_bytes`，默认 **256KB**。超过上限时**只缓存状态、不缓存结果体**：重试返回 `200` + `result: null` + `idempotency_replayed: true` + `trace_id`，调用方据此知道"已执行过但结果未保留" |
| **持久化** | M0 建议该缓存**不落盘**（Redis 不为该 DB 开启 AOF / RDB） |

> ⚠️ **容量是必须处理的问题**：出站响应上限在 MiB 量级，若不做上限，24h 内的高频调用会在 Redis 里堆积大量结果体。
> **`idempotency_cache_max_bytes` 是必须配置的参数，不是可选项。**

> ⚠️ **平台不承诺"跨重启幂等"**：Redis 重启后 24h 窗口丢失，重试会重新执行。
> 这是"不把业务结果落盘"与"强幂等"之间的取舍。**对真正不容重复的写操作，
> 应由上游系统自己做幂等**（平台把调用方的幂等键透传给上游，或在上游侧去重）；
> 平台只保证**在缓存存活期内**不重复执行。

#### 基础设施故障时的 fail-open / fail-closed（此前未定义）

配额、并发、幂等、确认令牌都押在 Redis 上，因此**必须逐项定义"Redis 不可用时怎么办"**。
**两类机制的处理完全相反，不能一刀切**：

| 机制 | 类别 | Redis 不可用时 | 理由 |
|---|---|---|---|
| **幂等** | **正确性依赖** | **fail-closed** → `TH_DEPENDENCY_UNAVAILABLE` (503) | fail-open 会导致**重复执行写操作**，后果最严重 |
| **确认令牌**（M1） | **正确性依赖** | **fail-closed** → `TH_DEPENDENCY_UNAVAILABLE` (503) | fail-open 等于一次性令牌可重放 |
| **QPS 限流** | **防滥用**（成本 / 容量控制） | **fail-open + 立即告警** | 它是"防滥用"而非"安全边界"；Redis 抖动通常短暂，因它全平台停服代价更大 |
| **日配额** | **防滥用** | **fail-open + 立即告警** | 同上；配额超支可事后追责，全平台停服不可接受 |
| **并发信号量** | **防滥用** | **fail-open + 立即告警** | 同上 |
| **可见集合缓存**（§9.2） | **性能优化** | **绕过缓存直接查库** | 缓存不是控制点——**降级为直查是正确的第三选择**，既不是 open 也不是 closed |

> **一句话原则：关乎"正确性"的 fail-closed；关乎"防滥用"的 fail-open 并告警；纯缓存的直接绕过。**
>
> **PostgreSQL 不可用时一律 fail-closed**（`TH_DEPENDENCY_UNAVAILABLE`）——没有数据库就没有授权与审计，不能放行。
>
> 上一版已有同类原则（安全类校验一律 fail-closed 并返回 503），本节是它的完整化与分类化。

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

### 7.4 错误模型（唯一权威表）

调用方要能自愈，就必须能区分：**参数错（改参数重试）/ 无权（换工具）/ 限流（退避重试）/
上游故障（稍后重试）/ 需要确认（走确认流程）**。

因此错误语义由**内核统一产出**，两个前端只做协议翻译；**不得各自实现一套**（否则 C1 复发）。

#### 统一错误体

```jsonc
{
  "code": "TH_RATE_LIMITED",   // 稳定标识，调用方据此分支
  "message": "请求过于频繁",     // 人类可读，可展示给用户
  "trace_id": "...",            // 排查用，务必记录
  "retryable": true,            // 用同一请求重试是否可能成功
  "retry_after_ms": 850         // 可选：建议的退避时间
}
```

**`retryable` 语义**：`true` = 在幂等安全的前提下，用**同样的请求**重试可能成功；
`false` = 重试无用，必须改请求或改流程。

#### 错误码枚举

| code | HTTP | retryable | 触发条件 | 面向调用方的 message |
|---|---|---|---|---|
| `TH_AUTH_INVALID` | 401 | ❌ | 凭证缺失/无效/过期/吊销 | 认证失败 |
| `TH_AUTH_FORBIDDEN` | 403 | ❌ | 凭证有效，但**在当前来源 IP / 时间窗下不被允许**（§9.1 的 `constraints`），或无权访问管理接口 | 不允许从当前来源访问 |
| `TH_PARAMETER_INVALID` | 400 | ❌ | 参数不符合 `input_schema` | 字段级具体错误 |
| `TH_TOOL_NOT_FOUND` | 404 | ❌ | **任何"不可调用"状态**：工具不存在 / 无权 / 已停用(`disabled`) / 无已发布版本 / 指定的版本或通道不可用 —— **全部返回完全一致**（§9.3） | 工具不可用 |
| `TH_CONFIRMATION_REQUIRED` | 409 | ❌ | 高风险/写操作工具未带确认令牌（**M0 恒返回此码**，因为 M0 无令牌机制） | 该工具需要确认 |
| `TH_CONFIRMATION_INVALID` | 400 | ❌ | 令牌无效/过期/已消费/与目标不匹配（**M1** 才有令牌，故 M0 不会出现此码） | 确认令牌无效 |
| `TH_IDEMPOTENCY_IN_PROGRESS` | 409 | ✅ | 同幂等键的请求**仍在处理中** | 重复请求处理中，请稍后重试 |
| `TH_IDEMPOTENCY_KEY_REUSED` | 409 | ❌ | 同一幂等键配了**不同参数**（请求指纹不符） | 幂等键已用于其他请求，请更换 key |
| `TH_RATE_LIMITED` | 429 | ✅ | 超 QPS 限额 | 请求过于频繁 |
| `TH_CONCURRENCY_LIMITED` | 429 | ✅ | 超并发限额 | 并发超限 |
| `TH_QUOTA_EXCEEDED` | 429 | ❌ | 超日配额（当日重试无意义） | 已达调用配额 |
| `TH_CIRCUIT_OPEN` | 503 | ✅ | Provider 熔断打开 | 目标服务暂时不可用 |
| `TH_DEADLINE_EXCEEDED` | 504 | ✅ | 请求整体 deadline 用尽 | 请求处理超时 |
| `TH_UPSTREAM_TIMEOUT` | 504 | ✅ | 出站超时 | 目标服务响应超时 |
| `TH_UPSTREAM_ERROR` | 502 | ✅ | 上游 5xx / 连接失败 / 响应不合 schema | 目标服务调用失败 |
| `TH_UPSTREAM_REJECTED` | 502 | ❌ | 上游 4xx（含平台凭据失效）——重试无用 | 目标服务拒绝了请求 |
| `TH_CHANNEL_REFERENCES_VERSION` | 409 | ❌ | 试图废弃一个被 Channel 指向的版本（§4.3） | 该版本仍被引用 |
| `TH_RETRIEVAL_UNAVAILABLE` | 503 | ✅ | 检索不可用（关键词与向量**同时**失败，见 §6.6） | 检索服务暂时不可用 |
| `TH_DEPENDENCY_UNAVAILABLE` | 503 | ✅ | **关键依赖不可用**：Redis（幂等 / 确认令牌）或 PostgreSQL 故障，按 §7.2 的矩阵执行 fail-closed | 服务依赖不可用，请求被拒绝 |
| `TH_INTERNAL_ERROR` | 500 | ✅ | 未预期异常 | 内部错误 |

> **为什么把上游错误拆成两个码**：`UPSTREAM_ERROR`（5xx 抖动）值得重试，
> `UPSTREAM_REJECTED`（4xx / 凭据失效）重试无用。合并成一个码会让调用方要么盲目重试、要么放弃可恢复的故障。
> **平台内部知道这个区别，就必须把它传给调用方。**

> **为什么把幂等冲突拆成两个码**：两者可重试性完全相反。
> "仍在处理中"稍后重试会成功；"键已被别的参数占用"**重试永远不会成功**，必须换 key。
> 若合并并标 `retryable: true`，一个守规范的 Agent 会**永久重试一个不可能成功的请求**。

#### 三条硬规则

1. **幂等命中已完成的结果 → 返回 200 与原结果**，不是 409。409 仅用于"仍在处理中"。
2. **内部原因不得外泄**：SSRF 拦截、DNS 校验失败、Provider 配置错误等一律映射为 `TH_UPSTREAM_ERROR`，
   详细原因只进日志——**不返回 `SSRF_BLOCKED` 之类的内部码**，否则等于给攻击者做探测反馈。
3. **`trace_id` 必须在所有错误响应中返回**（§11 的排查完全依赖它）。

#### REST ↔ MCP 映射

MCP 的 `tools/call` **不返回 HTTP 状态码**，它用 `isError` + `content` + `structuredContent` 表达工具级错误：

| 场景 | REST | MCP |
|---|---|---|
| 成功 | 2xx + 结果体 | `isError: false` + `content` + `structuredContent` |
| 业务错误（上表全部） | 对应 HTTP 状态码 + 统一错误体 | `isError: true`；`content[0].text` 放 `message`；**错误码等结构化字段一律放 `_meta`**：`_meta: {"code", "retryable", "trace_id", "retry_after_ms"}` |
| 认证失败 | 401 | **传输层 HTTP 401**（MCP 规范要求认证在传输层，不进 `tools/call`） |

> ⚠️ **关键**：MCP 侧调用方**无法依赖 HTTP 状态码判断可重试性**。
> 因此 `code` / `retryable` **必须放进 `_meta`**，不能只把错误信息拼成一段文本——那样调用方只能做字符串匹配，等于没有错误模型。
>
> **为什么用 `_meta` 而不是 `structuredContent`**：MCP 语义里 `structuredContent` 是"**成功结果且符合该工具 `outputSchema`**"的载体。
> 在 `isError: true` 时往里塞错误码，会与 `outputSchema` 的契约冲突（错误结构本来就不满足成功 schema）。
> `_meta` 才是协议留给扩展元数据的正式位置。

---

## 8. 协议前端与接口面

### 8.1 MCP 前端：搜索式暴露（1w 规模下唯一可行）

MCP 客户端会在会话开始拉全量 `tools/list`，**1w 个工具会直接压垮客户端与模型上下文**。因此：

| 要求 | 做法 |
|---|---|
| 不暴露全量列表 | `tools/list` 返回**该 Principal 的可见工具集合**（**复用 §9.1 的 Grant 判定，不引入新实体**）；超过 `N`（建议 50）则截断，并在响应里引导客户端改用 `search_tools` |
| 提供搜索元工具 | 注册一个 `search_tools(query, scope?, k?)` 工具 |
| 按需取详情 | 提供 `get_tool(code)` 返回完整 schema |
| 执行 | `call_tool(code, arguments)` |

> 注意：**不要把"帮我选并执行"做成一个 MCP 元工具**，否则职责边界塌陷（见 §15.3）。

> **认证方式（M1 前必须定下。默认方案）**：MCP 前端沿用**与 REST 相同的 Principal + API Key 体系**
> ——客户端以 `Authorization: Bearer <api-key>` 携带密钥，认证在**传输层**完成（§7.4 的映射表）。
> 这样**不需要引入 OAuth 授权服务器**，符合"不引入外部依赖"的决策。
> 将来若要面向第三方开放，再单独评估 OAuth。

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

> **约束（`constraints`）的求值时机**（此前只定义了字段、没定义在哪一层生效）：
>
> | 字段 | 求值时机 | 失败时 |
> |---|---|---|
> | `ip_cidrs` / `time_window` | **每次请求**（流水线第 3 步），**幂等命中时同样要校验** | `TH_AUTH_FORBIDDEN` (403) —— 身份已认证且对工具有授权，只是**当前来源 / 时间不允许** |
> | `require_confirmation` | 第 6 步的确认判定（§7.1） | `TH_CONFIRMATION_REQUIRED` (409) |
>
> ⚠️ **约束不参与可见集合缓存**：IP 与时间随请求变化，把它们塞进缓存 key 会让缓存完全失去意义
> （§9.2 的 key 只含 `principal_id` + `visible_ver`）。约束在**检索过滤与授权判定时叠加**即可。

- 层级继承：`domain` grant 自动覆盖其下所有 `system` 与 `tool`
- 多 grant 对**可见性**取并集（能看见的范围 = 各 grant 范围的并集）
- 默认拒绝（无 grant 即不可见、不可调）

#### 配额语义（此前未定义，现明确）

一次调用会命中**所有**匹配的 grant（domain / system / tag / tool）。规则：

> **每个命中的 grant 各自独立计数，任一超限即拒绝。
> 配额是"每个授权范围各自的限额"，不是主体总额。**

- Redis key：`quota:{principal_id}:{scope_type}:{scope_value}:{window}`
- `qps` / `daily` / `concurrency` 三者语义一致，都按 grant 独立计数
- grant 未配置 quota ⇒ 该项**不限额**
- 因此**增加一个 grant 只会增加约束，不会增加额度**（避免"多授一个范围就多一份 QPS"的意外放大）

推论：若确实需要"主体级总额度"，那是另一个概念，应加在 `Principal` 上（M2 再评估），**不要与 grant 配额混用同一套 key**。

### 9.2 与检索的耦合（含 pgvector 的性能陷阱）

**授权必须先于排序**（§6.2 步骤 1），不能"先取 top-100 再丢掉无权限的"。

落到 pgvector 有个具体陷阱：**带 `WHERE` 过滤的 HNSW 索引查询，PostgreSQL 可能放弃索引改走顺序扫描，
或者为凑够 `LIMIT` 反复迭代导致召回率下降**（与过滤率、`hnsw.ef_search` 强相关）。

**M0 的写法（必须照做）**——不在向量检索里带权限过滤，而是分两步：

```
1. 先按权限 + scope 查出可见工具的 tool_id 集合（普通 B-tree 查询，很快）
2. 再做向量检索：WHERE tool_id = ANY($1)
   · 窄权限调用方：集合小，过滤后索引照常可用
   · 宽权限调用方：集合接近全量，此时"过滤"本身不构成瓶颈
```

**M2 的优化（必做，不是"建议"）**——按 `domain` 对向量表**分区**，并确保查询条件包含分区键以触发 partition pruning：

```sql
-- 分区键 domain 必须出现在 WHERE 中，否则不会剪枝
WHERE domain = $1 AND tool_id = ANY($2)
```

> 1w 量级下全表扫描也能接受（2560 维 halfvec × 1w ≈ 50MB），但 M2 必须完成分区，
> 并把 `hnsw.ef_search` 的调参纳入检索评测的对比项。

**可见集合必须缓存**：`domain` grant 展开后可能有几千个 `tool_id`，每次检索都重算并不可取。
按 Principal 在 Redis 做短 TTL 缓存：

```
key:   visible:{principal_id}:{visible_ver}
value: tool_id 集合（压缩存储）
ttl:   60s
```

> **key 里为什么不能带 `scope`**：可见集合只依赖 **Principal + Grant**，与请求的 `scope` 无关
> ——`scope` 是在可见集合**之上**再收窄（§6.2 步骤 2）。把 `scope` 放进 key 会让 key 数量
> 随请求组合膨胀、命中率骤降。**scope 在查询时叠加即可**（`WHERE tool_id = ANY(...) AND domain = $1`）。

**失效方式（两条并用）**——只靠 TTL 会导致"授权已收回但调用方仍可见"：

1. **主动失效**：`Grant` / `Tool` / `Provider` 状态变更时执行 `INCR visible_ver:{principal_id}`；
   读取时把版本号拼进 key，版本一变旧 key 自然失效
2. **TTL 兜底**：即使漏了主动失效，最迟 60 秒后生效

> **授权变更的生效延迟上限 = TTL（60s）**，这个数字必须在授权管理界面明示，避免"已撤销却还能调"的误解。

### 9.3 不可区分原则

"工具不存在" 与 "工具无权访问" **必须返回完全相同的响应**——都是 `TH_TOOL_NOT_FOUND` + 相同的错误体（§7.4）。
否则可以靠错误码探测平台里有哪些工具。

---

## 10. 凭据与出站安全

### 10.1 凭据

```
Credential: { id, name, kind, ciphertext, kek_id, rotated_at }
kind: static_header | api_key | basic | oauth2_client | mtls
```

- **信封加密**：数据密钥加密内容，KEK 来自环境变量（**不接 KMS**）
- API **只写不读**：查询接口返回掩码（`sk-****abcd`），永不回显明文
- 支持**轮换**（多 KEK 并存窗口）与**访问审计**（谁在什么时候用了哪个凭据）
- `external_ref` 字段为将来可能的外部凭据保管预留，**当前不接任何 Vault**

#### 为什么需要一个"库外的密钥"（KEK）

**场景**：平台代持上游系统的 Token（D2）。若 Token 明文入库，那么任何拿到**数据库备份、只读账号或慢查询日志**的人，就能一次性拿走**所有**上游系统的凭据。

所以必须加密；而**密钥不能和密文放在同一个地方**（放一起等于没加密）。这个放在库外的密钥就是 KEK（Key Encryption Key）：

```
上游 Token（明文）
  └─ 用 DEK 加密        → ciphertext 存入 credential 表
       └─ DEK 再用 KEK 加密后一并存储
            └─ KEK 放在库外：环境变量，永不入库
```

`kek_id` 字段记录"这条密文由哪把 KEK 包装"，**它的存在是为了支持轮换**。

**做法**：每条凭据使用独立随机 DEK + AES-256-GCM。KEK 通过**两个环境变量**注入——必须是**多把并存**，否则上面的轮换流程无法进行：

```
TOOLHIVE_KEKS='{"k1":"<32 字节 base64>","k2":"<32 字节 base64>"}'   # 多把 KEK，可增可减
TOOLHIVE_ACTIVE_KEK_ID=k2                                            # 新写入用哪把
```

- **解密时按密文上的 `kek_id` 找对应 KEK**，不依赖 `ACTIVE_KEK_ID`
- 轮换第 2 步只改 `ACTIVE_KEK_ID`；第 3 步重包装全部完成后，才从 `TOOLHIVE_KEKS` 删掉旧 KEK
- **启动自检**：若存在密文引用了 `TOOLHIVE_KEKS` 里没有的 `kek_id`，
  **拒绝启动**（而不是等到某次调用才发现凭证解不开）

**不接 KMS**，因此 KEK 轮换走运维流程：

```
1. 新增一把 KEK（新 kek_id），与旧 KEK 并存
2. 新写入的凭据用新 KEK 包装
3. 后台任务用旧 KEK 解密、新 KEK 重新包装存量凭据
4. 全部迁完后，从环境变量中移除旧 KEK
```

第 3 步是普通的后台任务，不需要外部服务；`kek_id` 字段就是为这个流程存在的。

#### 部署约束（环境变量方案的补偿措施）

环境变量方案比明文入库强得多，但**拿到进程环境或 K8s Secret 的人可以解密全部凭据**。因此必须配套：

1. **KEK 只注入到运行面进程**（执行内核所在的 Pod）。**管理面 CLI 与 admin API 不持有 KEK、不参与凭据解密**
   ——这条正好让"凭据可见性"成为真实的安全边界，成本几乎为零
2. KEK **不进日志、不进崩溃转储、不进配置查询接口**；配置查询只返回 `kek_id`，永不返回密钥值
3. **凭据解密失败必须 fail-closed**：拒绝执行并返回 `TH_UPSTREAM_ERROR`，
   **不得**返回空值、不得降级为匿名调用。
   同时**必须触发平台侧告警**——这是平台配置问题（KEK 缺失、密文损坏），不是调用方的错；
   只让调用方看到一个 502 会把平台故障误判成"上游抖动"
4. KEK 轮换的重包装任务由**运行面进程**执行，管理面不介入

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
| **审计**（治理事实） | `AuditLog`：谁改了什么、谁调用了什么、结果哈希 |
| **凭据使用审计** | 每次解密凭据出站时记一条：`credential_id` + `principal_id` + `tool_id` + `trace_id`（**不记凭据值**）——§10.1 提到的"访问审计"落在这里 |
| **Trace**（技术链路） | **不引入 OpenTelemetry**：`trace_id` 在入口生成，贯穿 `retrieve → authorize → execute → upstream`，写入结构化日志与 `Invocation` 记录；排查时按 `trace_id` 串日志 |
| **指标** | **不引入 Prometheus**：关键计数（QPS、错误率、配额拒绝、熔断次数、**检索降级率**）写入日志；另提供 **CLI 子命令 `toolhive stats --since <时间>`** 从事件表聚合用量报表（**M0 管理面只有 CLI**，与 §16.2 一致；M1 有管理 API 后再考虑暴露为接口） |
| **延迟分位** | 不接 Prometheus 的代价是**无法从原始日志直接算 p95**。补救：日志里写**预聚合的延迟直方图桶**（固定边界，如 10/25/50/100/200/500/1000/2000ms），日志解析即可算分位——成本几乎为零 |
| **日志** | 结构化 JSON，每条带 `trace_id` |
| **健康检查** | liveness / readiness 分离；readiness 检查 PostgreSQL、Redis、检索索引 |

> **明确不引入**：OpenTelemetry、Prometheus。将来若接入统一监控体系，`trace_id` 与结构化日志可直接被采集，**不需要改业务代码**。
>
> **零成本兜底（当前不实现，留作后手）**：若将来确实需要被监控系统主动抓取，可暴露一个**只读的 `/metrics` 文本端点**
> （Prometheus 文本格式）。那只是**字符串格式化**——不引入任何依赖、不启动任何服务。

### 11.1 数据留存与脱敏（逐项裁决）

"审计不存明文" 与 "评测要从真实调用采样"（§14.4）此前是冲突的。逐项裁决如下：

| 数据 | 是否存储 | 说明 |
|---|---|---|
| **检索 query**（`/v1/tools/search` 的输入） | ✅ **存**：默认**截断 512 字符** + **默认脱敏** | 属**检索行为**数据，不是业务数据；也是评测标注的**唯一来源**，不存则评测体系无从建立 |
| **检索事件** | ✅ 单独记录 | `search` **不写 `Invocation`**（那是执行记录）；单独事件含 `query`、`top-k`、`degraded`、`latency` |
| **工具调用参数** | ❌ 明文不存 | 只存 `input_schema` 摘要 + `SHA-256` |
| **执行结果** | ❌ 明文不存 | 只存 `SHA-256` + 字节数 |
| **业务身份上下文**（`context`） | ⚠️ 按字段白名单 | 默认只保留 `tenant_id` / `user_id` 的哈希，其余丢弃 |
| **凭据值** | ❌ **永不记录** | 只记 `credential_id` |

> 上一版把调用参数与结果**明文**写进 `runtime_trace_log`，v0.2 按上表执行。

**默认脱敏规则（可配置开关）**——写入前用正则替换为占位符，避免合规评审卡住：

| 模式 | 替换为 |
|---|---|
| 手机号 `1[3-9]\d{9}` | `<PHONE>` |
| 身份证（18 位，含末位 X） | `<ID_CARD>` |
| 邮箱 | `<EMAIL>` |
| 银行卡（**仅在带"卡号/card/银行卡"等前缀上下文时才匹配**） | `<BANK_CARD>` |

> ⚠️ **裸 16–19 位数字不脱敏**：订单号、流水号、时间戳拼接串都会命中这个模式，
> 误伤后不仅无意义，还会把评测语料打坏（脱敏后的 query 无法用于判断"这条查询该匹配哪个工具"）。
> 宁可少脱敏，也不要过度脱敏——**脱敏规则的副作用是降低评测能力**。

- **截断长度**默认 512 字符（与 §6.1 的 `query` 上限一致），可配置
- **脱敏默认开启**；关闭必须显式配置，不能是默认行为
- 本节只影响**检索 query**；工具**参数**与**结果**仍是"只存哈希"，不受影响

---

## 12. 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言/框架 | Python 3.12 + FastAPI | 团队已有积累；此量级不是性能瓶颈 |
| 主存储 | PostgreSQL | 权威数据 + 审计 |
| 主键 | **雪花算法**（应用层生成 `bigint`） | 全局唯一、趋势递增、不依赖数据库序列；跨实例需配 `datacenter_id`/`worker_id`（§4.1） |
| 向量 | **pgvector**（服务端 0.8.6，已安装） | 一个库搞定；备份/一致性简单；**可水平扩展**（上一版嵌入式 Chroma 是硬伤）。⚠️ 2560 维超出 `vector` 的 2000 维索引上限，列类型用 **`halfvec(2560)`**，见 §6.4 |
| 检索 | **`pg_trgm`（M0，绕开中文分词）+ pgvector + RRF 融合** | 混合检索；M0 不引入分词方案。⚠️ `pg_trgm` 需装 contrib 包（部署前置条件，见 §6.2） |
| 精排（可选，**默认关**） | **DashScope `qwen3.7-text-rerank`**（判别式，非 LLM，境内）。供应商已确定；管线保留精排阶段，**默认关闭**（延迟与成本），由评测决定开启 | 见 §6.2；远程调用 p95 150–400ms，**需并入延迟 SLO** |
| embedding 服务 | **现成的境内服务**（OpenAI 兼容 `/v1/embeddings`，模型 `kinfra-text-embedding-4b`），通过配置注入 base_url 与密钥 | 已确认可用；不自建、不调境外 |
| 缓存/计数 | Redis + Lua | 配额、并发、幂等、确认令牌；**已有现成实例** |
| 迁移 | **Alembic 唯一来源** | 不再有 `init.sql` 与 ORM 双份 DDL |
| 密钥 | **环境变量注入的 KEK**（不接 KMS） | 见 §10.1 |
| 部署 | 容器化、多 worker、**无状态** | 上一版 `--workers 1` + 进程内信号量是硬伤 |
| 前端 | React + Vite | 管理台（M1） |

> **合规约束**：所有模型服务（embedding、离线富化可能用到的 LLM）必须部署在境内，不得调用境外 API。选型时先确认这一点，再比质量与成本。

#### 明确不引入的外部依赖

以下组件**已决定不接入**，实现时不得引入；若将来确需，必须先走设计变更：

| 不引入 | 替代做法 |
|---|---|
| **KMS** | KEK 由环境变量注入；轮换走运维流程（§10.1） |
| **Vault / 外部凭据保管** | 凭据密文入库；`credential.external_ref` 字段仅作预留，不接任何外部服务 |
| **OpenTelemetry** | `trace_id` + 结构化日志串链路（§11） |
| **Prometheus** | 关键计数写日志 + **管理侧 CLI 聚合（M0）/ 接口（M1）**（§11） |

> Redis 与 PostgreSQL(+pgvector) 属于**已有现成实例**，不算新增依赖。

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

> **已确认**：业务方具备独立部署工具服务的能力，因此 ③ 类工具走"业务方自部署 MCP 服务"这条路成立，**平台不需要自建"工具托管运行时"**（省掉沙箱、镜像管理、资源限额一整套）。
>
> 但要降低摩擦，平台必须提供两样东西（M1 交付）：
> 1. **工具服务 SDK**：把"写一个工具函数 + 暴露为 MCP"压缩成几行代码（含凭据注入通道 `ctx.credential(...)`）
> 2. **模板仓库 + CI 示例**：业务方 clone 后填函数体即可，含容器化与注册流程

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
| **契约测试** | OpenAPI 快照（M0）；**MCP schema 快照为 M1**（M0 无 MCP 前端）。防止无意破坏调用方 |
| **E2E** | 导入工具 → 送审 → 通过 → 发布 → 检索 → **通过 REST 调用** → 断言配额与审计（**M0 无 MCP，E2E 只走 REST**） |
| **检索评测** | 标注集上跑 `recall@k` / MRR / nDCG，**CI 门禁** |
| 架构断言 | §14.1 的五条 |

### 14.4 评测集怎么攒（M0）

- 初期：人工构造 200 条 `query → 正确工具` 标注（覆盖各业务域）
- 中期：从**真实检索事件**中采样，人工确认（`query` 的存储规则见 §11.1——这是评测体系能建立的前提）
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

#### M0 范围决策（已确认）

| 项 | M0 决定 | 说明 |
|---|---|---|
| **管理面形态** | **只用 CLI**，不做管理 HTTP API、不做管理前端 | 省掉会话/CSRF/验证码/操作码一整套（C3）；代价是 M0 只能命令行操作 |
| **调用方认证** | **API Key**（每 Principal 一把，可轮换） | 签名的请求认证（RSA/Ed25519）留到 M1，作为可插拔 authenticator（Q2） |
| **MCP 客户端 / MCP 服务端** | **两者都不做**（区分见 §5.1） | 均为 M1，且**彼此独立**（Q3） |
| **确认令牌端点** | **不做**。内核**只保留判定**（命中高风险/写操作即返回 `TH_CONFIRMATION_REQUIRED`），**不实现令牌发放、存储与消费**——那整套属 M1 | M0 工具以读为主，链路 fail-safe（Q4）。注意：由于 G6 已把这类工具标为 `executable=false`（第 2 步即拒），第 6 步在 M0 **正常路径下不可达**，保留它只是纵深防御 |
| **需确认工具的导入** | **照常建档，但标 `executable=false`**；判定条件**与内核第 6 步的确认判定完全对齐**：`method ∈ {POST,PUT,PATCH,DELETE}` **或** `risk == high`（**只读但高风险的工具同样处理**）。导入报告显式说明原因；**不跳过导入** | 否则会出现"搜得到、调得动、必被拒"的坏体验：`risk=high` 的 GET 工具不会被标不可用，但执行时第 6 步要求确认而 M0 无确认端点。**`executable=false` 的工具不进检索结果**（检索 = 可见 ∧ `discoverable` ∧ `executable`） |
| **关键词检索** | **`pg_trgm`**，不做中文分词 | 见 §6.2（Q5）；`pg_trgm` 属 contrib 包，**需在服务器安装** |
| **元数据富化** | **只做规则富化** | LLM 描述补全改为"评测触发的可选项"，见 §5.4 |
| **精排（rerank）** | **供应商已定（DashScope `qwen3.7-text-rerank`）**；管线保留该阶段，但**默认关闭**（延迟与成本），由评测决定开启 | 见 §6.2；远程调用 p95 150–400ms，**不计入基线延迟 SLO**，见 §6.7 |
| **多租户** | **不做**，`tenant_id` 字段预留 | — |
| **KEK** | **环境变量注入，不接 KMS** | 轮换走运维流程，见 §10.1 |
| **可观测性** | **不接 OpenTelemetry、不接 Prometheus** | 用 `trace_id` + 结构化日志；统计走**管理侧 CLI 聚合（M0）/ 接口（M1）**，见 §11 |
| **外部凭据保管** | **不接 Vault**，`external_ref` 仅作字段预留 | 凭据密文入库，见 §10.1 |
| **凭据范围** | **M0 只做最小可用**：`static_header` / `bearer` 两种类型、**单 KEK**、CLI 创建与吊销、出站注入。**不做**轮换界面、KEK 轮换、`oauth2_client` / `mTLS` | 不含凭据则导入的真实工具大多调不通，M0 验收无法成立；但轮换与多类型属 M1（§16.3）。此前 §16.2 与 §16.3 都写了"凭据注入"、两头都说得通，现已划清 |
| **审批权限** | 管理面是 CLI，**能执行 CLI 的人即可审**；M0 的审批**只留痕、不做权限分离**（导入者可自审自批） | M1 引入角色与职责分离（Q7） |
| **按来源免审策略** | **不做**，M0 `review_required` 恒为 true | M1（Q8） |
| **审计保留周期** | **不删除** | M1 定策略（Q9） |
| **工具服务 SDK** | **不做** | M1（Q10） |

#### M0 交付物

| # | 交付物 |
|---|---|
| 1 | 领域模型 + Alembic 首个迁移 |
| 2 | Principal（API Key）+ Grant + 授权判定与可见工具集合 |
| 3 | **OpenAPI 导入器** + `source_ref` 幂等重导 + 命名规范化 + 规则富化 |
| 4 | **简单审批流**：`draft → pending_review → published/rejected` + 审核记录（M0 **不含** `deprecated`/`retired`，见 §4.3） |
| 5 | **embedding 服务适配器**：在线单条（短超时 + 失败降级）+ 离线批量（分批 + 续跑） |
| 6 | **工具检索**：权限过滤 + `pg_trgm` ∥ 向量 + RRF + scope 收窄 + taxonomy 接口 |
| 7 | **执行内核**：http provider + **最小凭据注入**（见下方"凭据范围"）+ 配额/并发 + 幂等 + 审计 |
| 8 | **REST 前端**（MCP 前端为 M1） |
| 9 | **管理 CLI**：导入、送审、审核、发布、授权、**凭据管理**、重建索引、跑评测 |
| 10 | **评测集 v0（100~200 条）+ recall@k CI 门禁** |
| 11 | 架构断言 + CI 流水线（含契约快照与 E2E） |
| 12 | 可观测基础：`trace_id` 贯穿 + 结构化日志（**不接 OTel / Prometheus**） |

**M0 验收脚本**（工具数 ≥ 100 时执行；`L1` 的 E2E 按此实现，**步骤以本节为唯一口径**）：

| # | 动作 | 预期 |
|---|---|---|
| 1 | `toolhive import openapi --provider <code> --file <path>` | 输出新增 / 变更 / 消失三类计数 |
| 2 | `toolhive review list --status pending_review` | 列出刚导入的草稿 |
| 3 | `toolhive review approve --version <id>` | 状态转为 `published` |
| 4 | `toolhive publish --tool <code> --channel stable` | `stable` 通道指向该版本 |
| 5 | `toolhive grant create --principal <id> --scope domain --value <domain>` | 授权生效 |
| 6 | `POST /v1/tools/search {"query": "..."}` | 命中正确工具，且 `degraded=false` |
| 7 | `POST /v1/tools/{code}/execute` | 返回结果 + `trace_id` |
| 8 | 查 `Invocation` 与 `AuditLog` | 记录齐全，**且不含明文参数与结果**（§11.1） |
| 9 | **用同一幂等键重试第 7 步** | **返回与首次完全相同的结果**（§7.1 硬规则 1） |
| 10 | 把该 grant 的 QPS 调到 1 后连续请求 | 第二次返回 `TH_RATE_LIMITED` |

### 16.3 M1：放量到 1k

- **MCP 客户端**：MCP 导入器 + Provider `type=mcp`（会话管理、重连、上游超时）——与 OpenAPI 导入合并到统一规范化层
- **MCP 服务端**：MCP 前端（transport、transport security、Host 校验、`search_tools` / `get_tool` / `call_tool`）

> 上面两项是**独立交付物、无依赖关系**，可并行；技术栈完全不同（客户端要会话管理，服务端要传输安全）。
- **凭据轮换与类型扩展**：多 KEK 轮换、`oauth2_client` / `mTLS` 类型（**M0 已有最小注入**，见 §16.2「凭据范围」）
- 描述补全（LLM 富化）：**仅当评测证明"描述质量是瓶颈"时才引入**，见 §5.4
- 精排（**DashScope rerank 适配器**）：**供应商已定，但默认关闭**；仅当评测显示"recall@5 低但 recall@30 高"（排序问题）时开启，见 §6.2；同时评测集扩到 500 条
- **确认令牌机制**：`POST /v1/confirmations` 端点、令牌发放与原子消费、写操作/高风险工具随之启用（**M0 只有判定，见 §16.2**）
- 管理前端（目录、授权、配额、审计）

### 16.4 M2：放量到 1w

- 去重与相似工具检测
- 索引分区 + 多路召回融合
- 按来源信任策略的自动发布 + 批量操作
- 工具策展：识别长期零调用的工具
- 索引版本化切换（换 embedding 模型）演练

### 16.5 M3：治理增强（按需）

- 细粒度权限（在资源+动作模型上扩展，不枚举端点）
- 多级审批 / 会签（**仅在业务确实需要时**；简单审批流已在 M0 交付，见 §4.3）
- 计量与配额治理看板

### 16.6 `builtin_tools/` 准入规则

1. 只能是元能力：时间、UUID、哈希、编码转换
2. 不得有业务语义（禁止 `crm.*` 这类编码）
3. 数量上限 10 个
4. 不得访问网络或数据库（纯函数，CI 断言）

---

## 17. 决策记录与后续归属

### 17.1 已冻结的决策

| # | 决策 | 结论 | 影响章节 |
|---|---|---|---|
| D1 | 检索 `scope` | 作为**可选一等参数**，同时提供 `taxonomy` 接口供调用方缩小范围 | §6.1 |
| D2 | 凭据存储 | **密文入库**（信封加密）；KEK 由**环境变量**注入；`external_ref` 字段仅作预留，**不接 Vault** | §10.1 |
| D3 | 数据出境 | **不需要出境**；所有模型服务限境内 | §2.1 §6.4 §12 |
| D4 | 审批流 | **需要，但只做简单状态流转**（`draft → pending_review → published/rejected`），不做多级审批与会签 | §4.3 |
| D5 | 索引版本化 | M0 即带 `index_version` | §6.5 |
| D6 | 工具服务部署 | **业务方可自行部署** → ③ 类工具路径成立，平台**不需要**自建"工具托管运行时" | §13.1 |
| D7 | embedding 服务 | 使用现成的境内服务（OpenAI 兼容 `/v1/embeddings`） | §6.4 §12 |
| D8 | M0 范围与实现细节 | **以 §16.2 的「M0 范围决策」表为唯一口径**（此处不再重复枚举，避免两处不同步） | §16.2 |
| D9 | **明确排除的外部依赖** | **KMS、Vault、OpenTelemetry、Prometheus 一律不接**；Redis 与 PostgreSQL(+pgvector) 使用**已有现成实例**。**将来若接入统一监控体系，`trace_id` 与结构化日志可直接被采集，不需要改业务代码**（故 R11 的"未定"不影响现在开工） | §12 |
| D10 | **错误模型** | 统一错误体 `{code, message, trace_id, retryable, retry_after_ms}` + **20 个 `TH_*` 错误码**（见 §7.4 表）；**由内核统一产出，两个前端只做协议翻译** | §7.4 |
| D11 | **配额语义** | 每个命中的 grant **各自独立计数，任一超限即拒绝**；增加 grant 只增加约束、不增加额度 | §9.1 |
| D12 | **Channel 悬空** | **拒绝**废弃被 Channel 指向的版本（**不做自动回退**）；无 stable 通道的工具视为不可调用 | §4.3 |
| D13 | **数据留存**（**只约束审计表、日志与检索事件**） | 检索 `query` **存**（可配置脱敏）；工具参数/结果**只存哈希**；凭据值**永不记录**；`search` 不写 `Invocation`。**不约束幂等结果缓存**（属运行期临时状态，规则见 §7.2） | §11.1 §7.2 |
| D14 | **需确认的工具在 M0** | 判定条件**与内核确认判定对齐**（写方法 **或** `risk == high`），照常导入但标 `executable=false`，导入报告显式告知（**不跳过导入**） | §16.2 §4.1 |
| D15 | **rerank 供应商** | **DashScope `qwen3.7-text-rerank`**（境内、判别式）；管线保留精排阶段，**默认关闭**，由评测决定开启；远程调用 p95 150–400ms 需并入延迟 SLO | §6.2 §6.7 §12 |

**这些决策已足够冻结 M0 的表结构与接口，可以直接开工。**

### 17.2 后续归属（不需要再单独确认）

以下事项都已有明确归属，此处只作索引，避免它们重新变成"悬而未决"：

| # | 事项 | 归属 | 说明 |
|---|---|---|---|
| R1 | embedding 的向量维度 / 限流 / SLA / 单次最大批量 | **M0 接入时实测** | 维度首次调用探测后写入索引元数据；限流与 SLA 边用边摸，**不是决策项** |
| R2 | 工具服务 SDK 与模板仓库 | M1 | M0 不设计 |
| R3 | 按来源信任策略（可信来源免审） | M1 | M0 `review_required` 恒为 true |
| R4 | 向量/关键词融合权重是否按域调参 | M2 | 评测驱动 |
| R5 | 描述补全（引入 LLM 富化） | **评测触发，可能永不引入** | 见 §5.4 |
| R6 | 审计与 Invocation 的保留周期 | M0 不删除；M1 由合规确定 | |
| R7 | KEK 轮换的**实现** | M1（**流程已在 §10.1 设计定**） | 不接 KMS，靠多 KEK 并存 + 后台重包装 |
| R8 | 中文分词 / BM25 升级 | 评测触发，可能永不引入 | M0 用 `pg_trgm` 绕开，见 §6.2 |
| R8b | 服务器安装 `postgresql-contrib`（提供 `pg_trgm`） | **部署前置条件，开工前完成** | 不影响设计；实测当前服务器可用扩展只有 `plpgsql` 与 `vector` |
| R9 | **reranker 接入与启用** | **供应商已定（DashScope）**，M1 交付适配器 | 管线保留精排阶段但**默认关闭**（走 no-op，等价于 RRF 顺序）；接口 + 配置项 + no-op 实现先就位，**代码留 TODO**；是否开启由评测 A/B 决定，见 §6.2 |
| R9b | **rerank 服务的限流 / SLA / 计费** | M1 接入时实测 | 与 embedding 同类，属"事实探测"而非决策项 |
| R10 | 排序用的行为信号（调用成功率/频次）是否纳入 | M2 | 依赖足够的调用数据积累 |
| R11 | 统一监控接入（若将来有公司级监控体系） | 未定（**不影响开工**） | 见 D9：`trace_id` + 结构化日志可直接被采集，**不需要改业务代码** |

---

## 18. 附录 A：精排（reranker）原理与代价

> 本节是 §6.2 精排部分的展开，**属于背景知识，不影响开工决策**。主线只保留了"是否引入"的判据与接入契约。

### A.1 它不是 LLM

精排用的是 **cross-encoder**（判别式编码器模型，通常 100M~600M 参数），**只输出一个相关性分数，不生成任何文本**。

| | Embedding（粗排用） | **Reranker（精排用）** | LLM |
|---|---|---|---|
| 类型 | 判别式 | **判别式** | 生成式 |
| 输出 | 向量 | **相关性分数** | 文本 / JSON |
| 确定性 | 高 | **高** | 低 |
| 幻觉 | 无 | **无** | 有 |
| 可被 prompt 注入 | 否 | **否** | 是 |

### A.2 机制：为什么它比 embedding 准

```
输入：query 文本 + 候选工具文本（"域.系统.工具名.描述" 拼接）
对每个候选算一次：score = cross_encoder(query, doc_text)
按 score 降序 → 取 top-k
```

**与 embedding 的本质区别**：embedding 把 query 与文档**分别**编码再算余弦（两者从不"见面"）；
cross-encoder 把两者**拼在一起**送进模型，能建模词级交互。

例：query = `查一下这个客户的投诉记录`

| 候选 | embedding | cross-encoder |
|---|---|---|
| `aftersale.ticket.list` — 按客户查询售后工单列表 | 0.78 | **0.92** |
| `crm.customer.query` — 根据客户 ID 查询客户档案 | 0.74 | **0.35** |

**这就是精排的全部价值**：embedding 分不开这两者（都含"客户/查询"），
cross-encoder 能注意到"投诉 ↔ 工单"的对应与"档案 ↔ 投诉"的不对应。

### A.3 为什么它不需要业务知识

它只判断**文本相关性**。业务映射（"投诉"属于哪个域）由 `scope` / `taxonomy` 承担，发生在精排**之前**；
业务推理属于上层系统。**让 reranker 去做业务推理，它就变成生成式决策，§3.1 的约束就被破坏了。**

### A.4 代价：O(N)

cross-encoder 必须对每个候选各算一次前向，候选数量直接决定延迟：

| 候选数 | GPU | CPU（小模型 + 短文本） | CPU（base 模型） |
|---|---|---|---|
| 100 | ~50ms | ~300ms | ~1–2s |
| 50 | ~25ms | ~150ms | ~0.5–1s |
| 30 | ~15ms | ~90ms | ~300ms |

> 若将来改为**本地部署**而非调用远程服务，这张表就是选型依据。
> 缓解手段：缩小候选到 30~50、换 MiniLM 级小模型、把 `max_length` 从 512 降到 128（工具描述只有一句话）、
> 或独立部署走 GPU。

### A.5 不用模型的排序信号

粗排之后、精排之前，还可以叠加这些**确定性、零成本**的信号（**注：其中"调用成功率/频次"依赖数据积累，属 R10/M2**）：

| 信号 | 说明 |
|---|---|
| RRF 融合分 | 粗排本身给出的排序 |
| 字段加权 | 编码精确命中 > 名称命中 > 描述命中 |
| 覆盖率 | query 中多少词被命中 |
| 调用成功率 / 频次 | 历史行为信号（需数据积累，R10） |
| 新鲜度 | 最近更新/发布优先 |

这些在"投诉 vs 档案"这类**语义细微差别**上无能为力——那正是 cross-encoder 的价值所在。
