# ToolHive 一期部署与验收（H11）

本文档覆盖一期必须的数据库初始化、网关和基础启动验收；备份恢复、RPO/RTO、多实例与生产级监控按二期处理，不在本文档范围。

## 1. 环境要求

- 操作系统：Linux（生产建议与 Nginx 同机部署）
- Python：CPython 3.11.6（`pyproject.toml` 要求 `>=3.11.6,<3.12`）
- PostgreSQL（含 `TIMESTAMPTZ` 支持）与 Redis 可访问
- 嵌入式 Chroma：`chromadb` 随 `install.sh` 安装，生产持久化目录固定为配置的 `chroma.persist_directory`（默认 `/vdb/tool-hive/chroma`，需可写）
- 检索 Embedding（可选，未配置时 Discover 自动降级为关键词检索）：腾讯云 TokenHub API Key（`model_api_key`）与模型名（`embedding_model`，一期为 `kinfra-text-embedding-4b`）

## 2. 创建数据库和用户（先执行）

`sql/init.sql` 只负责建表，不创建数据库。首次部署必须先以 PostgreSQL 超级用户（如 `postgres`）创建应用用户和数据库，参考 [sql/create_database.sql](../tool-hive/sql/create_database.sql)：

```sql
CREATE USER toolhive WITH PASSWORD '<应用数据库密码>';
CREATE DATABASE toolhive OWNER toolhive ENCODING 'UTF8';
```

执行顺序（先建库、后建表）：

1. 本步：创建用户和数据库；
2. 第 4 步：执行 `sql/init.sql` 建表；

## 3. 安装

```bash
cd tool-hive
bash scripts/install.sh
```

脚本会创建 `.venv` 虚拟环境并安装 `toolhive`（含 dev 依赖）。也可手动指定解释器：

```bash
PYTHON_BIN=/path/to/python3.11 bash scripts/install.sh
```

## 4. 数据库初始化（建表）

全新环境在第 2 步创建好数据库后执行建表。开发阶段表结构变更直接修改 `sql/init.sql`，不保留历史变更记录：

```bash
# 建表（幂等）
psql "$DATABASE_URL" -f sql/init.sql
```

### 4.1 首批工具与索引

建表完成后执行（幂等，可重复执行）：

```bash
# 接入首批数学计算工具 math.basic.calculator（建工具 → 建版本+绑定 → 审核 → 发布设默认）
./.venv/bin/toolhive seed-tools --config /vdb/tool-hive/config/production.yaml

# 全量重建 Chroma 索引（需已配置 model_api_key / embedding_model；未配置时用于确认降级路径）
./.venv/bin/toolhive rebuild-chroma --config /vdb/tool-hive/config/production.yaml
```

## 5. 首个超级管理员初始化

```bash
TOOLHIVE_INIT_ADMIN_PASSWORD='<强密码>' \
  ./.venv/bin/toolhive init-admin --account admin --real-name '<姓名>' --config /vdb/tool-hive/config/production.yaml
```

- 密码优先读环境变量 `TOOLHIVE_INIT_ADMIN_PASSWORD`；未设置时交互式输入两次（不显示）。
- 仅当管理账号表为空时可执行；已存在账号时拒绝执行并返回非零退出码。
- 初始化成功自动授予内置超管角色；超管默认拥有全部有效管理操作项。

## 6. Nginx 网关接入

参考 [deploy/nginx/toolhive.conf](./nginx/toolhive.conf)：

- 管理入口：公网 `443`，转发 `/admin/**` 与 `/api/admin/**` 到 `127.0.0.1:8100`，写入 `X-ToolHive-Ingress: admin`；
- 运行入口：内网 `8081`，仅转发 `/api/runtime/v1/**`，写入 `X-ToolHive-Ingress: runtime`；**默认只允许本机来源**（`allow 127.0.0.1; allow ::1; deny all;`），若调用系统分布在其他主机，按实际内网网段替换为 `allow 10.0.0.0/8;`、`allow 172.16.0.0/12;`、`allow 192.168.0.0/16;` 等，一期不允许公网访问运行入口；
- Header 清洗：清除客户端提交的 `Forwarded` / `X-Forwarded-For` / `X-Real-IP`，按实际 TCP 连接写入 `X-ToolHive-Client-IP: $remote_addr`；
- 限流：管理入口全局 `10 r/s`（burst 20），`/api/admin/auth/**` 登录/验证码等接口 `5 r/s`（burst 8），运行入口内网基础限流 `50 r/s`（burst 100）；zone 定义位于示例配置顶部，需处于 Nginx `http` 上下文；
- 应用只监听回环地址，生产必须由 Nginx 转发，不允许直连应用端口。

应用侧 `network.trusted_proxies` 必须包含 Nginx 来源地址（同机部署为 `127.0.0.1/32`、`::1/128`），否则入口请求会被拒绝。

应用层限流：登录失败按来源 IP 在 `login_failure_window_minutes` 窗口内累计，达到 `login_max_failures` 次后拒绝；验证码挑战接口按来源 IP 每分钟最多 `captcha_challenge_max_per_minute` 次（默认 10 次）。Nginx 与应用层限流共同构成管理侧基础限流。

