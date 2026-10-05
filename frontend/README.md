# ToolHive 管理台界面（Frontend）

> **状态：M0 不实现。** 本目录是 M1 的交付物，现在只占位 + 记录约定。
> 设计依据：§12 技术选型（`React + Vite`）、§16.2（M0 管理面**只有 CLI**）、§16.3 M1。

## 仓库结构：后端与前端的划分

```
toolhive/
├── backend/          # Python 后端（整个 Python 工程）
│   ├── src/toolhive/
│   │   ├── core/            领域与内核
│   │   ├── retrieval/       检索
│   │   ├── ingestion/       接入管线
│   │   ├── adapters/        db / cache / secrets / upstream / id
│   │   ├── protocols/       ← 协议适配器（REST / MCP / 管理 API），**后端代码**
│   │   ├── observability/
│   │   └── builtin_tools/
│   ├── tests/architecture/  架构断言
│   ├── eval/                检索效果验证
│   ├── alembic/             迁移
│   ├── scripts/             手动验证脚本
│   ├── pyproject.toml
│   └── .env                 后端环境变量（不入库）
├── frontend/         # ← 本目录：管理台界面（TypeScript + React）
└── docs/             # 设计与部署文档（跨前后端）
```

## ⚠️ 别把 `backend/.../protocols/` 和 `frontend/` 搞混

这是本仓库最容易混的一点，所以放在最前面。

| 说法 | 位置 | 是什么 | 语言 | 阶段 |
|---|---|---|---|---|
| **协议适配器**（设计里叫「协议前端」） | `backend/src/toolhive/protocols/` 下的 `rest/` `mcp/` `admin/` | 把外部协议翻译成内核调用——**是后端代码** | Python | REST 在 M0；MCP 与管理 API 在 M1 |
| **管理台界面** | **`frontend/`（本目录）** | 人在浏览器里点的界面 | TypeScript + React + Vite | **M1** |

设计 §3.3 说的"协议前端必须是薄适配器"、§14.1 第 2/3 条约束的"`adapters/` 不得反向依赖
`protocols/`""`protocols/` 之间不得互相 import"——**说的都是上表第一行**。

该目录原先叫 `frontends/`，与 `frontend/` 只差一个字母，故已改名为 `protocols/`。

**本目录不受那些架构断言约束**：与 Python 侧只通过 HTTP 接口契约耦合，不共享代码。

## M0 为什么是空的

设计 §16.2 的 M0 范围决策写得很明确：

> **管理面形态**：**只用 CLI**，不做管理 HTTP API、不做管理前端。

理由（§16.2 原文）是省掉会话 / CSRF / 验证码 / 操作码一整套，代价是 M0 只能命令行操作。
所以 M0 期间：

* 管理操作走 `backend/src/toolhive/cli/`（任务 J）
* 调用方接口走 `backend/src/toolhive/protocols/rest/`（任务 I）
* **没有任何浏览器界面**，也不需要 Node.js 参与构建

## M1 要建什么

设计 §16.3 的 M1 清单里有两项，它们是一对：

1. **管理 HTTP API**（`backend/src/toolhive/protocols/admin/`）—— 给界面用的后端接口
2. **管理前端**（本目录）—— 目录、授权、配额、审计四个视图

**顺序上先有 1 才有 2**：M0 的管理能力全是 CLI 子命令，M1 先把它们暴露成 HTTP 接口，
界面才有东西可调。**不要让界面直连数据库。**

## 环境准备（M1 开工时再看）

本机已装 Node.js v24.17.0、npm 11.13.0；**pnpm 未安装**（若本工程用 pnpm，
需 `npm i -g pnpm` 或 `corepack enable pnpm`）。详见 `docs/04-部署前置条件` §6。

## 目录约定（M1 建立时遵循）

```
frontend/
├── src/
│   ├── api/          # 对管理 API 的封装（接口契约的唯一出口）
│   ├── pages/        # 四个视图：目录 / 授权 / 配额 / 审计
│   └── components/
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

**约定**：`src/api/` 是**唯一**直接发 HTTP 请求的地方。视图层不自己拼 URL——
这样接口变更时只需要改一处，也不会出现"某个页面忘了带认证头"这类问题。
