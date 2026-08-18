-- ============================================================
-- ToolHive 数据库初始化脚本
-- 用途：开发早期/新环境建表使用；表结构变化时直接修改本脚本，
--       不保留历史变更记录（当前阶段所有表变更均属预期内操作）。
-- 说明：
--   1. 所有业务主键 id 由应用层生成，DDL 不设置默认值。
--   2. create_time/update_time 由应用层维护，create_time 有数据库
--      默认值；create_id/update_id 记录操作人 ID，
--      create_name/update_name 记录操作人名称，均可为空。
--   3. 时间统一使用 TIMESTAMPTZ。
--   4. 本脚本及后续所有字段变更一律不使用外键（FOREIGN KEY），
--      引用完整性由应用层保证。
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 管理账号
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_account (
    id                        VARCHAR(32) PRIMARY KEY,
    username                  VARCHAR(128) NOT NULL,
    password_hash             VARCHAR(256) NOT NULL,
    external_user_id          VARCHAR(256),
    status                    VARCHAR(20) NOT NULL DEFAULT 'enabled',
    login_failures            INTEGER NOT NULL DEFAULT 0,
    locked_until              TIMESTAMPTZ,
    must_change_password      BOOLEAN NOT NULL DEFAULT TRUE,
    temp_password_expires_at  TIMESTAMPTZ,
    create_time                TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time                TIMESTAMPTZ,
    create_id                VARCHAR(32),
    update_id                VARCHAR(32),
    create_name           VARCHAR(128),
    update_name           VARCHAR(128),
    CONSTRAINT uq_management_account_username UNIQUE (username),
    CONSTRAINT uq_management_account_external_user_id UNIQUE (external_user_id)
);

CREATE INDEX IF NOT EXISTS idx_management_account_username
    ON management_account (username);
CREATE INDEX IF NOT EXISTS idx_management_account_external_user_id
    ON management_account (external_user_id);
CREATE INDEX IF NOT EXISTS idx_management_account_status
    ON management_account (status);

COMMENT ON TABLE management_account IS '管理账号';
COMMENT ON COLUMN management_account.id IS '主键，应用层生成';
COMMENT ON COLUMN management_account.username IS '登录用户名，全局唯一';
COMMENT ON COLUMN management_account.password_hash IS '密码哈希';
COMMENT ON COLUMN management_account.external_user_id IS '外部身份唯一标识，保存工号或外部系统唯一标识，用于 SSO 登录时匹配内部账号';
COMMENT ON COLUMN management_account.status IS '账号状态';
COMMENT ON COLUMN management_account.login_failures IS '连续登录失败次数';
COMMENT ON COLUMN management_account.locked_until IS '锁定到期时间';
COMMENT ON COLUMN management_account.must_change_password IS '是否必须修改密码';
COMMENT ON COLUMN management_account.temp_password_expires_at IS '临时密码过期时间';
COMMENT ON COLUMN management_account.create_time IS '创建时间';
COMMENT ON COLUMN management_account.update_time IS '最后更新时间';
COMMENT ON COLUMN management_account.create_id IS '创建人 ID';
COMMENT ON COLUMN management_account.update_id IS '修改人 ID';
COMMENT ON COLUMN management_account.create_name IS '创建人名称';
COMMENT ON COLUMN management_account.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 后台角色
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backend_role (
    id              VARCHAR(32) PRIMARY KEY,
    name            VARCHAR(128) NOT NULL,
    description     VARCHAR(512),
    is_super_admin  BOOLEAN NOT NULL DEFAULT FALSE,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_id      VARCHAR(32),
    update_id      VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128),
    CONSTRAINT uq_backend_role_name UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_backend_role_name
    ON backend_role (name);
CREATE INDEX IF NOT EXISTS idx_backend_role_status
    ON backend_role (status);

