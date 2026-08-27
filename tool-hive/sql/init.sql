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

-- ------------------------------------------------------------
-- Catalog：Provider
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_provider (
    id                   VARCHAR(32) PRIMARY KEY,
    provider_code        VARCHAR(128) NOT NULL,
    name                 VARCHAR(256) NOT NULL,
    provider_type        VARCHAR(20) NOT NULL DEFAULT 'http',
    status               VARCHAR(20) NOT NULL DEFAULT 'enabled',
    description          TEXT,
    target_security_config JSONB,
    row_version          INTEGER NOT NULL DEFAULT 0,
    create_time          TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time          TIMESTAMPTZ,
    create_by            VARCHAR(32),
    update_by            VARCHAR(32),
    CONSTRAINT uq_catalog_provider_code UNIQUE (provider_code)
);

CREATE INDEX IF NOT EXISTS idx_catalog_provider_status
    ON catalog_provider (status);

COMMENT ON TABLE catalog_provider IS 'Provider：工具执行的固定通道';
COMMENT ON COLUMN catalog_provider.provider_code IS 'Provider 编码（全局唯一）';
COMMENT ON COLUMN catalog_provider.provider_type IS '类型：builtin | http';
COMMENT ON COLUMN catalog_provider.status IS '状态：enabled | disabled | archived';
COMMENT ON COLUMN catalog_provider.target_security_config IS 'http 类型目标安全配置（JSON）';

-- ------------------------------------------------------------
-- Catalog：能力包
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_capability_pack (
    id            VARCHAR(32) PRIMARY KEY,
    pack_code     VARCHAR(128) NOT NULL,
    name          VARCHAR(256) NOT NULL,
    description   TEXT,
    status        VARCHAR(20) NOT NULL DEFAULT 'enabled',
    row_version   INTEGER NOT NULL DEFAULT 0,
    create_time   TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time   TIMESTAMPTZ,
    create_by     VARCHAR(32),
    update_by     VARCHAR(32),
    CONSTRAINT uq_catalog_capability_pack_code UNIQUE (pack_code)
);

CREATE INDEX IF NOT EXISTS idx_catalog_capability_pack_status
    ON catalog_capability_pack (status);

COMMENT ON TABLE catalog_capability_pack IS '能力包：工具的打包与调用系统授权单元';
COMMENT ON COLUMN catalog_capability_pack.pack_code IS '能力包编码（全局唯一）';
COMMENT ON COLUMN catalog_capability_pack.status IS '状态：enabled | disabled | archived';

-- ------------------------------------------------------------
-- Catalog：工具
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_tool (
    id                 VARCHAR(32) PRIMARY KEY,
    namespace          VARCHAR(128) NOT NULL,
    tool_code          VARCHAR(128) NOT NULL,
    name               VARCHAR(256) NOT NULL,
    description        TEXT,
    risk_level         VARCHAR(20) NOT NULL DEFAULT 'low',
    discoverable       BOOLEAN NOT NULL DEFAULT TRUE,
    executable         BOOLEAN NOT NULL DEFAULT TRUE,
    input_schema       JSONB,
    output_schema      JSONB,
    status             VARCHAR(20) NOT NULL DEFAULT 'enabled',
    default_version_id VARCHAR(32),
    row_version        INTEGER NOT NULL DEFAULT 0,
    create_time        TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time        TIMESTAMPTZ,
    create_by          VARCHAR(32),
    update_by          VARCHAR(32),
    CONSTRAINT uq_catalog_tool_namespace_code UNIQUE (namespace, tool_code)
);

CREATE INDEX IF NOT EXISTS idx_catalog_tool_namespace
    ON catalog_tool (namespace);
CREATE INDEX IF NOT EXISTS idx_catalog_tool_status
    ON catalog_tool (status);

COMMENT ON TABLE catalog_tool IS '工具：Catalog 目录条目，持有多个工具版本';
COMMENT ON COLUMN catalog_tool.namespace IS '命名空间（点分两级，如 math.basic）';
COMMENT ON COLUMN catalog_tool.tool_code IS '工具编码（命名空间内唯一）';
COMMENT ON COLUMN catalog_tool.risk_level IS '风险等级：low | medium | high';
COMMENT ON COLUMN catalog_tool.discoverable IS '是否可被发现';
COMMENT ON COLUMN catalog_tool.executable IS '是否可被执行';
COMMENT ON COLUMN catalog_tool.input_schema IS '输入 JSON Schema';
COMMENT ON COLUMN catalog_tool.output_schema IS '输出 JSON Schema';
COMMENT ON COLUMN catalog_tool.status IS '状态：enabled | disabled | archived';
COMMENT ON COLUMN catalog_tool.default_version_id IS '默认工具版本 ID';

