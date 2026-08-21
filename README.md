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
├── tool-hive/    # 后端服务（FastAPI 应用、SQL 迁移、CLI、部署脚本）
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

### 1. 后端

```bash
cd tool-hive

# 安装依赖（创建 .venv 虚拟环境并安装 toolhive）
bash scripts/install.sh

# 准备配置文件（按需修改数据库、Redis、密钥等）
cp toolhive.example.yaml config/production.yaml

# 数据库初始化：基线建表 + 增量迁移
psql "$DATABASE_URL" -f sql/init.sql
./.venv/bin/toolhive db-migrate --config config/production.yaml

# 初始化首个超级管理员（仅空库可执行，密码建议用环境变量传入）
TOOLHIVE_INIT_ADMIN_PASSWORD='<强密码>' \
  ./.venv/bin/toolhive init-admin --username admin --config config/production.yaml

# 启动（监听 127.0.0.1:8100）
TOOLHIVE_CONFIG_FILE=config/production.yaml bash scripts/start.sh

# 验证服务
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

配置字段说明见 [toolhive.example.yaml](./tool-hive/toolhive.example.yaml)，也可通过环境变量覆盖（参考 [.env.example](./tool-hive/.env.example)）。

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

### 4. 生产网关（Nginx）

生产环境后端只监听回环地址，必须由 Nginx 转发，配置示例见 [deploy/nginx/toolhive.conf](./deploy/nginx/toolhive.conf)：管理入口走公网 443，运行入口仅内网 8081，并负责清洗客户端伪造的 Header、写入可信入口标识与真实客户端 IP。

完整的生产部署、配置校验与验收步骤见 [deploy/README.md](./deploy/README.md)。

## License

Apache License 2.0
