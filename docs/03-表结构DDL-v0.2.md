# ToolHive 表结构 DDL v0.2

> 上游依据：`01-ToolHive平台设计-v0.2.md` §4.1 实体总览
> **本文档是 M0 的建表交付物**，可直接在 PostgreSQL 上执行。
> ⚠️ **落库后以 `alembic/versions/0001_initial.py` 为唯一来源**：本文件用于评审与首次建库，
> 之后 schema 变更只走迁移，由 `C2` 的契约测试保证 ORM metadata 与迁移结果一致。

---

## 1. 全局约定

### 1.1 主键：雪花算法

```sql
id bigint PRIMARY KEY      -- 雪花 ID，64 位有符号（实际只用 63 位正数）
```

- 由应用层的雪花生成器产出，**数据库不做自增、不用序列**
- 需要配置 `TOOLHIVE_SNOWFLAKE_DATACENTER_ID` 与 `TOOLHIVE_SNOWFLAKE_WORKER_ID`（多实例不得重复）
- 所有外键一律 `bigint`，与主键类型一致

### 1.2 审计字段：每张表必备

```sql
create_by_id   bigint,
create_by_name varchar(128),
create_time    timestamptz  NOT NULL DEFAULT now(),
update_by_id   bigint,
update_by_name varchar(128),
update_time    timestamptz
```

四条规则：

| 规则 | 说明 |
|---|---|
| **六列在每张表上都存在** | 包括日志/事件表——这样 ORM 可以对**所有模型用同一个 `AuditMixin`**，不需要两套 |
| **`*_by_name` 是写入时刻的名称快照** | 不随账号改名而变——审计记录必须保持当时的可读性 |
| **审计字段不加外键** | 操作人可能已离职/被删、也可能是服务型 Principal，加 FK 会导致删号失败或历史记录被牵连 |
| **追加型表（日志/事件）只填 `create_*`** | `update_*` 恒为空，语义即"不可修改"；列仍然存在，只是不被写入 |
| **`create_time` 有默认值，`update_time` 无** | 前者可由数据库兜底；后者只在真正更新时由应用显式 `now()` 设置 |

> 事件/日志表（`invocation` / `search_event` / `audit_log`）中，`create_by_id` / `create_by_name`
> **即"触发该记录的操作人"**——因此这几张表不再单设 `actor_id` / `reviewer_id` 之类的重复字段。

### 1.3 其余约定

- 状态类字段用 `varchar` 存储**代码层枚举的字符串值**，数据库不加 `CHECK`（新增状态只需改代码）
- 软删除一律不用；用 `status` 表达（`archived` 为终态）
- 乐观锁：仅**可变实体**带 `row_version integer NOT NULL DEFAULT 0`
- 时间一律 `timestamptz`

---

## 2. 扩展