-- ------------------------------------------------------------
-- Catalog：工具版本
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_tool_version (
    id            VARCHAR(32) PRIMARY KEY,
    tool_id       VARCHAR(32) NOT NULL REFERENCES catalog_tool(id) ON DELETE CASCADE,
    version       VARCHAR(32) NOT NULL,
    status        VARCHAR(24) NOT NULL DEFAULT 'draft',
    input_schema  JSONB,
    output_schema JSONB,
    release_note  TEXT,
    review_comment TEXT,
    row_version   INTEGER NOT NULL DEFAULT 0,
    create_time   TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time   TIMESTAMPTZ,
    create_by     VARCHAR(32),
    update_by     VARCHAR(32),
    CONSTRAINT uq_catalog_tool_version UNIQUE (tool_id, version)
);

CREATE INDEX IF NOT EXISTS idx_catalog_tool_version_tool_id
    ON catalog_tool_version (tool_id);
CREATE INDEX IF NOT EXISTS idx_catalog_tool_version_status
    ON catalog_tool_version (status);

COMMENT ON TABLE catalog_tool_version IS '工具版本：唯一走完整审核发布流程的对象';
COMMENT ON COLUMN catalog_tool_version.version IS '版本号（同一工具下唯一）';
COMMENT ON COLUMN catalog_tool_version.status IS '状态：draft | pending_review | approved | rejected | published | disabled | withdrawn | archived';
COMMENT ON COLUMN catalog_tool_version.input_schema IS '输入 JSON Schema（可覆盖工具级）';
COMMENT ON COLUMN catalog_tool_version.output_schema IS '输出 JSON Schema（可覆盖工具级）';
COMMENT ON COLUMN catalog_tool_version.release_note IS '版本说明';
COMMENT ON COLUMN catalog_tool_version.review_comment IS '审核意见/驳回原因';