## 7. 启动

```bash
TOOLHIVE_CONFIG_FILE=/vdb/tool-hive/config/production.yaml bash scripts/start.sh
```

脚本以单 Uvicorn Worker 启动并仅监听 `127.0.0.1:8100`；配置文件不存在时启动失败并输出明确错误。

## 8. 生产配置校验（配置缺失时启动失败）

应用启动（lifespan）时执行生产配置校验，`debug=false` 下任一条件不满足将**拒绝启动**并输出原因：

- `csrf_secret` 必须非空；
- `database_url` / `redis_url` 不能使用默认占位密码 `changeme`；
- `network.allow_loopback_direct` 必须为 `false`；
- `bind_host` 必须绑定回环地址（`127.0.0.1` 或 `::1`）；
- `network.trusted_proxies` 不能为空，必须包含部署的 Nginx 地址。
- 运行侧签名：`signature_time_window_seconds` / `nonce_retention_minutes` / `signing_key_min_bits`（≥2048）必须为正，`signing_algorithm` 必须是 `RSA-PSS-SHA256` 或 `Ed25519`，`signature_version` 必须为 `TOOLHIVE-SIGN-V1`。
- Embedding 与 Chroma：`embedding_model` 与 `model_api_key` 必须同时配置或同时为空；`chroma.persist_directory` 不能为空；一期 `chroma.mode` 必须为 `embedded`。
- Provider 出站限制：`provider_max_response_bytes` / `provider_max_header_count` / `provider_connect_timeout_seconds` 必须大于 0。

开发模式（`debug=true`）跳过该校验，允许宽松配置。

## 9. 自动化验收

```bash
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

验收项：

- `/health` 返回 `{"status": "ok"}`；
- `/api/admin/bootstrap/status` 返回初始化状态（需携带入口 Header；生产建议通过 Nginx 访问）；
- 运行入口配置存在且包含 `X-ToolHive-Ingress: runtime`。

## 9.1 运行入口端到端验收（签名 → 认证 → 发现 → 执行 → Trace）

运行 API 只接受签名请求。验收前先在管理端完成调用系统登记：

1. 管理端「调用系统」登记一个已启用系统（`system_id`），添加 RSA-PSS-SHA256 公钥（记下 `key_id`）、来源 IP 规则（本机 `127.0.0.1/32`）、运行策略（允许 `/api/runtime/v1/**`）、工具范围（`math.basic.calculator`）；
2. 调用系统侧保管私钥 PEM 文件（如 `caller.pem`）；
3. 用 `toolhive sign-request` 生成签名 curl 命令：

```bash
./.venv/bin/toolhive sign-request \
  --method POST \
  --path /api/runtime/v1/ping \
  --system-id sys_xxx \
  --key-id key_xxx \
  --private-key caller.pem \
  --base-url http://127.0.0.1:8081
```

4. 执行输出的 curl 命令，预期返回 `{"status":"ok","system_id":"sys_xxx","trace_id":"..."}`；
5. 依次验收：

```bash
# 精确解析
toolhive sign-request --method POST --path /api/runtime/v1/tools/resolve \
  --body '{"tool_code":"math.basic.calculator"}' --system-id sys_xxx --key-id key_xxx --private-key caller.pem
# 发现（关键词）
toolhive sign-request --method POST --path /api/runtime/v1/tools/discover \
  --body '{"query":"数学"}' --system-id sys_xxx --key-id key_xxx --private-key caller.pem
# 执行
toolhive sign-request --method POST --path /api/runtime/v1/tools/math.basic.calculator/execute \
  --body '{"arguments":{"a":1,"b":2,"operation":"add"}}' --system-id sys_xxx --key-id key_xxx --private-key caller.pem
```

执行接口预期返回 `{"result":{"result":3},...}` 与 `trace_id`；
6. 低风险工具无需确认；高风险/写操作工具需先调用 `POST /api/runtime/v1/confirmations` 申请令牌，再在 execute 请求体携带 `confirmation_id` 与 `confirmation_token`；
7. Trace 落库：`runtime_trace_log` 中按 `trace_id` 可查到 `runtime.auth` / `runtime.scope` / `runtime.retrieval` / `runtime.control` / `runtime.provider` / `runtime.execute` 等事件；管理端「工具测试」执行产生的 Trace 以 `system_id=management` 标注 `source=admin-test`。

> 提示：`sign-request` 只生成命令不自动发起请求；时间戳与 Nonce 默认当前生成，重复执行同一命令会因时间窗/Nonce 变化失效，属预期行为。

## 10. 基础失败恢复说明

- **进程退出/崩溃**：由 systemd/supervisor 等进程守护自动拉起，重启后应用自愈；数据库与 Redis 故障时应用拒绝相关请求而不是带病运行。
- **配置错误**：启动阶段配置校验失败会直接退出并输出具体缺失项，修复配置后重新启动。
- **备份恢复、RPO/RTO、多实例高可用与监控告警**：按二期规划，不在本期验收范围。