```sql
-- 向量检索（服务端已确认可用：pgvector 0.8.6，含 halfvec 类型）
CREATE EXTENSION IF NOT EXISTS vector;

-- 关键词检索（按字符三元组，绕开中文分词）
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

> **部署前置条件**：`pg_trgm` 属于 PostgreSQL contrib 包。
> **当前目标服务器尚未安装**（实测可用扩展只有 `plpgsql` 与 `vector`）——
> 需要在服务器上装 `postgresql-contrib`（OpenCloudOS / RHEL 系：`yum install postgresql15-contrib`）
> 后执行上面的建扩展语句。这属于**环境准备**，不是设计取舍。

---

## 3. 完整 DDL

```sql
-- ═══════════════════════════════════════════════════════════════
-- 身份
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE principal (
    id             bigint       PRIMARY KEY,
    type           varchar(16)  NOT NULL,                    -- user | service | agent
    tenant_id      bigint,                                   -- 预留：M0/M1 不参与任何过滤
    name           varchar(128) NOT NULL,
    display_name   varchar(128),
    status         varchar(16)  NOT NULL DEFAULT 'enabled',   -- enabled | disabled
    row_version    integer      NOT NULL DEFAULT 0,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_principal_name ON principal (name);

-- 一个 Principal 可持多把 key（便于轮换：建新 → 切流 → 吊销旧）
CREATE TABLE api_key (
    id             bigint       PRIMARY KEY,
    principal_id   bigint       NOT NULL REFERENCES principal(id),
    key_prefix     varchar(16)  NOT NULL,                    -- 明文前缀，用于快速定位候选
    key_hash       varchar(256) NOT NULL,                    -- argon2 哈希；明文只在创建时返回一次
    status         varchar(16)  NOT NULL DEFAULT 'active',    -- active | revoked
    expires_at     timestamptz,
    rotated_at     timestamptz,
    last_used_at   timestamptz,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_api_key_prefix    ON api_key (key_prefix);
CREATE INDEX        idx_api_key_principal ON api_key (principal_id);

-- ═══════════════════════════════════════════════════════════════
-- 凭据与上游
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE credential (
    id             bigint       PRIMARY KEY,
    name           varchar(128) NOT NULL,
    kind           varchar(32)  NOT NULL,
        -- M0: static_header | bearer      M1: basic | oauth2_client | mtls
    ciphertext     bytea,                                    -- DEK 加密后的密文
    external_ref   varchar(256),                             -- D2 预留：将来切 Vault 时使用
    kek_id         varchar(64),                              -- 该密文由哪把 KEK 包装（轮换用）
    meta           jsonb        NOT NULL DEFAULT '{}'::jsonb,-- header 名等非敏感元数据
    rotated_at     timestamptz,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz,
    CONSTRAINT ck_credential_source CHECK (ciphertext IS NOT NULL OR external_ref IS NOT NULL)
);
CREATE UNIQUE INDEX uq_credential_name ON credential (name);

CREATE TABLE provider (
    id             bigint       PRIMARY KEY,
    code           varchar(64)  NOT NULL,
    name           varchar(128) NOT NULL,
    type           varchar(16)  NOT NULL,                    -- M0: http | local    M1: mcp
    base_url       varchar(512),
    auth_ref       bigint       REFERENCES credential(id),
    tls_config     jsonb        NOT NULL DEFAULT '{}'::jsonb,
    limits         jsonb        NOT NULL DEFAULT '{}'::jsonb,-- 出站大小/超时/header 上限
    status         varchar(16)  NOT NULL DEFAULT 'enabled',   -- enabled | disabled | archived
    row_version    integer      NOT NULL DEFAULT 0,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_provider_code ON provider (code);

-- ═══════════════════════════════════════════════════════════════
-- 工具目录
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE tool (
    id              bigint       PRIMARY KEY,
    code            varchar(160) NOT NULL,                   -- domain.system.entity.action
    source_ref      varchar(512) NOT NULL,                   -- 跨重导稳定标识（去重主键）
    provider_id     bigint       REFERENCES provider(id),     -- 【来源】Provider；与实际调用用的
                                                             -- binding.provider_id 区分（M0 二者相同）
    name            varchar(200) NOT NULL,
    description     text,
    domain          varchar(64),
    system          varchar(64),
    tags            text[]       NOT NULL DEFAULT '{}',
    risk            varchar(16)  NOT NULL DEFAULT 'low',      -- low | medium | high
    executable      boolean      NOT NULL DEFAULT true,       -- false 时检索也会过滤掉
    discoverable    boolean      NOT NULL DEFAULT true,       -- 是否出现在检索结果里
    review_required boolean      NOT NULL DEFAULT true,       -- M0 恒 true
    input_schema    jsonb,
    output_schema   jsonb,                                    -- 可空：为空则跳过输出校验
    status          varchar(16)  NOT NULL DEFAULT 'enabled',  -- enabled | disabled | stale | archived
    owner           varchar(128),
    row_version     integer      NOT NULL DEFAULT 0,
    create_by_id    bigint,
    create_by_name  varchar(128),
    create_time     timestamptz  NOT NULL DEFAULT now(),
    update_by_id    bigint,
    update_by_name  varchar(128),
    update_time     timestamptz
);
CREATE UNIQUE INDEX uq_tool_code       ON tool (code);
CREATE UNIQUE INDEX uq_tool_source_ref ON tool (source_ref);
CREATE INDEX idx_tool_domain_system    ON tool (domain, system);
CREATE INDEX idx_tool_provider         ON tool (provider_id);
CREATE INDEX idx_tool_status_exec      ON tool (status, executable);
CREATE INDEX idx_tool_tags             ON tool USING gin (tags);
-- 关键词检索（设计文档 §6.2：M0 用 pg_trgm，不引入中文分词方案）
CREATE INDEX idx_tool_name_trgm        ON tool USING gin (name gin_trgm_ops);
CREATE INDEX idx_tool_description_trgm ON tool USING gin (description gin_trgm_ops);
CREATE INDEX idx_tool_code_trgm        ON tool USING gin (code gin_trgm_ops);

CREATE TABLE tool_version (
    id             bigint       PRIMARY KEY,
    tool_id        bigint       NOT NULL REFERENCES tool(id),
    version        varchar(32)  NOT NULL,
    -- 以下为定义快照（版本不可变）
    name           varchar(200) NOT NULL,
    description    text,
    input_schema   jsonb,
    output_schema  jsonb,
    status         varchar(24)  NOT NULL DEFAULT 'draft',
        -- M0: draft | pending_review | published | rejected    M1: + deprecated | retired
    review_comment text,
    submitted_at   timestamptz,
    published_at   timestamptz,
    row_version    integer      NOT NULL DEFAULT 0,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_tool_version         ON tool_version (tool_id, version);
CREATE INDEX        idx_tool_version_status ON tool_version (status);

CREATE TABLE tool_channel (
    id             bigint      PRIMARY KEY,
    tool_id        bigint      NOT NULL REFERENCES tool(id),
    name           varchar(16) NOT NULL,                     -- stable | beta | canary
    version_id     bigint      NOT NULL REFERENCES tool_version(id),
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_tool_channel ON tool_channel (tool_id, name);

-- 每种 Provider 类型都必须有一条 binding（§4.3 的修正说明）
CREATE TABLE execution_binding (
    id              bigint       PRIMARY KEY,
    version_id      bigint       NOT NULL REFERENCES tool_version(id),
    provider_id     bigint       NOT NULL REFERENCES provider(id),
    method          varchar(8),                              -- mcp/local 类型可空
    path_template   varchar(512),                            -- 支持 {arg} 占位符
    param_mapping   jsonb        NOT NULL DEFAULT '{}'::jsonb,-- {query:{},body:{},headers:{}}
    timeout_seconds integer      NOT NULL DEFAULT 5,
    retry_max       integer      NOT NULL DEFAULT 0,
    create_by_id    bigint,
    create_by_name  varchar(128),
    create_time     timestamptz  NOT NULL DEFAULT now(),
    update_by_id    bigint,
    update_by_name  varchar(128),
    update_time     timestamptz
);
CREATE UNIQUE INDEX uq_binding_version ON execution_binding (version_id);

-- 审批留痕（追加型：审批人 = create_by_id / create_by_name）
CREATE TABLE review_record (
    id             bigint      PRIMARY KEY,
    version_id     bigint      NOT NULL REFERENCES tool_version(id),
    action         varchar(16) NOT NULL,                     -- submit | approve | reject
    from_status    varchar(24) NOT NULL,
    to_status      varchar(24) NOT NULL,
    comment        text,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE INDEX idx_review_record_version ON review_record (version_id);

-- ═══════════════════════════════════════════════════════════════
-- 授权
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE grant_rule (                                     -- grant 是 SQL 保留字
    id             bigint       PRIMARY KEY,
    principal_id   bigint       NOT NULL REFERENCES principal(id),
    scope_type     varchar(16)  NOT NULL,                     -- domain | system | tag | tool
    scope_value    varchar(160) NOT NULL,
    quota          jsonb        NOT NULL DEFAULT '{}'::jsonb,  -- {qps, daily, concurrency}
    constraints    jsonb        NOT NULL DEFAULT '{}'::jsonb,  -- {ip_cidrs, time_window, require_confirmation}
    status         varchar(16)  NOT NULL DEFAULT 'active',     -- active | disabled
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_grant_rule        ON grant_rule (principal_id, scope_type, scope_value);
CREATE INDEX        idx_grant_rule_scope ON grant_rule (scope_type, scope_value);

-- ═══════════════════════════════════════════════════════════════
-- 检索索引
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE index_meta (
    id             bigint       PRIMARY KEY,
    index_version  varchar(32)  NOT NULL,
    model          varchar(128) NOT NULL,                     -- 与在线 embedding.model 比对（启动校验）
    dimension      integer      NOT NULL,
    status         varchar(16)  NOT NULL,                     -- building | active | retired
    activated_at   timestamptz,
    retired_at     timestamptz,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_index_meta_version ON index_meta (index_version);
-- 同一时刻只允许一个 active 版本
CREATE UNIQUE INDEX uq_index_meta_single_active ON index_meta (status) WHERE status = 'active';

CREATE TABLE tool_embedding (
    id             bigint        PRIMARY KEY,
    tool_id        bigint        NOT NULL REFERENCES tool(id),
    index_version  varchar(32)   NOT NULL,
    chunk_kind     varchar(16)   NOT NULL,                    -- name | description | combined
    embedding      halfvec(2560) NOT NULL,                    -- 实测维度 2560；用 halfvec 的原因见 §4.1
    content_hash   varchar(64)   NOT NULL,                    -- 内容未变则跳过重嵌
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz   NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_tool_embedding ON tool_embedding (tool_id, index_version, chunk_kind);
CREATE INDEX idx_tool_embedding_version ON tool_embedding (index_version);
-- HNSW 索引：M0 单表即可；M2 按 domain 分区时，每个分区需要各自的索引
CREATE INDEX idx_tool_embedding_hnsw ON tool_embedding
    USING hnsw (embedding halfvec_cosine_ops);

-- ═══════════════════════════════════════════════════════════════
-- 记录（追加型，只填 create_*）
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE invocation (
    id              bigint      PRIMARY KEY,
    trace_id        varchar(64) NOT NULL,
    principal_id    bigint      NOT NULL,
    tool_id         bigint      NOT NULL,
    version_id      bigint,
    protocol        varchar(16) NOT NULL,                     -- rest | mcp | cli
    outcome         varchar(16) NOT NULL,                     -- success | failure
    error_code      varchar(64),
    duration_ms     integer,
    request_digest  varchar(64),                              -- 只存摘要，不存明文
    result_digest   varchar(64),
    result_bytes    integer,
    create_by_id    bigint,
    create_by_name  varchar(128),
    create_time     timestamptz NOT NULL DEFAULT now(),
    update_by_id    bigint,
    update_by_name  varchar(128),
    update_time     timestamptz
);
CREATE INDEX idx_invocation_trace     ON invocation (trace_id);
CREATE INDEX idx_invocation_principal ON invocation (principal_id, create_time DESC);
CREATE INDEX idx_invocation_tool      ON invocation (tool_id, create_time DESC);

CREATE TABLE audit_log (
    id             bigint      PRIMARY KEY,
    action         varchar(64) NOT NULL,
    object_type    varchar(64) NOT NULL,
    object_id      bigint,
    result         varchar(16) NOT NULL DEFAULT 'success',    -- success | failure
    before_summary jsonb,
    after_summary  jsonb,
    trace_id       varchar(64),
    create_by_id   bigint,                                    -- 即"操作人"
    create_by_name varchar(128),
    create_time    timestamptz NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE INDEX idx_audit_object ON audit_log (object_type, object_id);
CREATE INDEX idx_audit_time   ON audit_log (create_time DESC);

CREATE TABLE search_event (
    id               bigint       PRIMARY KEY,
    trace_id         varchar(64)  NOT NULL,
    principal_id     bigint       NOT NULL,
    query            varchar(512) NOT NULL,                   -- 截断 + 默认脱敏后
    scope            jsonb,
    top_k            integer      NOT NULL,
    returned         integer      NOT NULL,                   -- 实际返回条数
    total_candidates integer      NOT NULL,                   -- 权限 + scope 过滤后的候选总数
    degraded         boolean      NOT NULL DEFAULT false,
    latency_ms       integer,
    create_by_id     bigint,
    create_by_name   varchar(128),
    create_time      timestamptz  NOT NULL DEFAULT now(),
    update_by_id     bigint,
    update_by_name   varchar(128),
    update_time      timestamptz
);
CREATE INDEX idx_search_event_principal ON search_event (principal_id, create_time DESC);
CREATE INDEX idx_search_event_time      ON search_event (create_time DESC);

CREATE TABLE outbox_event (
    id             bigint      PRIMARY KEY,
    event_type     varchar(64) NOT NULL,
    object_type    varchar(64) NOT NULL,
    object_id      bigint      NOT NULL,
    payload        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status         varchar(16) NOT NULL DEFAULT 'PENDING',    -- PENDING|PROCESSING|RETRY|SUCCEEDED|DEAD
    attempts       integer     NOT NULL DEFAULT 0,
    next_retry_at  timestamptz,
    locked_by      varchar(64),
    locked_until   timestamptz,
    last_error     text,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE INDEX idx_outbox_pending ON outbox_event (status, next_retry_at);
```

---

## 4. 三处需要留意的实现约束

### 4.1 `embedding` 用 `halfvec(2560)` —— 两个实测结论

**① 维度是 2560，不是预估的 1024。** 已实测 embedding 服务
（`kinfra-text-embedding-4b`，OpenAI 兼容 `/v1/embeddings`）：返回向量长度 **2560**。

**② 2560 维用 `vector` 类型建不了 HNSW 索引。** 已实测：

| 列类型 | HNSW 索引 |
|---|---|
| `vector(2560)` | ❌ `column cannot have more than 2000 dimensions for hnsw index` |
| **`halfvec(2560)`** | ✅ 成功 |

pgvector 对 `vector` 类型的索引上限是 **2000 维**，`halfvec`（半精度）上限是 **4000 维**。
服务器上是 pgvector **0.8.6**，`halfvec` 可用。

**因此定案：`embedding halfvec(2560)` + `USING hnsw (embedding halfvec_cosine_ops)`。**

**代价与注意点**：

| 项 | 说明 |
|---|---|
| 精度 | `halfvec` 是 **float16**，相比 float32 有微小精度损失 → **召回率需在评测集上确认**（`K2` 已覆盖） |
| 存储 | 2560 × 2 字节 = **5 KB/向量**；1w 工具 × 3 种 chunk ≈ 150 MB，可接受 |
| 查询写法 | 查询向量需转成 halfvec：`ORDER BY embedding <=> $1::halfvec` |
| **降维是备选，不是首选** | 也可以把 2560 投影到 ≤2000 维后用 `vector`，但那会丢信息且需要额外模型；`halfvec` 是 pgvector 给出的标准答案 |

> ⚠️ **不要再假设维度**。`H1`（embedding 客户端）仍必须在启动时**校验**服务返回的维度与
> `index_meta.dimension` 一致——换模型时维度可能变，届时需要一个新的迁移。

### 4.2 审计字段不加外键

`create_by_id` / `update_by_id` **刻意不建 FK**：

- 操作人可能是**服务型 Principal**（不是管理账号），也可能已离职或记录被清理
- 加 FK 会让"删号"变成不可能，或导致历史审计记录被级联影响

> 如果将来需要强一致，可以加一个**视图**或定期校验任务，而不是 FK。

### 4.3 `tool.provider_id` 与 `execution_binding.provider_id` 的区别

| 字段 | 含义 |
|---|---|
| `tool.provider_id` | **来源**：这个工具是从哪个 Provider（OpenAPI 文档 / MCP Server）导入的。用于重导匹配、按来源信任策略、按来源分组 |
| `execution_binding.provider_id` | **实际调用**走哪个 Provider。M0 二者相同；将来做"预发/生产双 Provider"时才分离 |

---

## 5. 表清单（16 张）
| # | 表 | 类型 | 关键约束 |
|---|---|---|---|
| 1 | `principal` | 实体 | `uq_principal_name` |
| 2 | `api_key` | 实体 | `uq_api_key_prefix` |
| 3 | `credential` | 实体 | `ck_credential_source`（密文或外部引用至少有一个） |
| 4 | `provider` | 实体 | `uq_provider_code` |
| 5 | `tool` | 实体 | `uq_tool_code` + `uq_tool_source_ref` |
| 6 | `tool_version` | 实体（不可变快照） | `uq_tool_version(tool_id, version)` |
| 7 | `tool_channel` | 关联 | `uq_tool_channel(tool_id, name)` |
| 8 | `execution_binding` | 实体 | `uq_binding_version`（一版本一绑定） |
| 9 | `review_record` | 追加 | — |
| 10 | `grant_rule` | 实体 | `uq_grant_rule(principal_id, scope_type, scope_value)` |
| 11 | `index_meta` | 元数据 | `uq_index_meta_single_active`（**只允许一个 active**） |
| 12 | `tool_embedding` | 索引数据 | `uq_tool_embedding` + HNSW |
| 13 | `invocation` | 追加 | — |
| 14 | `audit_log` | 追加 | — |
| 15 | `search_event` | 追加 | — |
| 16 | `outbox_event` | 队列 | `idx_outbox_pending` |

---

## 6. 与迁移的关系

1. **首次建库**：可直接执行本文档的 DDL，或（推荐）把它转写为 `alembic/versions/0001_initial.py`
2. **之后所有 schema 变更只走 Alembic**，本文档**不再更新**
3. `C2` 的契约测试保证 `ORM metadata` == 迁移结果 —— 这条能同时兜住"ORM 漏写字段"和"迁移漏改"两类问题

### 建议固化为 CI 断言的两条不变量

这篇文章的三条全局约定里，有两条可以机器检查，建议做成测试（归入 `C1` / `C2`）：

| 不变量 | 检查方式 |
|---|---|
| **每张表都有雪花 `bigint` 主键** | 遍历 `Base.metadata.tables`，断言 `id` 列存在、类型为 `BigInteger`、是主键 |
| **每张表都有全部 6 个审计字段** | 断言 6 个列名在每张表上都存在（`update_*` 在追加型表上可空，但**必须存在**） |

> 这两条的价值在于：新增表时如果漏了审计字段，CI 会直接拦下——而不是等到某次审计追溯时才发现记录里没有操作人。
> （本文档的 DDL 已用一次性脚本核对通过：16 张表全部满足上述两条。）
