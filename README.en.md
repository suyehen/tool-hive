<h1 align="center">ToolHive</h1>

<p align="center">
  <a href="tool-hive/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="README.md"><img src="https://img.shields.io/badge/docs-中文-red" alt="Chinese Docs"></a>
</p>

<p align="center">
  A managed tool hive for AI agents.<br/>
  Centralize tools, enforce policy, and execute safely without exposing networks or secrets to the LLM.
</p>

---

## Overview

ToolHive is a unified tool platform for agents, business systems, and other service callers. External capabilities are registered as governed tools; before execution, ToolHive authenticates callers, evaluates tool-call policy, validates arguments, and executes approved requests. Callers can only use the tools ToolHive makes discoverable in the current context, and cannot choose target URLs, HTTP methods, authentication headers, or platform-managed credentials.

Core capabilities:

- Central tool catalog: Providers, tools, versions, and capability bundles are managed centrally; only reviewed and published definitions can be called.
- Management and runtime separation: the management entry (`/admin/**`, `/api/admin/**`) and the runtime entry (`/api/runtime/**`) use distinct identities and authentication, isolated from each other.
- Context-aware discovery and revalidation: execution re-checks real arguments, resource scope, and high-risk actions.
- Controlled Provider execution: Providers call external services through approved fixed request mappings, with credential references, timeouts, error normalization, and response sanitization.
- Traceable governance: management changes, authentication, authorization decisions, and execution retain necessary redacted trace/audit records.

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
├── tool-hive/    # Backend service (FastAPI app, SQL migrations, CLI, deploy scripts)
├── frontend/     # Admin frontend (React + Vite)
├── deploy/       # Deployment assets (Nginx gateway sample, deployment doc)
└── docs/         # Architecture and requirements docs
```

## Requirements

- Linux (production: deploy on the same host as Nginx)
- CPython 3.11.6 (`>=3.11.6,<3.12`)
- PostgreSQL and Redis
- Node.js 18+ (only needed for frontend development and builds)

## Deployment & Startup

### 1. Backend

```bash
cd tool-hive

# Install dependencies (creates .venv and installs toolhive)
bash scripts/install.sh

# Prepare the configuration file (edit DB, Redis, secrets as needed)
cp toolhive.example.yaml config/production.yaml

# Initialize the database: baseline schema + incremental migrations
psql "$DATABASE_URL" -f sql/init.sql
./.venv/bin/toolhive db-migrate --config config/production.yaml

# Initialize the first super admin (only on an empty database)
TOOLHIVE_INIT_ADMIN_PASSWORD='<strong password>' \
  ./.venv/bin/toolhive init-admin --username admin --config config/production.yaml

# Start the service (listens on 127.0.0.1:8100)
TOOLHIVE_CONFIG_FILE=config/production.yaml bash scripts/start.sh

# Verify
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

All settings are documented in [toolhive.example.yaml](./tool-hive/toolhive.example.yaml); they can also be overridden with environment variables (see [.env.example](./tool-hive/.env.example)).

### 2. Frontend (development)

```bash
cd frontend
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` and proxies `/api` to `http://127.0.0.1:8100`.

### 3. Frontend (production build)

```bash
cd frontend
npm run build
```

Build output goes to `frontend/dist/`.

### 4. Production gateway (Nginx)

In production the backend listens on loopback only and must be fronted by Nginx. See [deploy/nginx/toolhive.conf](./deploy/nginx/toolhive.conf): the management entry is exposed on public port 443, the runtime entry on internal port 8081 only, with client-supplied headers stripped and trusted ingress/client-IP headers written by Nginx.

See [deploy/README.md](./deploy/README.md) for the full production deployment, configuration validation, and acceptance steps.

## License

Apache License 2.0
