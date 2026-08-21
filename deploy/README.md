# ToolHive 一期部署与验收（H11）

本文档覆盖一期必须的数据库初始化、网关和基础启动验收；备份恢复、RPO/RTO、多实例与生产级监控按二期处理，不在本文档范围。

## 1. 环境要求

- 操作系统：Linux（生产建议与 Nginx 同机部署）
- Python：CPython 3.11.6（`pyproject.toml` 要求 `>=3.11.6,<3.12`）
- PostgreSQL（含 `TIMESTAMPTZ` 支持）与 Redis 可访问

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

## 5. 首个超级管理员初始化

```bash
TOOLHIVE_INIT_ADMIN_PASSWORD='<强密码>' \
  ./.venv/bin/toolhive init-admin --username admin --config /vdb/tool-hive/config/production.yaml
```

- 密码优先读环境变量 `TOOLHIVE_INIT_ADMIN_PASSWORD`；未设置时交互式输入两次（不显示）。
- 仅当管理账号表为空时可执行；已存在账号时拒绝执行并返回非零退出码。
- 初始化成功自动授予内置超管角色；超管默认拥有全部有效管理操作项。

## 6. Nginx 网关接入

参考 [deploy/nginx/toolhive.conf](./nginx/toolhive.conf)：

- 管理入口：公网 `443`，转发 `/admin/**` 与 `/api/admin/**` 到 `127.0.0.1:8100`，写入 `X-ToolHive-Ingress: admin`；
- 运行入口：内网 `8081`，仅转发 `/api/runtime/v1/**`，写入 `X-ToolHive-Ingress: runtime`；
- Header 清洗：清除客户端提交的 `Forwarded` / `X-Forwarded-For` / `X-Real-IP`，按实际 TCP 连接写入 `X-ToolHive-Client-IP: $remote_addr`；
- 应用只监听回环地址，生产必须由 Nginx 转发，不允许直连应用端口。

应用侧 `network.trusted_proxies` 必须包含 Nginx 来源地址（同机部署为 `127.0.0.1/32`、`::1/128`），否则入口请求会被拒绝。

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

开发模式（`debug=true`）跳过该校验，允许宽松配置。

## 9. 自动化验收

```bash
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

验收项：

- `/health` 返回 `{"status": "ok"}`；
- `/api/admin/bootstrap/status` 返回初始化状态（需携带入口 Header；生产建议通过 Nginx 访问）。

## 10. 基础失败恢复说明

- **进程退出/崩溃**：由 systemd/supervisor 等进程守护自动拉起，重启后应用自愈；数据库与 Redis 故障时应用拒绝相关请求而不是带病运行。
- **配置错误**：启动阶段配置校验失败会直接退出并输出具体缺失项，修复配置后重新启动。
- **备份恢复、RPO/RTO、多实例高可用与监控告警**：按二期规划，不在本期验收范围。