-- ------------------------------------------------------------
-- Catalog：执行绑定
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_execution_binding (
    id                VARCHAR(32) PRIMARY KEY,
    version_id        VARCHAR(32) NOT NULL REFERENCES catalog_tool_version(id) ON DELETE CASCADE,
    provider_id       VARCHAR(32) NOT NULL REFERENCES catalog_provider(id) ON DELETE RESTRICT,
    method            VARCHAR(16) NOT NULL DEFAULT 'COMPUTE',
    path_template     VARCHAR(512) NOT NULL,
    parameter_mapping JSONB,
    allowed_headers   JSONB,
    response_handling JSONB,
    timeout_seconds   INTEGER,
    retry_max         INTEGER,
    idempotent        BOOLEAN NOT NULL DEFAULT TRUE,
    row_version       INTEGER NOT NULL DEFAULT 0,
    create_time       TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time       TIMESTAMPTZ,
    create_by         VARCHAR(32),
    update_by         VARCHAR(32),
    CONSTRAINT uq_catalog_execution_binding_version UNIQUE (version_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_execution_binding_provider_id
    ON catalog_execution_binding (provider_id);

COMMENT ON TABLE catalog_execution_binding IS '执行绑定：工具版本与 Provider 的固定映射';
COMMENT ON COLUMN catalog_execution_binding.version_id IS '工具版本 ID（一对一）';
COMMENT ON COLUMN catalog_execution_binding.provider_id IS 'Provider ID';
COMMENT ON COLUMN catalog_execution_binding.method IS '方法：builtin 为 COMPUTE，http 为 GET/POST/PUT/DELETE';
COMMENT ON COLUMN catalog_execution_binding.path_template IS 'http 路径模板或 builtin:// 标识';
COMMENT ON COLUMN catalog_execution_binding.parameter_mapping IS '参数映射（JSON）';
COMMENT ON COLUMN catalog_execution_binding.allowed_headers IS '允许 Header 列表';
COMMENT ON COLUMN catalog_execution_binding.response_handling IS '响应处理规则（JSON）';
COMMENT ON COLUMN catalog_execution_binding.timeout_seconds IS '执行超时（秒）';
COMMENT ON COLUMN catalog_execution_binding.retry_max IS '最大重试次数';
COMMENT ON COLUMN catalog_execution_binding.idempotent IS '是否幂等';

-- ------------------------------------------------------------
-- Catalog：审核记录
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_review_record (
    id                  VARCHAR(32) PRIMARY KEY,
    tool_id             VARCHAR(32) NOT NULL REFERENCES catalog_tool(id) ON DELETE CASCADE,
    version_id          VARCHAR(32) NOT NULL REFERENCES catalog_tool_version(id) ON DELETE CASCADE,
    action              VARCHAR(32) NOT NULL,
    from_status         VARCHAR(24) NOT NULL,
    to_status           VARCHAR(24) NOT NULL,
    comment             TEXT,
    operator_account_id VARCHAR(32),
    create_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time         TIMESTAMPTZ,
    create_by           VARCHAR(32),
    update_by           VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS idx_catalog_review_record_version_id
    ON catalog_review_record (version_id);
CREATE INDEX IF NOT EXISTS idx_catalog_review_record_tool_id
    ON catalog_review_record (tool_id);

COMMENT ON TABLE catalog_review_record IS '工具版本送审/审核记录';
COMMENT ON COLUMN catalog_review_record.action IS '动作：submit_review | approve | reject';
COMMENT ON COLUMN catalog_review_record.from_status IS '变更前状态';
COMMENT ON COLUMN catalog_review_record.to_status IS '变更后状态';
COMMENT ON COLUMN catalog_review_record.operator_account_id IS '操作人账号 ID';

-- ------------------------------------------------------------
-- Catalog：发布历史
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_publish_history (
    id                  VARCHAR(32) PRIMARY KEY,
    tool_id             VARCHAR(32) NOT NULL REFERENCES catalog_tool(id) ON DELETE CASCADE,
    version_id          VARCHAR(32) NOT NULL REFERENCES catalog_tool_version(id) ON DELETE CASCADE,
    action              VARCHAR(32) NOT NULL,
    comment             TEXT,
    operator_account_id VARCHAR(32),
    create_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time         TIMESTAMPTZ,
    create_by           VARCHAR(32),
    update_by           VARCHAR(32)
);

CREATE INDEX IF NOT EXISTS idx_catalog_publish_history_version_id
    ON catalog_publish_history (version_id);
CREATE INDEX IF NOT EXISTS idx_catalog_publish_history_tool_id
    ON catalog_publish_history (tool_id);

COMMENT ON TABLE catalog_publish_history IS '工具版本发布/停用/撤回/归档/默认切换历史';
COMMENT ON COLUMN catalog_publish_history.action IS '动作：publish | disable | enable | withdraw | archive | set_default';
COMMENT ON COLUMN catalog_publish_history.operator_account_id IS '操作人账号 ID';

-- ------------------------------------------------------------
-- Catalog：能力包 ↔ 工具 关联
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_capability_pack_tool (
    id          VARCHAR(32) PRIMARY KEY,
    pack_id     VARCHAR(32) NOT NULL REFERENCES catalog_capability_pack(id) ON DELETE CASCADE,
    tool_id     VARCHAR(32) NOT NULL REFERENCES catalog_tool(id) ON DELETE CASCADE,
    create_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time TIMESTAMPTZ,
    create_by   VARCHAR(32),
    update_by   VARCHAR(32),
    CONSTRAINT uq_catalog_pack_tool UNIQUE (pack_id, tool_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_pack_tool_tool_id
    ON catalog_capability_pack_tool (tool_id);

COMMENT ON TABLE catalog_capability_pack_tool IS '能力包与工具的多对多关联';

-- ------------------------------------------------------------
-- Catalog：能力包 ↔ 调用系统 授权关联
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_capability_pack_system (
    id          VARCHAR(32) PRIMARY KEY,
    pack_id     VARCHAR(32) NOT NULL REFERENCES catalog_capability_pack(id) ON DELETE CASCADE,
    system_id   VARCHAR(64) NOT NULL REFERENCES caller_system(system_id) ON DELETE CASCADE,
    create_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time TIMESTAMPTZ,
    create_by   VARCHAR(32),
    update_by   VARCHAR(32),
    CONSTRAINT uq_catalog_pack_system UNIQUE (pack_id, system_id)
);

CREATE INDEX IF NOT EXISTS idx_catalog_pack_system_system_id
    ON catalog_capability_pack_system (system_id);

COMMENT ON TABLE catalog_capability_pack_system IS '能力包与调用系统的授权关联';

-- ------------------------------------------------------------
-- 预置数据：内置计算 Provider（阶段 0 确认，首批数学工具使用 builtin 类型）
-- ------------------------------------------------------------
INSERT INTO catalog_provider (
    id, provider_code, name, provider_type, status, description,
    target_security_config, row_version, create_time
) VALUES (
    'builtin_math_provider', 'builtin-math', '内置计算 Provider', 'builtin', 'enabled',
    '平台内置的数学计算占位工具执行通道（阶段 1 预置，首批工具阶段 8 接入）',
    NULL, 0, now()
) ON CONFLICT (provider_code) DO NOTHING;

-- ------------------------------------------------------------
-- 运行 Trace 记录
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runtime_trace_log (
    id          VARCHAR(32) PRIMARY KEY,
    trace_id    VARCHAR(64) NOT NULL,
    system_id   VARCHAR(64),
    action      VARCHAR(64) NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'success',
    error_code  VARCHAR(64),
    summary     JSONB,
    source_ip   VARCHAR(64),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runtime_trace_log_trace_id
    ON runtime_trace_log (trace_id);
CREATE INDEX IF NOT EXISTS idx_runtime_trace_log_system_id
    ON runtime_trace_log (system_id);
CREATE INDEX IF NOT EXISTS idx_runtime_trace_log_occurred_at
    ON runtime_trace_log (occurred_at);

COMMENT ON TABLE runtime_trace_log IS '运行请求基础 Trace 记录（追加式）';
COMMENT ON COLUMN runtime_trace_log.trace_id IS 'Trace ID，跨认证/授权/执行/Provider 关联';
COMMENT ON COLUMN runtime_trace_log.system_id IS '调用系统标识';
COMMENT ON COLUMN runtime_trace_log.action IS '事件动作：runtime.auth / runtime.scope / runtime.traffic / runtime.request';
COMMENT ON COLUMN runtime_trace_log.status IS '结果：success | failure';
COMMENT ON COLUMN runtime_trace_log.error_code IS '失败时的稳定业务错误码';
COMMENT ON COLUMN runtime_trace_log.summary IS '事件摘要（JSON，脱敏）';
COMMENT ON COLUMN runtime_trace_log.source_ip IS '来源 IP';
COMMENT ON COLUMN runtime_trace_log.occurred_at IS '事件发生时间';

-- ------------------------------------------------------------
-- 运行侧高风险执行确认
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runtime_confirmation (
    id          VARCHAR(32) PRIMARY KEY,
    system_id   VARCHAR(64) NOT NULL,
    tool_id     VARCHAR(32) NOT NULL,
    version_id  VARCHAR(32),
    tool_code   VARCHAR(256) NOT NULL,
    token_hash  VARCHAR(64) NOT NULL,
    status      VARCHAR(20) NOT NULL DEFAULT 'pending',
    expires_at  TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    trace_id    VARCHAR(64),
    create_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_runtime_confirmation_system_id
    ON runtime_confirmation (system_id);
CREATE INDEX IF NOT EXISTS idx_runtime_confirmation_status
    ON runtime_confirmation (status);

COMMENT ON TABLE runtime_confirmation IS '高风险工具执行确认申请';
COMMENT ON COLUMN runtime_confirmation.system_id IS '调用系统标识';
COMMENT ON COLUMN runtime_confirmation.tool_id IS '工具 ID';
COMMENT ON COLUMN runtime_confirmation.version_id IS '工具版本 ID';
COMMENT ON COLUMN runtime_confirmation.tool_code IS '完整工具标识';
COMMENT ON COLUMN runtime_confirmation.token_hash IS '一次性确认令牌 SHA-256 哈希';
COMMENT ON COLUMN runtime_confirmation.status IS '状态：pending | consumed | expired';
COMMENT ON COLUMN runtime_confirmation.expires_at IS '令牌过期时间';
COMMENT ON COLUMN runtime_confirmation.consumed_at IS '消费时间';
COMMENT ON COLUMN runtime_confirmation.trace_id IS '关联 Trace ID';

COMMIT;
