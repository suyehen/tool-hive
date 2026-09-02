<h1 align="center">ToolHive</h1>

<p align="center">
  Agent 的统一工具托管平台 —— 集中登记、策略授权、安全执行
</p>

<p align="center">
  <a href="tool-hive/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/Docs-English-blue" alt="English Docs"></a>
  <a href="docs/一期功能/验收报告/一期验收报告.md"><img src="https://img.shields.io/badge/Phase%201-Passed-brightgreen" alt="Phase 1 Acceptance"></a>
</p>

ToolHive 是面向 Agent、业务系统及其他服务调用方的统一工具平台。平台把外部系统能力登记为受控工具，在调用前完成调用方认证、工具调用控制、参数校验与受控执行，让 LLM/Agent 只负责“决定调用什么”，不直接接触目标地址、HTTP 方法与凭据。

> 状态：一期功能已完成并通过验收（2026-09-02），见 [一期验收报告](docs/一期功能/验收报告/一期验收报告.md)。

## 主要能力

- **统一工具目录**：Provider、工具、版本与能力包集中登记；工具版本经审核、发布后才能被调用；默认版本唯一且严格参与默认解析。
- **管理与运行分离**：管理入口 `/admin/**`、`/api/admin/**` 与运行入口 `/api/runtime/v1/**` 使用不同身份体系，互相隔离。
- **运行时安全链**：调用系统状态/IP 规则/公钥签名（RSA-PSS-SHA256、Ed25519）实时校验，时间窗与 Nonce 防重放；QPS、并发、日配额、总超时与熔断统一生效。
- **按需发现与二次校验**：Discover/Resolve 只返回当前上下文允许的工具；Execute 对真实参数、工具状态、范围与高风险/写操作确认重新校验。
- **受控 Provider 执行**：内置与 HTTP Provider 按审核过的固定映射执行；包含 SSRF/私网防护、TLS、超时/大小/Header 限制、输出 Schema 校验与错误转换。
- **可追溯治理**：管理操作审计与运行 Trace 贯通；确认令牌绑定调用方、工具与版本并原子一次性消费。

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
├── tool-hive/    # 后端服务（FastAPI 应用、CLI、测试与部署脚本）
├── frontend/     # 管理前端（React + Vite，访问路径 /admin/）
├── deploy/       # Nginx 网关示例与部署文档
└── docs/         # 需求、设计冻结、开发记录与验收报告
```

## 快速开始

环境要求：Linux（生产与 Nginx 同机）· CPython 3.11.6（`>=3.11.6,<3.12`）· PostgreSQL · Redis；前端开发需要 Node.js 18+。

```bash
cd tool-hive

# 安装依赖（创建 .venv 并安装 toolhive）
bash scripts/install.sh

# 准备本地配置（数据库/Redis 连接）
cp .env.example .env

# 创建数据库后执行建表
psql "postgresql://toolhive:<密码>@localhost:5432/toolhive" -f sql/init.sql

# 初始化首个超级管理员（仅空库可执行）
TOOLHIVE_INIT_ADMIN_PASSWORD='<强密码>' \
  ./.venv/bin/toolhive init-admin --account admin --real-name '<姓名>'

# 接入首批数学计算工具（幂等：建工具 → 版本+绑定 → 审核 → 发布）
./.venv/bin/toolhive seed-tools

# 启动服务（监听 127.0.0.1:8100）
./.venv/bin/uvicorn toolhive.main:app --host 127.0.0.1 --port 8100

# 基础验收
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

Windows 用户使用 PowerShell 时，用 `Copy-Item .env.example .env`、`toolhive init-admin ...`（或 `python -m toolhive.cli`）执行相同步骤；`verify.sh` 建议在 Git Bash/WSL 下运行。

## 前端开发与生产构建

```bash
cd frontend
npm install
npm run dev      # 打开 http://localhost:5173/admin/
```

开发服务器将 `/api` 代理到 `http://127.0.0.1:8100`。生产构建：

```bash
cd frontend
npm run build    # 产物输出到 frontend/dist/
```

生产环境由 Nginx 托管 `frontend/dist`，统一入口为 `/admin/**`，详见 [deploy/README.md](deploy/README.md) 与 [Nginx 配置示例](deploy/nginx/toolhive.conf)。

## 文档索引

- [总体功能与架构说明](docs/ToolHive总体功能与架构说明.md)
- 一期： [一期目标](docs/一期功能/一期目标.md) · [设计冻结](docs/一期功能/一期下半设计冻结.md) · [开发完成情况](docs/一期功能/一期开发完成情况.md) · [验收报告](docs/一期功能/验收报告/一期验收报告.md)
- 二期：[二期目标](docs/二期功能/二期目标.md)
- 部署：[deploy/README.md](deploy/README.md)

## 一期边界与二期方向

一期确认边界：

- 不代持目标系统凭据，不引入 Secret Store / `credential_ref`；
- 首批工具为内置数学计算占位工具（`builtin` Provider），用于打通端到端链路；
- ToolContext 采用调用系统声明制，租户/业务身份级过滤属二期；
- 出站 DNS 校验后的“固定 IP + 绑定连接”与多实例共享并发计数按二期设计落地；
- HTTP `response_handling` 为一期描述性元数据，规则化脱敏属二期。

## License

[Apache License 2.0](tool-hive/LICENSE)
