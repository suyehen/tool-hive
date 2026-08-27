<h1 align="center">ToolHive</h1>

<p align="center">
  <a href="tool-hive/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/docs-English-blue" alt="English Docs"></a>
</p>

<p align="center">
  <b>Agent 的工具蜂巢</b><br/>
  统一托管、策略鉴权、安全执行，让 LLM 只负责思考，不直接触碰网络与凭据。
</p>

---

## 项目简介

ToolHive 是面向 Agent、业务系统及其他服务调用方的统一工具平台。平台将外部系统能力登记为受控工具，在调用前完成身份认证、工具调用控制、参数校验与受控执行；调用方只能使用平台在当前上下文中允许发现的工具，无法自行指定目标地址、HTTP 方法、认证 Header 或平台托管的凭据。

核心能力：

- 集中工具目录：Provider、工具、版本与能力包统一登记，审核发布后才可被调用；
- 管理与运行分离：管理入口 `/admin/**`、`/api/admin/**` 与运行入口 `/api/runtime/**` 使用不同的身份与认证方式，相互隔离；
- 按需发现与二次校验：执行时对真实参数、资源范围和高风险操作重新校验；
- 受控 Provider 执行：按审核后的固定请求映射调用外部服务，并处理凭据引用、超时、错误转换与结果清洗；
- 可追溯治理：管理变更、认证、授权决策与执行保留必要的脱敏 Trace / 审计记录。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端 | Python 3.11.6 · FastAPI · Uvicorn · SQLAlchemy (async) |
| 数据存储 | PostgreSQL · Redis · Chroma (embedded) |
| 前端 | React 18 · TypeScript · Vite · Ant Design |
| 网关 | Nginx |

## 项目结构

```text
toolhive/
├── tool-hive/    # 后端服务（FastAPI 应用、CLI、部署脚本）
├── frontend/     # 管理前端（React + Vite）
├── deploy/       # 部署配置（Nginx 网关示例、部署文档）
└── docs/         # 架构与需求文档
```

## 环境要求

- Linux（生产建议与 Nginx 同机部署）；
- CPython 3.11.6（`>=3.11.6,<3.12`）；
- PostgreSQL 与 Redis；
- Node.js 18+（仅前端开发与构建需要）。

## 部署与启动

### 1. 本地开发（.env 配置）

复制 [.env.example](./tool-hive/.env.example) 为 `tool-hive/.env`，修改数据库、Redis 等连接信息（IP/端口/密码）。`.env` 支持全部配置字段（含 `network` / `chroma` 等嵌套分组），本地开发建议设置 `TOOLHIVE_DEBUG=true`、`TOOLHIVE_NETWORK_ALLOW_LOOPBACK_DIRECT=true`（Vite 开发代理不携带入口 Header）。

首次部署需先在服务器上用 PostgreSQL 超级用户创建应用用户和数据库（模板见 [sql/create_database.sql](./tool-hive/sql/create_database.sql)），再执行下面的建表步骤。执行顺序：先建库 → 再建表。

一期开发中所有 DDL 改动（建表、改表、删表、改字段）一律直接修改 `sql/init.sql`，不保留历史迁移记录。

```bash
cd tool-hive

# 安装依赖（创建 .venv 虚拟环境并安装 toolhive）
bash scripts/install.sh

# 准备本地配置
cp .env.example .env

# 数据库初始化：建表（库已由 create_database.sql 创建；连接信息读取 .env）
psql "postgresql://toolhive:<密码>@localhost:5432/toolhive" -f sql/init.sql

# 初始化首个超级管理员（仅空库可执行，密码建议用环境变量传入）
TOOLHIVE_INIT_ADMIN_PASSWORD='<强密码>' \
  ./.venv/bin/toolhive init-admin --account admin --real-name '<姓名>'

# 启动（监听 127.0.0.1:8100，自动读取 .env）
./.venv/bin/uvicorn toolhive.main:app --host 127.0.0.1 --port 8100

# 验证服务
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

Windows 本地（PowerShell）对应命令：

```powershell
cd tool-hive

# 准备本地配置
Copy-Item .env.example .env

# 数据库初始化：建表（库已由 create_database.sql 创建；连接信息读取 .env）
psql "postgresql://toolhive:<密码>@localhost:5432/toolhive" -f sql/init.sql

# 初始化首个超级管理员（仅空库可执行；PowerShell 使用 $env: 设置环境变量）
$env:TOOLHIVE_INIT_ADMIN_PASSWORD='<强密码>'
toolhive init-admin --account admin --real-name '<姓名>'

# 启动（需先激活 Python 环境，如 conda activate toolhive 或 .\.venv\Scripts\Activate.ps1）
python -m uvicorn toolhive.main:app --host 127.0.0.1 --port 8100
```

> 若未安装 `toolhive` 命令，可用 `python -m toolhive.cli init-admin --account admin --real-name '<姓名>'` 替代；`scripts/verify.sh` 为 bash 脚本，Windows 下可用 Git Bash / WSL 执行。配置优先级：真实环境变量 > 外挂 YAML > `.env` 文件 > 代码默认值；完整字段说明见 [.env.example](./tool-hive/.env.example) 与 [toolhive.example.yaml](./tool-hive/toolhive.example.yaml)。

### 2. 前端（开发模式）

```bash
cd frontend
npm install
npm run dev
```

开发服务器默认运行在 `http://localhost:5173`，`/api` 请求自动代理到 `http://127.0.0.1:8100`。

### 3. 前端（生产构建）

```bash
cd frontend
npm run build
```

构建产物输出到 `frontend/dist/`。

### 4. 生产部署（YAML 配置）

生产环境复制 [toolhive.example.yaml](./tool-hive/toolhive.example.yaml) 为配置文件，并通过 `TOOLHIVE_CONFIG_FILE` 指定（如 `config/production.yaml`）。完整的生产部署、配置校验与验收步骤见 [deploy/README.md](./deploy/README.md)。

### 5. 生产网关（Nginx）

生产环境后端只监听回环地址，必须由 Nginx 转发，配置示例见 [deploy/nginx/toolhive.conf](./deploy/nginx/toolhive.conf)：管理入口走公网 443，运行入口仅内网 8081，并负责清洗客户端伪造的 Header、写入可信入口标识与真实客户端 IP。

## License

Apache License 2.0

## 一期范围补充说明（2026-08-27）

- “凭据引用”属二期能力：一期不代持目标系统凭据、不引入 `credential_ref` 与 Secret Store。
- 一期首批工具为内置数学计算占位工具（`builtin` Provider），用于打通端到端链路；后续真实外部 HTTP 工具按已审核固定映射接入（详见 docs/功能架构梳理/一期下半设计冻结.md）。
