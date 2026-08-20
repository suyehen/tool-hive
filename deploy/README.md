# ToolHive 一期部署与验收（H11）

本文档覆盖一期必须的迁移、初始化、网关和基础启动验收；备份恢复、RPO/RTO、多实例与生产级监控按二期处理，不在本文档范围。

## 1. 环境要求

- 操作系统：Linux（生产建议与 Nginx 同机部署）
- Python：CPython 3.11.6（`pyproject.toml` 要求 `>=3.11.6,<3.12`）
- PostgreSQL（含 `TIMESTAMPTZ` 支持）与 Redis 可访问

## 2. 安装

```bash
cd tool-hive
bash scripts/install.sh
```

脚本会创建 `.venv` 虚拟环境并安装 `toolhive`（含 dev 依赖）。也可手动指定解释器：

```bash
PYTHON_BIN=/path/to/python3.11 bash scripts/install.sh
```

## 3. 数据库初始化与迁移

全新环境先执行基线建表，再执行增量迁移：

```bash
# 1) 基线建表（幂等）
psql "$DATABASE_URL" -f sql/init.sql

# 2) 增量迁移（可重复执行；当前无增量时为无操作）
./.venv/bin/toolhive db-migrate --config /vdb/tool-hive/config/production.yaml
```

迁移规则：`sql/migrations/` 下的 `*.sql` 按文件名顺序执行，已执行文件记录在 `schema_migrations` 表，重复执行同一命令不会重复应用。

## 4. 首个超级管理员初始化

```bash
TOOLHIVE_INIT_ADMIN_PASSWORD='<强密码>' \
  ./.venv/bin/toolhive init-admin --username admin --config /vdb/tool-hive/config/production.yaml
```

- 密码优先读环境变量 `TOOLHIVE_INIT_ADMIN_PASSWORD`；未设置时交互式输入两次（不显示）。
- 仅当管理账号表为空时可执行；已存在账号时拒绝执行并返回非零退出码。
- 初始化成功自动授予内置超管角色；超管默认拥有全部有效管理操作项。

## 5. Nginx 网关接入

参考 [deploy/nginx/toolhive.conf](./nginx/toolhive.conf)：

- 管理入口：公网 `443`，转发 `/admin/**` 与 `/api/admin/**` 到 `127.0.0.1:8100`，写入 `X-ToolHive-Ingress: admin`；
- 运行入口：内网 `8081`，仅转发 `/api/runtime/v1/**`，写入 `X-ToolHive-Ingress: runtime`；
- Header 清洗：清除客户端提交的 `Forwarded` / `X-Forwarded-For` / `X-Real-IP`，按实际 TCP 连接写入 `X-ToolHive-Client-IP: $remote_addr`；
- 应用只监听回环地址，生产必须由 Nginx 转发，不允许直连应用端口。

应用侧 `network.trusted_proxies` 必须包含 Nginx 来源地址（同机部署为 `127.0.0.1/32`、`::1/128`），否则入口请求会被拒绝。

## 6. 启动

```bash
TOOLHIVE_CONFIG_FILE=/vdb/tool-hive/config/production.yaml bash scripts/start.sh
```

脚本以单 Uvicorn Worker 启动并仅监听 `127.0.0.1:8100`；配置文件不存在时启动失败并输出明确错误。

## 7. 生产配置校验（配置缺失时启动失败）

应用启动（lifespan）时执行生产配置校验，`debug=false` 下任一条件不满足将**拒绝启动**并输出原因：

- `csrf_secret` 必须非空；
- `database_url` / `redis_url` 不能使用默认占位密码 `changeme`；
- `network.allow_loopback_direct` 必须为 `false`；
- `bind_host` 必须绑定回环地址（`127.0.0.1` 或 `::1`）；
- `network.trusted_proxies` 不能为空，必须包含部署的 Nginx 地址。

开发模式（`debug=true`）跳过该校验，允许宽松配置。

## 8. 自动化验收

```bash
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

验收项：

- `/health` 返回 `{"status": "ok"}`；
- `/api/admin/bootstrap/status` 返回初始化状态（需携带入口 Header；生产建议通过 Nginx 访问）。

## 9. 基础失败恢复说明

- **进程退出/崩溃**：由 systemd/supervisor 等进程守护自动拉起，重启后应用自愈；数据库与 Redis 故障时应用拒绝相关请求而不是带病运行。
- **配置错误**：启动阶段配置校验失败会直接退出并输出具体缺失项，修复配置后重新启动。
- **数据库迁移失败**：迁移脚本均幂等且逐文件记录，失败后修复脚本内容可重跑 `db-migrate`。
- **备份恢复、RPO/RTO、多实例高可用与监控告警**：按二期规划，不在本期验收范围。