COMMENT ON TABLE backend_role IS '后台角色';
COMMENT ON COLUMN backend_role.id IS '主键，应用层生成';
COMMENT ON COLUMN backend_role.name IS '角色名称，唯一';
COMMENT ON COLUMN backend_role.description IS '角色说明';
COMMENT ON COLUMN backend_role.is_super_admin IS '是否为超级管理员角色';
COMMENT ON COLUMN backend_role.status IS '角色状态';
COMMENT ON COLUMN backend_role.create_time IS '创建时间';
COMMENT ON COLUMN backend_role.update_time IS '最后更新时间';
COMMENT ON COLUMN backend_role.create_id IS '创建人 ID';
COMMENT ON COLUMN backend_role.update_id IS '修改人 ID';
COMMENT ON COLUMN backend_role.create_name IS '创建人名称';
COMMENT ON COLUMN backend_role.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 管理账号 ↔ 后台角色 关联
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS account_role (
    id          VARCHAR(32) PRIMARY KEY,
    account_id  VARCHAR(32) NOT NULL,
    role_id     VARCHAR(32) NOT NULL,
    create_time  TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time  TIMESTAMPTZ,
    create_id  VARCHAR(32),
    update_id  VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128),
    CONSTRAINT uq_account_role UNIQUE (account_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_account_role_account_id
    ON account_role (account_id);
CREATE INDEX IF NOT EXISTS idx_account_role_role_id
    ON account_role (role_id);

COMMENT ON TABLE account_role IS '管理账号与后台角色关联';
COMMENT ON COLUMN account_role.id IS '主键，应用层生成';
COMMENT ON COLUMN account_role.account_id IS '管理账号 ID';
COMMENT ON COLUMN account_role.role_id IS '后台角色 ID';
COMMENT ON COLUMN account_role.create_time IS '创建时间';
COMMENT ON COLUMN account_role.update_time IS '最后更新时间';
COMMENT ON COLUMN account_role.create_id IS '创建人 ID';
COMMENT ON COLUMN account_role.update_id IS '修改人 ID';
COMMENT ON COLUMN account_role.create_name IS '创建人名称';
COMMENT ON COLUMN account_role.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 管理操作项
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS management_operation (
    operation_code  VARCHAR(128) PRIMARY KEY,
    display_name    VARCHAR(256) NOT NULL,
    description     TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'active',
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_id      VARCHAR(32),
    update_id      VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128)
);

COMMENT ON TABLE management_operation IS '管理操作项';
COMMENT ON COLUMN management_operation.operation_code IS '操作码（主键），唯一';
COMMENT ON COLUMN management_operation.display_name IS '显示名称';
COMMENT ON COLUMN management_operation.description IS '操作项说明';
COMMENT ON COLUMN management_operation.status IS '状态';
COMMENT ON COLUMN management_operation.create_time IS '创建时间';
COMMENT ON COLUMN management_operation.update_time IS '最后更新时间';
COMMENT ON COLUMN management_operation.create_id IS '创建人 ID';
COMMENT ON COLUMN management_operation.update_id IS '修改人 ID';
COMMENT ON COLUMN management_operation.create_name IS '创建人名称';
COMMENT ON COLUMN management_operation.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 后台角色 ↔ 管理操作项 关联
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS role_operation (
    id              VARCHAR(32) PRIMARY KEY,
    role_id         VARCHAR(32) NOT NULL,
    operation_code  VARCHAR(128) NOT NULL,
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_id      VARCHAR(32),
    update_id      VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128),
    CONSTRAINT uq_role_operation UNIQUE (role_id, operation_code)
);

CREATE INDEX IF NOT EXISTS idx_role_operation_role_id
    ON role_operation (role_id);
CREATE INDEX IF NOT EXISTS idx_role_operation_operation_code
    ON role_operation (operation_code);

COMMENT ON TABLE role_operation IS '后台角色与管理操作项关联';
COMMENT ON COLUMN role_operation.id IS '主键，应用层生成';
COMMENT ON COLUMN role_operation.role_id IS '后台角色 ID';
COMMENT ON COLUMN role_operation.operation_code IS '管理操作码';
COMMENT ON COLUMN role_operation.create_time IS '创建时间';
COMMENT ON COLUMN role_operation.update_time IS '最后更新时间';
COMMENT ON COLUMN role_operation.create_id IS '创建人 ID';
COMMENT ON COLUMN role_operation.update_id IS '修改人 ID';
COMMENT ON COLUMN role_operation.create_name IS '创建人名称';
COMMENT ON COLUMN role_operation.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 管理账号 MFA TOTP 配置
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mfa_config (
    id                    VARCHAR(32) PRIMARY KEY,
    account_id            VARCHAR(32) NOT NULL,
    encrypted_secret      VARCHAR(512) NOT NULL,
    recovery_codes_hash   TEXT NOT NULL,
    is_bound              BOOLEAN NOT NULL DEFAULT FALSE,
    create_time            TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time            TIMESTAMPTZ,
    create_id            VARCHAR(32),
    update_id            VARCHAR(32),
    create_name       VARCHAR(128),
    update_name       VARCHAR(128),
    CONSTRAINT uq_mfa_config_account UNIQUE (account_id)
);

