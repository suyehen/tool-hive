-- ============================================================
-- ToolHive 数据库建表脚本
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 管理账号
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_account (
    id                        VARCHAR(32) PRIMARY KEY,
    account                   VARCHAR(128) NOT NULL,
    real_name                 VARCHAR(128) NOT NULL,
    external_user_id          VARCHAR(256),
    email                     VARCHAR(256),
    mobile                    VARCHAR(32),
    department                VARCHAR(256),
    remark                    VARCHAR(512),
    account_type              VARCHAR(32),
    status                    VARCHAR(20) NOT NULL DEFAULT 'enabled',
    row_version               INTEGER NOT NULL DEFAULT 0,
    create_time                TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time                TIMESTAMPTZ,
    create_by                VARCHAR(32),
    update_by                VARCHAR(32),
    CONSTRAINT uq_management_account_account UNIQUE (account),
    CONSTRAINT uq_management_account_external_user_id UNIQUE (external_user_id)
);

CREATE INDEX IF NOT EXISTS idx_management_account_account
    ON management_account (account);
CREATE INDEX IF NOT EXISTS idx_management_account_external_user_id
    ON management_account (external_user_id);
CREATE INDEX IF NOT EXISTS idx_management_account_status
    ON management_account (status);

COMMENT ON TABLE management_account IS '管理账号';
COMMENT ON COLUMN management_account.id IS '主键，应用层生成';
COMMENT ON COLUMN management_account.account IS '登录账号，全局唯一';
COMMENT ON COLUMN management_account.real_name IS '姓名';
COMMENT ON COLUMN management_account.external_user_id IS '外部身份唯一标识（工号），用于 SSO 登录匹配内部账号';
COMMENT ON COLUMN management_account.email IS '邮箱';
COMMENT ON COLUMN management_account.mobile IS '手机号';
COMMENT ON COLUMN management_account.department IS '部门';
COMMENT ON COLUMN management_account.remark IS '备注';
COMMENT ON COLUMN management_account.account_type IS '账号类型/来源（预留二期 SSO 使用）';
COMMENT ON COLUMN management_account.status IS '账号状态';
COMMENT ON COLUMN management_account.row_version IS '乐观锁版本号，用于并发更新保护';
COMMENT ON COLUMN management_account.create_time IS '创建时间';
COMMENT ON COLUMN management_account.update_time IS '最后更新时间';
COMMENT ON COLUMN management_account.create_by IS '创建人 ID';
COMMENT ON COLUMN management_account.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 管理账号认证状态（与 management_account 1:1）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_account_auth_state (
    account_id                 VARCHAR(32) PRIMARY KEY,
    password_hash              VARCHAR(256) NOT NULL,
    login_failures             INTEGER NOT NULL DEFAULT 0,
    locked_until               TIMESTAMPTZ,
    must_change_password       BOOLEAN NOT NULL DEFAULT TRUE,
    temp_password_expires_at   TIMESTAMPTZ,
    security_version           INTEGER NOT NULL DEFAULT 0,
    create_time                TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time                TIMESTAMPTZ,
    create_by                  VARCHAR(32),
    update_by                  VARCHAR(32)
);

COMMENT ON TABLE management_account_auth_state IS '管理账号认证与登录安全状态（与 management_account 1:1）';
COMMENT ON COLUMN management_account_auth_state.account_id IS '账号 ID（主键，与 management_account.id 一一对应）';
COMMENT ON COLUMN management_account_auth_state.password_hash IS '密码哈希';
COMMENT ON COLUMN management_account_auth_state.login_failures IS '连续登录失败次数';
COMMENT ON COLUMN management_account_auth_state.locked_until IS '锁定到期时间';
COMMENT ON COLUMN management_account_auth_state.must_change_password IS '是否必须修改密码';
COMMENT ON COLUMN management_account_auth_state.temp_password_expires_at IS '临时密码过期时间';
COMMENT ON COLUMN management_account_auth_state.security_version IS '安全事件版本，用于会话失效判定';
COMMENT ON COLUMN management_account_auth_state.create_time IS '创建时间';
COMMENT ON COLUMN management_account_auth_state.update_time IS '最后更新时间';
COMMENT ON COLUMN management_account_auth_state.create_by IS '创建人 ID';
COMMENT ON COLUMN management_account_auth_state.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 后台角色
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_role (
    id              VARCHAR(32) PRIMARY KEY,
    code            VARCHAR(64) NOT NULL,
    name            VARCHAR(128) NOT NULL,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_builtin      BOOLEAN NOT NULL DEFAULT FALSE,
    description     VARCHAR(512),
    is_super_admin  BOOLEAN NOT NULL DEFAULT FALSE,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    row_version     INTEGER NOT NULL DEFAULT 0,
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_by      VARCHAR(32),
    update_by      VARCHAR(32),
    CONSTRAINT uq_management_role_name UNIQUE (name),
    CONSTRAINT uq_management_role_code UNIQUE (code)
);

