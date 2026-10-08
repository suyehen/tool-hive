"""Initial M0 schema, frozen from reviewed DDL; never imports live ORM."""
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

_SQL = r"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;




CREATE TABLE principal (
    id             bigint       PRIMARY KEY,
    type           varchar(16)  NOT NULL,                    
    tenant_id      bigint,                                   
    name           varchar(128) NOT NULL,
    display_name   varchar(128),
    status         varchar(16)  NOT NULL DEFAULT 'enabled',   
    row_version    integer      NOT NULL DEFAULT 0,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_principal_name ON principal (name);


CREATE TABLE api_key (
    id             bigint       PRIMARY KEY,
    principal_id   bigint       NOT NULL REFERENCES principal(id),
    key_prefix     varchar(16)  NOT NULL,                    
    key_hash       varchar(256) NOT NULL,                    
    status         varchar(16)  NOT NULL DEFAULT 'active',    
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





CREATE TABLE credential (
    id             bigint       PRIMARY KEY,
    name           varchar(128) NOT NULL,
    kind           varchar(32)  NOT NULL,
        
    status         varchar(16)  NOT NULL DEFAULT 'active',    
    ciphertext     bytea,                                    
    external_ref   varchar(256),                             
    kek_id         varchar(64),                              
    meta           jsonb        NOT NULL DEFAULT '{}'::jsonb,
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
    type           varchar(16)  NOT NULL,                    
    base_url       varchar(512),
    auth_ref       bigint       REFERENCES credential(id),
    tls_config     jsonb        NOT NULL DEFAULT '{}'::jsonb,
    limits         jsonb        NOT NULL DEFAULT '{}'::jsonb,
    status         varchar(16)  NOT NULL DEFAULT 'enabled',   
    row_version    integer      NOT NULL DEFAULT 0,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_provider_code ON provider (code);





CREATE TABLE tool (
    id              bigint       PRIMARY KEY,
    code            varchar(160) NOT NULL,                   
    source_ref      varchar(512) NOT NULL,                   
    provider_id     bigint       REFERENCES provider(id),     
                                                             
    name            varchar(200) NOT NULL,
    description     text,
    domain          varchar(64),
    system          varchar(64),
    tags            text[]       NOT NULL DEFAULT '{}',
    risk            varchar(16)  NOT NULL DEFAULT 'low',      
    side_effect     varchar(16)  NOT NULL DEFAULT 'unknown'
        CONSTRAINT ck_tool_side_effect CHECK (side_effect IN ('read', 'write', 'unknown')),
    retry_safe      boolean      NOT NULL DEFAULT false,      
    executable      boolean      NOT NULL DEFAULT true,       
    discoverable    boolean      NOT NULL DEFAULT true,       
    review_required boolean      NOT NULL DEFAULT true,       
    input_schema    jsonb,
    output_schema   jsonb,                                    
    status          varchar(16)  NOT NULL DEFAULT 'enabled',  
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

CREATE INDEX idx_tool_name_trgm        ON tool USING gin (name gin_trgm_ops);
CREATE INDEX idx_tool_description_trgm ON tool USING gin (description gin_trgm_ops);
CREATE INDEX idx_tool_code_trgm        ON tool USING gin (code gin_trgm_ops);

CREATE TABLE tool_version (
    id             bigint       PRIMARY KEY,
    tool_id        bigint       NOT NULL REFERENCES tool(id),
    version        varchar(32)  NOT NULL,
    
    name           varchar(200) NOT NULL,
    description    text,
    domain         varchar(64),
    system         varchar(64),
    tags           text[]      NOT NULL DEFAULT '{}',
    risk           varchar(16) NOT NULL DEFAULT 'low',
    side_effect    varchar(16) NOT NULL DEFAULT 'unknown'
        CONSTRAINT ck_tool_version_side_effect CHECK (side_effect IN ('read', 'write', 'unknown')),
    retry_safe     boolean     NOT NULL DEFAULT false,
    executable     boolean     NOT NULL DEFAULT true,
    discoverable   boolean     NOT NULL DEFAULT true,
    input_schema   jsonb,
    output_schema  jsonb,
    status         varchar(24)  NOT NULL DEFAULT 'draft',
        
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
CREATE UNIQUE INDEX uq_tool_version_owner   ON tool_version (tool_id, id);
CREATE INDEX        idx_tool_version_status ON tool_version (status);

CREATE TABLE tool_channel (
    id             bigint      PRIMARY KEY,
    tool_id        bigint      NOT NULL REFERENCES tool(id),
    name           varchar(16) NOT NULL,                     
    version_id     bigint      NOT NULL,
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz,
    CONSTRAINT fk_channel_version_owner FOREIGN KEY (tool_id, version_id)
        REFERENCES tool_version (tool_id, id)
);
CREATE UNIQUE INDEX uq_tool_channel ON tool_channel (tool_id, name);


CREATE TABLE execution_binding (
    id              bigint       PRIMARY KEY,
    version_id      bigint       NOT NULL REFERENCES tool_version(id),
    provider_id     bigint       NOT NULL REFERENCES provider(id),
    method          varchar(8),                              
    path_template   varchar(512),                            
    param_mapping   jsonb,                                   
    timeout_seconds integer,                                
    retry_max       integer,                                
    create_by_id    bigint,
    create_by_name  varchar(128),
    create_time     timestamptz  NOT NULL DEFAULT now(),
    update_by_id    bigint,
    update_by_name  varchar(128),
    update_time     timestamptz
);
CREATE UNIQUE INDEX uq_binding_version ON execution_binding (version_id);


CREATE TABLE review_record (
    id             bigint      PRIMARY KEY,
    version_id     bigint      NOT NULL REFERENCES tool_version(id),
    action         varchar(16) NOT NULL,                     
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





CREATE TABLE grant_rule (                                     
    id             bigint       PRIMARY KEY,
    principal_id   bigint       NOT NULL REFERENCES principal(id),
    scope_type     varchar(16)  NOT NULL,                     
    scope_value    varchar(160) NOT NULL,
    quota          jsonb        NOT NULL DEFAULT '{}'::jsonb,  
    constraints    jsonb        NOT NULL DEFAULT '{}'::jsonb,  
    status         varchar(16)  NOT NULL DEFAULT 'active',     
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz  NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_grant_rule        ON grant_rule (principal_id, scope_type, scope_value);
CREATE INDEX        idx_grant_rule_scope ON grant_rule (scope_type, scope_value);





CREATE TABLE index_meta (
    id             bigint       PRIMARY KEY,
    index_version  varchar(32)  NOT NULL,
    model          varchar(128) NOT NULL,                     
    dimension      integer      NOT NULL,
    status         varchar(16)  NOT NULL,                     
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

CREATE UNIQUE INDEX uq_index_meta_single_active ON index_meta (status) WHERE status = 'active';

CREATE TABLE tool_embedding (
    id             bigint        PRIMARY KEY,
    tool_id        bigint        NOT NULL REFERENCES tool(id),
    index_version  varchar(32)   NOT NULL,
    chunk_kind     varchar(16)   NOT NULL,                    
    embedding      halfvec(2560) NOT NULL,                    
    content_hash   varchar(64)   NOT NULL,                    
    create_by_id   bigint,
    create_by_name varchar(128),
    create_time    timestamptz   NOT NULL DEFAULT now(),
    update_by_id   bigint,
    update_by_name varchar(128),
    update_time    timestamptz
);
CREATE UNIQUE INDEX uq_tool_embedding ON tool_embedding (tool_id, index_version, chunk_kind);
CREATE INDEX idx_tool_embedding_version ON tool_embedding (index_version);

CREATE INDEX idx_tool_embedding_hnsw ON tool_embedding
    USING hnsw (embedding halfvec_cosine_ops);





CREATE TABLE invocation (
    id              bigint      PRIMARY KEY,
    trace_id        varchar(64) NOT NULL,
    principal_id    bigint      NOT NULL,
    tool_id         bigint      NOT NULL,
    version_id      bigint,
    provider_id     bigint,                                   
    provider_row_version integer,
    binding_digest  varchar(64),                              
    provider_config_digest varchar(64),                       
    protocol        varchar(16) NOT NULL,                     
    outcome         varchar(16) NOT NULL,                     
    error_code      varchar(64),
    duration_ms     integer,
    request_digest  varchar(64),                              
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
    result         varchar(16) NOT NULL DEFAULT 'success',    
    before_summary jsonb,
    after_summary  jsonb,
    trace_id       varchar(64),
    create_by_id   bigint,                                    
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
    query            varchar(512) NOT NULL,                   
    scope            jsonb,
    top_k            integer      NOT NULL,
    returned         integer      NOT NULL,                   
    total_candidates integer      NOT NULL,                   
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
    status         varchar(16) NOT NULL DEFAULT 'PENDING',    
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
"""


def upgrade() -> None:
    for statement in _SQL.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade() -> None:
    op.drop_table("outbox_event")
    op.drop_table("search_event")
    op.drop_table("audit_log")
    op.drop_table("invocation")
    op.drop_table("tool_embedding")
    op.drop_table("index_meta")
    op.drop_table("grant_rule")
    op.drop_table("review_record")
    op.drop_table("execution_binding")
    op.drop_table("tool_channel")
    op.drop_table("tool_version")
    op.drop_table("tool")
    op.drop_table("provider")
    op.drop_table("credential")
    op.drop_table("api_key")
    op.drop_table("principal")