CREATE INDEX IF NOT EXISTS idx_mfa_config_account_id
    ON mfa_config (account_id);

COMMENT ON TABLE mfa_config IS '管理账号 MFA TOTP 配置';
COMMENT ON COLUMN mfa_config.id IS '主键，应用层生成';
COMMENT ON COLUMN mfa_config.account_id IS '管理账号 ID';
COMMENT ON COLUMN mfa_config.encrypted_secret IS '加密的 TOTP 密钥';
COMMENT ON COLUMN mfa_config.recovery_codes_hash IS '恢复码哈希列表';
COMMENT ON COLUMN mfa_config.is_bound IS '是否已完成 MFA 绑定';
COMMENT ON COLUMN mfa_config.create_time IS '创建时间';
COMMENT ON COLUMN mfa_config.update_time IS '最后更新时间';
COMMENT ON COLUMN mfa_config.create_id IS '创建人 ID';
COMMENT ON COLUMN mfa_config.update_id IS '修改人 ID';
COMMENT ON COLUMN mfa_config.create_name IS '创建人名称';
COMMENT ON COLUMN mfa_config.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 密码历史
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS password_history (
    id              VARCHAR(32) PRIMARY KEY,
    account_id      VARCHAR(32) NOT NULL,
    password_hash   VARCHAR(256) NOT NULL,
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_id      VARCHAR(32),
    update_id      VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128)
);

CREATE INDEX IF NOT EXISTS idx_password_history_account_id
    ON password_history (account_id);

COMMENT ON TABLE password_history IS '密码历史';
COMMENT ON COLUMN password_history.id IS '主键，应用层生成';
COMMENT ON COLUMN password_history.account_id IS '管理账号 ID';
COMMENT ON COLUMN password_history.password_hash IS '历史密码哈希';
COMMENT ON COLUMN password_history.create_time IS '创建时间';
COMMENT ON COLUMN password_history.update_time IS '最后更新时间';
COMMENT ON COLUMN password_history.create_id IS '创建人 ID';
COMMENT ON COLUMN password_history.update_id IS '修改人 ID';
COMMENT ON COLUMN password_history.create_name IS '创建人名称';
COMMENT ON COLUMN password_history.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 调用系统
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caller_system (
    id                 VARCHAR(32) PRIMARY KEY,
    system_id          VARCHAR(64) NOT NULL,
    name               VARCHAR(256) NOT NULL,
    description        TEXT,
    environment        VARCHAR(20) NOT NULL,
    department         VARCHAR(256),
    owner              VARCHAR(256),
    contact            VARCHAR(256),
    status             VARCHAR(20) NOT NULL DEFAULT 'draft',
    effective_from     TIMESTAMPTZ,
    effective_to       TIMESTAMPTZ,
    deactivated_reason TEXT,
    create_time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time         TIMESTAMPTZ,
    create_id         VARCHAR(32),
    update_id         VARCHAR(32),
    create_name    VARCHAR(128),
    update_name    VARCHAR(128),
    CONSTRAINT uq_caller_system_system_id UNIQUE (system_id)
);

CREATE INDEX IF NOT EXISTS idx_caller_system_system_id
    ON caller_system (system_id);
CREATE INDEX IF NOT EXISTS idx_caller_system_name
    ON caller_system (name);
CREATE INDEX IF NOT EXISTS idx_caller_system_environment
    ON caller_system (environment);
CREATE INDEX IF NOT EXISTS idx_caller_system_status
    ON caller_system (status);