CREATE INDEX IF NOT EXISTS idx_management_role_code
    ON management_role (code);
CREATE INDEX IF NOT EXISTS idx_management_role_name
    ON management_role (name);
CREATE INDEX IF NOT EXISTS idx_management_role_status
    ON management_role (status);

COMMENT ON TABLE management_role IS '后台角色';
COMMENT ON COLUMN management_role.id IS '主键，应用层生成';
COMMENT ON COLUMN management_role.code IS '角色编码，唯一，创建后不可修改';
COMMENT ON COLUMN management_role.name IS '角色名称，唯一';
COMMENT ON COLUMN management_role.sort_order IS '排序值，越小越靠前';
COMMENT ON COLUMN management_role.is_builtin IS '是否内置角色（系统创建，不可删除）';
COMMENT ON COLUMN management_role.description IS '角色说明';
COMMENT ON COLUMN management_role.is_super_admin IS '是否为超级管理员角色';
COMMENT ON COLUMN management_role.status IS '角色状态';
COMMENT ON COLUMN management_role.row_version IS '乐观锁版本号，用于并发更新保护';
COMMENT ON COLUMN management_role.create_time IS '创建时间';
COMMENT ON COLUMN management_role.update_time IS '最后更新时间';
COMMENT ON COLUMN management_role.create_by IS '创建人 ID';
COMMENT ON COLUMN management_role.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 管理账号 ↔ 后台角色 关联
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_account_role (
    id          VARCHAR(32) PRIMARY KEY,
    account_id  VARCHAR(32) NOT NULL,
    role_id     VARCHAR(32) NOT NULL,
    create_time  TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time  TIMESTAMPTZ,
    create_by  VARCHAR(32),
    update_by  VARCHAR(32),
    CONSTRAINT uq_management_account_role UNIQUE (account_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_management_account_role_account_id
    ON management_account_role (account_id);
CREATE INDEX IF NOT EXISTS idx_management_account_role_role_id
    ON management_account_role (role_id);

COMMENT ON TABLE management_account_role IS '管理账号与后台角色关联';
COMMENT ON COLUMN management_account_role.id IS '主键，应用层生成';
COMMENT ON COLUMN management_account_role.account_id IS '管理账号 ID';
COMMENT ON COLUMN management_account_role.role_id IS '后台角色 ID';
COMMENT ON COLUMN management_account_role.create_time IS '创建时间';
COMMENT ON COLUMN management_account_role.update_time IS '最后更新时间';
COMMENT ON COLUMN management_account_role.create_by IS '创建人 ID';
COMMENT ON COLUMN management_account_role.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 管理操作项
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_operation (
    operation_code  VARCHAR(128) PRIMARY KEY,
    category        VARCHAR(64) NOT NULL DEFAULT 'other',
    display_name    VARCHAR(256) NOT NULL,
    description     TEXT,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_by      VARCHAR(32),
    update_by      VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS idx_management_operation_category
    ON management_operation (category);

COMMENT ON TABLE management_operation IS '管理操作项';
COMMENT ON COLUMN management_operation.operation_code IS '操作码（主键），唯一';
COMMENT ON COLUMN management_operation.category IS '操作权限分类';
COMMENT ON COLUMN management_operation.display_name IS '显示名称';
COMMENT ON COLUMN management_operation.description IS '操作项说明';
COMMENT ON COLUMN management_operation.sort_order IS '分类内排序值，越小越靠前';
COMMENT ON COLUMN management_operation.status IS '状态';
COMMENT ON COLUMN management_operation.create_time IS '创建时间';
COMMENT ON COLUMN management_operation.update_time IS '最后更新时间';
COMMENT ON COLUMN management_operation.create_by IS '创建人 ID';
COMMENT ON COLUMN management_operation.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 管理操作审计（追加式，不更新、不删除）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_audit_log (
    id                 VARCHAR(32) PRIMARY KEY,
    actor_account_id   VARCHAR(32),
    actor_account_name VARCHAR(128),
    actor_system_id    VARCHAR(64),
    object_type        VARCHAR(64) NOT NULL,
    object_id          VARCHAR(64),
    action             VARCHAR(128) NOT NULL,
    before_summary     TEXT,
    after_summary      TEXT,
    reason             TEXT,
    result             VARCHAR(20) NOT NULL DEFAULT 'success',
    trace_id           VARCHAR(64),
    source_ip          VARCHAR(64),
    occurred_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_management_audit_log_actor_account
    ON management_audit_log (actor_account_id);
CREATE INDEX IF NOT EXISTS idx_management_audit_log_object
    ON management_audit_log (object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_management_audit_log_action
    ON management_audit_log (action);
CREATE INDEX IF NOT EXISTS idx_management_audit_log_occurred_at
    ON management_audit_log (occurred_at);

COMMENT ON TABLE management_audit_log IS '管理操作审计记录（追加式）';
COMMENT ON COLUMN management_audit_log.actor_account_id IS '操作人账号 ID';
COMMENT ON COLUMN management_audit_log.actor_account_name IS '操作人用户名';
COMMENT ON COLUMN management_audit_log.actor_system_id IS '调用系统 ID（管理侧一般为空）';
COMMENT ON COLUMN management_audit_log.object_type IS '操作对象类型';
COMMENT ON COLUMN management_audit_log.object_id IS '操作对象 ID';
COMMENT ON COLUMN management_audit_log.action IS '动作码';
COMMENT ON COLUMN management_audit_log.before_summary IS '变更前摘要（JSON，脱敏）';
COMMENT ON COLUMN management_audit_log.after_summary IS '变更后摘要（JSON，脱敏）';
COMMENT ON COLUMN management_audit_log.reason IS '原因或失败说明';
COMMENT ON COLUMN management_audit_log.result IS '结果：success | failure';
COMMENT ON COLUMN management_audit_log.trace_id IS '关联 Trace ID';
COMMENT ON COLUMN management_audit_log.source_ip IS '来源 IP';
COMMENT ON COLUMN management_audit_log.occurred_at IS '事件发生时间';

-- ------------------------------------------------------------
-- 后台角色 ↔ 管理操作项 关联
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_role_operation (
    id              VARCHAR(32) PRIMARY KEY,
    role_id         VARCHAR(32) NOT NULL,
    operation_code  VARCHAR(128) NOT NULL,
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_by      VARCHAR(32),
    update_by      VARCHAR(32),
    CONSTRAINT uq_management_role_operation UNIQUE (role_id, operation_code)
);

CREATE INDEX IF NOT EXISTS idx_management_role_operation_role_id
    ON management_role_operation (role_id);
CREATE INDEX IF NOT EXISTS idx_management_role_operation_operation_code
    ON management_role_operation (operation_code);

COMMENT ON TABLE management_role_operation IS '后台角色与管理操作项关联';
COMMENT ON COLUMN management_role_operation.id IS '主键，应用层生成';
COMMENT ON COLUMN management_role_operation.role_id IS '后台角色 ID';
COMMENT ON COLUMN management_role_operation.operation_code IS '管理操作码';
COMMENT ON COLUMN management_role_operation.create_time IS '创建时间';
COMMENT ON COLUMN management_role_operation.update_time IS '最后更新时间';
COMMENT ON COLUMN management_role_operation.create_by IS '创建人 ID';
COMMENT ON COLUMN management_role_operation.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 密码历史
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_account_password_history (
    id              VARCHAR(32) PRIMARY KEY,
    account_id      VARCHAR(32) NOT NULL,
    password_hash   VARCHAR(256) NOT NULL,
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_by      VARCHAR(32),
    update_by      VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS idx_management_account_password_history_account_id
    ON management_account_password_history (account_id);

COMMENT ON TABLE management_account_password_history IS '密码历史';
COMMENT ON COLUMN management_account_password_history.id IS '主键，应用层生成';
COMMENT ON COLUMN management_account_password_history.account_id IS '管理账号 ID';
COMMENT ON COLUMN management_account_password_history.password_hash IS '历史密码哈希';
COMMENT ON COLUMN management_account_password_history.create_time IS '创建时间';
COMMENT ON COLUMN management_account_password_history.update_time IS '最后更新时间';
COMMENT ON COLUMN management_account_password_history.create_by IS '创建人 ID';
COMMENT ON COLUMN management_account_password_history.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 调用系统
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caller_system (
    id                 VARCHAR(32) PRIMARY KEY,
    system_id          VARCHAR(64) NOT NULL,
    name               VARCHAR(256) NOT NULL,
    description        TEXT,
    environment        VARCHAR(20) NOT NULL,
    belonging_party    VARCHAR(256),
    code               VARCHAR(128) NOT NULL,
    owner              VARCHAR(256),
    contact            VARCHAR(256),
    owner_email        VARCHAR(256),
    tags               TEXT,
    status             VARCHAR(20) NOT NULL DEFAULT 'draft',
    effective_from     TIMESTAMPTZ,
    effective_to       TIMESTAMPTZ,
    deactivated_reason TEXT,
    emergency_disabled BOOLEAN NOT NULL DEFAULT FALSE,
    emergency_disabled_reason TEXT,
    emergency_disabled_at TIMESTAMPTZ,
    row_version        INTEGER NOT NULL DEFAULT 0,
    create_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time         TIMESTAMPTZ,
    create_by         VARCHAR(32),
    update_by         VARCHAR(32),
    CONSTRAINT uq_caller_system_system_id UNIQUE (system_id),
    CONSTRAINT uq_caller_system_environment_code UNIQUE (environment, code)
);

CREATE INDEX IF NOT EXISTS idx_caller_system_system_id
    ON caller_system (system_id);
CREATE INDEX IF NOT EXISTS idx_caller_system_name
    ON caller_system (name);
CREATE INDEX IF NOT EXISTS idx_caller_system_environment
    ON caller_system (environment);
CREATE INDEX IF NOT EXISTS idx_caller_system_status
    ON caller_system (status);
CREATE INDEX IF NOT EXISTS idx_caller_system_code
    ON caller_system (code);

COMMENT ON TABLE caller_system IS '调用系统';
COMMENT ON COLUMN caller_system.id IS '主键，应用层生成';
COMMENT ON COLUMN caller_system.system_id IS '调用系统公开标识，唯一';
COMMENT ON COLUMN caller_system.name IS '系统名称';
COMMENT ON COLUMN caller_system.description IS '系统说明';
COMMENT ON COLUMN caller_system.environment IS '所属环境';
COMMENT ON COLUMN caller_system.belonging_party IS '归属方（纯描述）';
COMMENT ON COLUMN caller_system.code IS '系统编码，必填';
COMMENT ON COLUMN caller_system.owner IS '负责人';
COMMENT ON COLUMN caller_system.contact IS '联系方式';
COMMENT ON COLUMN caller_system.owner_email IS '负责人邮箱（通知收件人）';
COMMENT ON COLUMN caller_system.tags IS '标签（JSON 数组）';
COMMENT ON COLUMN caller_system.status IS '状态';
COMMENT ON COLUMN caller_system.row_version IS '乐观锁版本号，用于并发更新保护';
COMMENT ON COLUMN caller_system.effective_from IS '生效时间';
COMMENT ON COLUMN caller_system.effective_to IS '失效时间';
COMMENT ON COLUMN caller_system.deactivated_reason IS '停用或注销原因';
COMMENT ON COLUMN caller_system.emergency_disabled IS '是否处于系统级紧急禁用状态';
COMMENT ON COLUMN caller_system.emergency_disabled_reason IS '紧急禁用原因';
COMMENT ON COLUMN caller_system.emergency_disabled_at IS '紧急禁用时间';
COMMENT ON COLUMN caller_system.create_time IS '创建时间';
COMMENT ON COLUMN caller_system.update_time IS '最后更新时间';
COMMENT ON COLUMN caller_system.create_by IS '创建人 ID';
COMMENT ON COLUMN caller_system.update_by IS '修改人 ID';

-- 兼容已存在的调用系统表：幂等补充紧急禁用字段
ALTER TABLE caller_system ADD COLUMN IF NOT EXISTS emergency_disabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE caller_system ADD COLUMN IF NOT EXISTS emergency_disabled_reason TEXT;
ALTER TABLE caller_system ADD COLUMN IF NOT EXISTS emergency_disabled_at TIMESTAMPTZ;

-- ------------------------------------------------------------
-- 调用系统运行策略（每系统一条）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caller_runtime_policy (
    id                       VARCHAR(32) PRIMARY KEY,
    system_id                VARCHAR(64) NOT NULL,
    allowed_api_patterns     TEXT NOT NULL,
    qps_limit                INTEGER NOT NULL,
    concurrency_limit        INTEGER NOT NULL,
    quota_per_day            INTEGER NOT NULL,
    request_timeout_seconds  INTEGER NOT NULL,
    circuit_breaker_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    effective_from           TIMESTAMPTZ,
    effective_to             TIMESTAMPTZ,
    row_version              INTEGER NOT NULL DEFAULT 0,
    create_time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time              TIMESTAMPTZ,
    create_by                VARCHAR(32),
    update_by                VARCHAR(32),
    CONSTRAINT uq_caller_runtime_policy_system UNIQUE (system_id)
);

CREATE INDEX IF NOT EXISTS idx_caller_runtime_policy_system_id
    ON caller_runtime_policy (system_id);

COMMENT ON TABLE caller_runtime_policy IS '调用系统运行策略';
COMMENT ON COLUMN caller_runtime_policy.system_id IS '调用系统公开标识';
COMMENT ON COLUMN caller_runtime_policy.allowed_api_patterns IS '允许访问的运行 API 范围（JSON 数组）';
COMMENT ON COLUMN caller_runtime_policy.qps_limit IS '每秒请求上限';
COMMENT ON COLUMN caller_runtime_policy.concurrency_limit IS '并发请求上限';
COMMENT ON COLUMN caller_runtime_policy.quota_per_day IS '每日配额上限';
COMMENT ON COLUMN caller_runtime_policy.request_timeout_seconds IS '请求超时时间（秒）';
COMMENT ON COLUMN caller_runtime_policy.circuit_breaker_enabled IS '是否启用熔断';
COMMENT ON COLUMN caller_runtime_policy.effective_from IS '策略生效时间';
COMMENT ON COLUMN caller_runtime_policy.effective_to IS '策略失效时间';
COMMENT ON COLUMN caller_runtime_policy.row_version IS '乐观锁版本号';

-- ------------------------------------------------------------
-- 调用系统工具范围
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caller_tool_scope (
    id            VARCHAR(32) PRIMARY KEY,
    system_id     VARCHAR(64) NOT NULL,
    scope_type    VARCHAR(20) NOT NULL DEFAULT 'tool',
    scope_code    VARCHAR(256) NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'active',
    row_version   INTEGER NOT NULL DEFAULT 0,
    create_time   TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time   TIMESTAMPTZ,
    create_by     VARCHAR(32),
    update_by     VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS idx_caller_tool_scope_system_id
    ON caller_tool_scope (system_id);
CREATE INDEX IF NOT EXISTS idx_caller_tool_scope_code
    ON caller_tool_scope (scope_code);

COMMENT ON TABLE caller_tool_scope IS '调用系统可访问的工具/能力包范围';
COMMENT ON COLUMN caller_tool_scope.scope_type IS '范围类型：capability（能力包）| tool（工具）';
COMMENT ON COLUMN caller_tool_scope.scope_code IS '工具或能力包编码';
COMMENT ON COLUMN caller_tool_scope.status IS '状态：active | disabled';

-- ------------------------------------------------------------
-- 调用系统公钥
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caller_public_key (
    id              VARCHAR(32) PRIMARY KEY,
    key_id          VARCHAR(64) NOT NULL,
    system_id       VARCHAR(64) NOT NULL,
    public_key      TEXT NOT NULL,
    fingerprint     VARCHAR(128) NOT NULL,
    algorithm       VARCHAR(32) NOT NULL DEFAULT 'RSA-PSS-SHA256',
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    effective_from  TIMESTAMPTZ NOT NULL,
    effective_to    TIMESTAMPTZ,
    row_version     INTEGER NOT NULL DEFAULT 0,
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_by      VARCHAR(32),
    update_by      VARCHAR(32),
    CONSTRAINT uq_caller_public_key_key_id UNIQUE (key_id)
);

CREATE INDEX IF NOT EXISTS idx_caller_public_key_key_id
    ON caller_public_key (key_id);
CREATE INDEX IF NOT EXISTS idx_caller_public_key_system_id
    ON caller_public_key (system_id);
CREATE INDEX IF NOT EXISTS idx_caller_public_key_status
    ON caller_public_key (status);

COMMENT ON TABLE caller_public_key IS '调用系统公钥记录';
COMMENT ON COLUMN caller_public_key.id IS '主键，应用层生成';
COMMENT ON COLUMN caller_public_key.key_id IS '公钥标识，唯一';
COMMENT ON COLUMN caller_public_key.system_id IS '所属调用系统标识';
COMMENT ON COLUMN caller_public_key.public_key IS '公钥（PEM）';
COMMENT ON COLUMN caller_public_key.fingerprint IS '公钥指纹';
COMMENT ON COLUMN caller_public_key.algorithm IS '签名算法';
COMMENT ON COLUMN caller_public_key.status IS '状态';
COMMENT ON COLUMN caller_public_key.row_version IS '乐观锁版本号，用于并发更新保护';
COMMENT ON COLUMN caller_public_key.effective_from IS '生效时间';
COMMENT ON COLUMN caller_public_key.effective_to IS '失效时间';
COMMENT ON COLUMN caller_public_key.create_time IS '创建时间';
COMMENT ON COLUMN caller_public_key.update_time IS '最后更新时间';
COMMENT ON COLUMN caller_public_key.create_by IS '创建人 ID';
COMMENT ON COLUMN caller_public_key.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- 调用系统来源 IP 规则
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caller_ip_rule (
    id          VARCHAR(32) PRIMARY KEY,
    system_id   VARCHAR(64) NOT NULL,
    ip_cidr     VARCHAR(64) NOT NULL,
    description TEXT,
    status      VARCHAR(20) NOT NULL DEFAULT 'active',
    row_version INTEGER NOT NULL DEFAULT 0,
    create_time  TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time  TIMESTAMPTZ,
    create_by  VARCHAR(32),
    update_by  VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS idx_caller_ip_rule_system_id
    ON caller_ip_rule (system_id);

COMMENT ON TABLE caller_ip_rule IS '调用系统来源 IP 白名单规则';
COMMENT ON COLUMN caller_ip_rule.id IS '主键，应用层生成';
COMMENT ON COLUMN caller_ip_rule.system_id IS '所属调用系统标识';
COMMENT ON COLUMN caller_ip_rule.ip_cidr IS '来源 IP 或 CIDR';
COMMENT ON COLUMN caller_ip_rule.description IS '规则说明';
COMMENT ON COLUMN caller_ip_rule.status IS '状态';
COMMENT ON COLUMN caller_ip_rule.row_version IS '乐观锁版本号，用于并发更新保护';
COMMENT ON COLUMN caller_ip_rule.create_time IS '创建时间';
COMMENT ON COLUMN caller_ip_rule.update_time IS '最后更新时间';
COMMENT ON COLUMN caller_ip_rule.create_by IS '创建人 ID';
COMMENT ON COLUMN caller_ip_rule.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- Outbox 事件
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outbox_event (
    event_id        VARCHAR(32) PRIMARY KEY,
    event_type      VARCHAR(64) NOT NULL,
    object_type     VARCHAR(64) NOT NULL,
    object_id       VARCHAR(32) NOT NULL,
    object_version  VARCHAR(64),
    payload         JSONB,
    status          VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    attempts        INTEGER NOT NULL DEFAULT 0,
    locked_by       VARCHAR(64),
    locked_until    TIMESTAMPTZ,
    next_retry_at   TIMESTAMPTZ,
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_by      VARCHAR(32),
    update_by      VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS idx_outbox_event_status_next_retry
    ON outbox_event (status, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_outbox_event_object
    ON outbox_event (object_type, object_id);

COMMENT ON TABLE outbox_event IS 'Outbox 事件';
COMMENT ON COLUMN outbox_event.event_id IS '事件 ID（主键）';
COMMENT ON COLUMN outbox_event.event_type IS '事件类型';
COMMENT ON COLUMN outbox_event.object_type IS '业务对象类型';
COMMENT ON COLUMN outbox_event.object_id IS '业务对象 ID';
COMMENT ON COLUMN outbox_event.object_version IS '业务对象版本';
COMMENT ON COLUMN outbox_event.payload IS '事件附加信息';
COMMENT ON COLUMN outbox_event.status IS '状态';
COMMENT ON COLUMN outbox_event.attempts IS '处理尝试次数';
COMMENT ON COLUMN outbox_event.locked_by IS '领取任务实例标识';
COMMENT ON COLUMN outbox_event.locked_until IS '任务锁到期时间';
COMMENT ON COLUMN outbox_event.next_retry_at IS '下次重试时间';
COMMENT ON COLUMN outbox_event.create_time IS '创建时间';
COMMENT ON COLUMN outbox_event.update_time IS '最后更新时间';
COMMENT ON COLUMN outbox_event.create_by IS '创建人 ID';
COMMENT ON COLUMN outbox_event.update_by IS '修改人 ID';

-- ------------------------------------------------------------
-- Outbox 投递记录
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS outbox_delivery (
    delivery_id  VARCHAR(32) PRIMARY KEY,
    event_id     VARCHAR(32) NOT NULL,
    target       VARCHAR(32) NOT NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    attempts     INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT,
    duration_ms  INTEGER,
    worker_instance VARCHAR(64),
    create_time   TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time   TIMESTAMPTZ,
    create_by   VARCHAR(32),
    update_by   VARCHAR(32),
    CONSTRAINT uq_outbox_delivery_event_target UNIQUE (event_id, target)
);

CREATE INDEX IF NOT EXISTS idx_outbox_delivery_event_id
    ON outbox_delivery (event_id);
CREATE INDEX IF NOT EXISTS idx_outbox_delivery_status
    ON outbox_delivery (status);

COMMENT ON TABLE outbox_delivery IS 'Outbox 投递记录';
COMMENT ON COLUMN outbox_delivery.delivery_id IS '投递 ID（主键）';
COMMENT ON COLUMN outbox_delivery.event_id IS '事件 ID';
COMMENT ON COLUMN outbox_delivery.target IS '投递目标';
COMMENT ON COLUMN outbox_delivery.status IS '状态';
COMMENT ON COLUMN outbox_delivery.attempts IS '投递尝试次数';
COMMENT ON COLUMN outbox_delivery.last_error IS '最近一次错误信息';
COMMENT ON COLUMN outbox_delivery.duration_ms IS '最近一次投递耗时（毫秒）';
COMMENT ON COLUMN outbox_delivery.worker_instance IS '处理投递的 Worker 实例标识';
COMMENT ON COLUMN outbox_delivery.create_time IS '创建时间';
COMMENT ON COLUMN outbox_delivery.update_time IS '最后更新时间';
COMMENT ON COLUMN outbox_delivery.create_by IS '创建人 ID';
COMMENT ON COLUMN outbox_delivery.update_by IS '修改人 ID';

COMMIT;
