<h1 align="center">ToolHive</h1>

<p align="center">
  A unified, policy-governed tool platform for AI agents and service callers
</p>

<p align="center">
  <a href="tool-hive/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/Docs-中文-red" alt="Chinese Docs"></a>
  <a href="docs/一期功能/验收报告/一期验收报告.md"><img src="https://img.shields.io/badge/Phase%201-Passed-brightgreen" alt="Phase 1 Acceptance"></a>
</p>

ToolHive is a unified tool platform for agents, business systems, and other service callers. External capabilities are registered as governed tools. Before execution, ToolHive authenticates the caller, evaluates tool-call policy, validates arguments, and executes approved requests, so an LLM/agent decides *what to call* without touching target URLs, HTTP methods, or credentials.

> Status: Phase 1 is complete and accepted (2026-09-02). See the [Phase 1 acceptance report](docs/一期功能/验收报告/一期验收报告.md).

## Key Features

- **Central tool catalog**: providers, tools, versions, and capability packs are managed centrally; tool versions must be reviewed and published before use, and the default version is unique and strictly authoritative for default resolution.
- **Separated admin and runtime**: the admin entry (`/admin/**`, `/api/admin/**`) and the runtime entry (`/api/runtime/v1/**`) use different identity systems and are isolated from each other.
- **Runtime security chain**: caller-system status, IP rules, and public-key signatures (RSA-PSS-SHA256, Ed25519) are validated per request, with timestamp windows and Nonce replay protection; QPS, concurrency, daily quota, total timeout, and circuit breaking are enforced.
- **Context-aware discovery and revalidation**: Discover/Resolve only return tools allowed in the current context; Execute revalidates real arguments, tool state, scope, and high-risk/write confirmation.
- **Controlled Provider execution**: built-in and HTTP providers execute only reviewed fixed mappings, with SSRF/private-network protection, TLS, timeout/size/header limits, output-schema validation, and error normalization.
- **Traceable governance**: management audit and runtime traces are linked; confirmation tokens are bound to caller, tool, and version and consumed atomically.

## Tech Stack

| Module | Technology |
| --- | --- |
| Backend | Python 3.11.6 · FastAPI · Uvicorn · SQLAlchemy (async) |
| Storage | PostgreSQL · Redis · Chroma (embedded) |
| Frontend | React 18 · TypeScript · Vite · Ant Design |
| Gateway | Nginx |

## Repository Layout

```text
toolhive/
├── tool-hive/    # Backend service (FastAPI app, CLI, tests, deployment scripts)
├── frontend/     # Admin frontend (React + Vite, served under /admin/)
├── deploy/       # Nginx gateway sample and deployment guide
└── docs/         # Requirements, frozen design, development notes, acceptance reports
```

## Quick Start

Requirements: Linux (production on the same host as Nginx) · CPython 3.11.6 (`>=3.11.6,<3.12`) · PostgreSQL · Redis; Node.js 18+ for frontend development.

```bash
cd tool-hive

# Install dependencies (creates .venv and installs toolhive)
bash scripts/install.sh

# Prepare local configuration (database/Redis connections)
cp .env.example .env

# Create the database, then initialize the schema
psql "postgresql://toolhive:<password>@localhost:5432/toolhive" -f sql/init.sql

# Initialize the first super admin (empty database only)
TOOLHIVE_INIT_ADMIN_PASSWORD='<strong password>' \
  ./.venv/bin/toolhive init-admin --account admin --real-name '<real name>'

# Seed the first-batch math tools (idempotent: create tool → version+binding → review → publish)
./.venv/bin/toolhive seed-tools

# Start the service (listens on 127.0.0.1:8100)
./.venv/bin/uvicorn toolhive.main:app --host 127.0.0.1 --port 8100

# Basic verification
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

On Windows PowerShell, use `Copy-Item .env.example .env` and the `toolhive` CLI (or `python -m toolhive.cli`) with equivalent commands; run `verify.sh` under Git Bash/WSL.

## Frontend Development & Build

```bash
cd frontend
npm install
npm run dev      # open http://localhost:5173/admin/
```

The dev server proxies `/api` to `http://127.0.0.1:8100`. Production build:

```bash
cd frontend
npm run build    # outputs to frontend/dist/
```

In production, Nginx serves `frontend/dist` under `/admin/**`. See [deploy/README.md](deploy/README.md) and the [Nginx sample](deploy/nginx/toolhive.conf).

## Documentation

- [Overall functionality & architecture](docs/ToolHive总体功能与架构说明.md)
- Phase 1: [goals](docs/一期功能/一期目标.md) · [frozen design](docs/一期功能/一期下半设计冻结.md) · [development notes](docs/一期功能/一期开发完成情况.md) · [acceptance report](docs/一期功能/验收报告/一期验收报告.md)
- Phase 2: [goals](docs/二期功能/二期目标.md)
- Deployment: [deploy/README.md](deploy/README.md)

## Phase 1 Boundary & Phase 2 Direction

Confirmed Phase 1 boundaries:

- No target-system credential holding; no Secret Store or `credential_ref`;
- The first batch of tools are built-in math placeholder tools (`builtin` Provider) that validate the end-to-end chain;
- ToolContext uses the caller-declared model; tenant/business-identity filtering belongs to Phase 2;
- DNS resolution pinning (fixed IP + bound connection) and multi-instance shared concurrency are designed for Phase 2;
- HTTP `response_handling` is descriptive metadata in Phase 1; rule-based response sanitization belongs to Phase 2.

## License

[Apache License 2.0](tool-hive/LICENSE)