COMMENT ON TABLE caller_system IS '调用系统';
COMMENT ON COLUMN caller_system.id IS '主键，应用层生成';
COMMENT ON COLUMN caller_system.system_id IS '调用系统公开标识，唯一';
COMMENT ON COLUMN caller_system.name IS '系统名称';
COMMENT ON COLUMN caller_system.description IS '系统说明';
COMMENT ON COLUMN caller_system.environment IS '所属环境';
COMMENT ON COLUMN caller_system.department IS '所属部门或团队';
COMMENT ON COLUMN caller_system.owner IS '负责人';
COMMENT ON COLUMN caller_system.contact IS '联系方式';
COMMENT ON COLUMN caller_system.status IS '状态';
COMMENT ON COLUMN caller_system.effective_from IS '生效时间';
COMMENT ON COLUMN caller_system.effective_to IS '失效时间';
COMMENT ON COLUMN caller_system.deactivated_reason IS '停用或注销原因';
COMMENT ON COLUMN caller_system.create_time IS '创建时间';
COMMENT ON COLUMN caller_system.update_time IS '最后更新时间';
COMMENT ON COLUMN caller_system.create_id IS '创建人 ID';
COMMENT ON COLUMN caller_system.update_id IS '修改人 ID';
COMMENT ON COLUMN caller_system.create_name IS '创建人名称';
COMMENT ON COLUMN caller_system.update_name IS '修改人名称';

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
    create_time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time      TIMESTAMPTZ,
    create_id      VARCHAR(32),
    update_id      VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128),
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
COMMENT ON COLUMN caller_public_key.effective_from IS '生效时间';
COMMENT ON COLUMN caller_public_key.effective_to IS '失效时间';
COMMENT ON COLUMN caller_public_key.create_time IS '创建时间';
COMMENT ON COLUMN caller_public_key.update_time IS '最后更新时间';
COMMENT ON COLUMN caller_public_key.create_id IS '创建人 ID';
COMMENT ON COLUMN caller_public_key.update_id IS '修改人 ID';
COMMENT ON COLUMN caller_public_key.create_name IS '创建人名称';
COMMENT ON COLUMN caller_public_key.update_name IS '修改人名称';

-- ------------------------------------------------------------
-- 调用系统来源 IP 规则
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS caller_ip_rule (
    id          VARCHAR(32) PRIMARY KEY,
    system_id   VARCHAR(64) NOT NULL,
    ip_cidr     VARCHAR(64) NOT NULL,
    description TEXT,
    status      VARCHAR(20) NOT NULL DEFAULT 'active',
    create_time  TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time  TIMESTAMPTZ,
    create_id  VARCHAR(32),
    update_id  VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128)
);

CREATE INDEX IF NOT EXISTS idx_caller_ip_rule_system_id
    ON caller_ip_rule (system_id);

COMMENT ON TABLE caller_ip_rule IS '调用系统来源 IP 白名单规则';
COMMENT ON COLUMN caller_ip_rule.id IS '主键，应用层生成';
COMMENT ON COLUMN caller_ip_rule.system_id IS '所属调用系统标识';
COMMENT ON COLUMN caller_ip_rule.ip_cidr IS '来源 IP 或 CIDR';
COMMENT ON COLUMN caller_ip_rule.description IS '规则说明';
COMMENT ON COLUMN caller_ip_rule.status IS '状态';
COMMENT ON COLUMN caller_ip_rule.create_time IS '创建时间';
COMMENT ON COLUMN caller_ip_rule.update_time IS '最后更新时间';
COMMENT ON COLUMN caller_ip_rule.create_id IS '创建人 ID';
COMMENT ON COLUMN caller_ip_rule.update_id IS '修改人 ID';
COMMENT ON COLUMN caller_ip_rule.create_name IS '创建人名称';
COMMENT ON COLUMN caller_ip_rule.update_name IS '修改人名称';

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
    create_id      VARCHAR(32),
    update_id      VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128)
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
COMMENT ON COLUMN outbox_event.create_id IS '创建人 ID';
COMMENT ON COLUMN outbox_event.update_id IS '修改人 ID';
COMMENT ON COLUMN outbox_event.create_name IS '创建人名称';
COMMENT ON COLUMN outbox_event.update_name IS '修改人名称';

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
    create_time   TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_time   TIMESTAMPTZ,
    create_id   VARCHAR(32),
    update_id   VARCHAR(32),
    create_name VARCHAR(128),
    update_name VARCHAR(128),
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
COMMENT ON COLUMN outbox_delivery.create_time IS '创建时间';
COMMENT ON COLUMN outbox_delivery.update_time IS '最后更新时间';
COMMENT ON COLUMN outbox_delivery.create_id IS '创建人 ID';
COMMENT ON COLUMN outbox_delivery.update_id IS '修改人 ID';
COMMENT ON COLUMN outbox_delivery.create_name IS '创建人名称';
COMMENT ON COLUMN outbox_delivery.update_name IS '修改人名称';

COMMIT;
