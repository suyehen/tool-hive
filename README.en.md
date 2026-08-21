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
├── tool-hive/    # Backend service (FastAPI app, CLI, deploy scripts)
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

### 1. Local development (.env)

Copy [.env.example](./tool-hive/.env.example) to `tool-hive/.env` and edit database/Redis connections (IP/port/password). `.env` supports all settings, including nested groups (`network`, `chroma`, etc.). For local development, set `TOOLHIVE_DEBUG=true` and `TOOLHIVE_NETWORK_ALLOW_LOOPBACK_DIRECT=true` (the Vite dev proxy does not send ingress headers).

On first deployment, create the application user and database on the server with the PostgreSQL superuser first (template: [sql/create_database.sql](./tool-hive/sql/create_database.sql)), then run the schema steps below. Order: create database → create tables.

```bash
cd tool-hive

# Install dependencies (creates .venv and installs toolhive)
bash scripts/install.sh

# Prepare local config
cp .env.example .env

# Initialize the database: schema (database created by create_database.sql; connection from .env)
psql "postgresql://toolhive:<password>@localhost:5432/toolhive" -f sql/init.sql

# Initialize the first super admin (only on an empty database)
TOOLHIVE_INIT_ADMIN_PASSWORD='<strong password>' \
  ./.venv/bin/toolhive init-admin --username admin

# Start the service (listens on 127.0.0.1:8100, loads .env automatically)
./.venv/bin/uvicorn toolhive.main:app --host 127.0.0.1 --port 8100

# Verify
BASE_URL=http://127.0.0.1:8100 bash scripts/verify.sh
```

On Windows you can start with `python -m uvicorn toolhive.main:app --host 127.0.0.1 --port 8100` (after activating your Python environment). Settings precedence: real environment variables > external YAML > `.env` file > defaults; all fields are documented in [.env.example](./tool-hive/.env.example) and [toolhive.example.yaml](./tool-hive/toolhive.example.yaml).

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

### 4. Production deployment (YAML)

In production, copy [toolhive.example.yaml](./tool-hive/toolhive.example.yaml) as the configuration file and point `TOOLHIVE_CONFIG_FILE` to it (e.g., `config/production.yaml`). See [deploy/README.md](./deploy/README.md) for the full production deployment, configuration validation, and acceptance steps.

### 5. Production gateway (Nginx)

In production the backend listens on loopback only and must be fronted by Nginx. See [deploy/nginx/toolhive.conf](./deploy/nginx/toolhive.conf): the management entry is exposed on public port 443, the runtime entry on internal port 8081 only, with client-supplied headers stripped and trusted ingress/client-IP headers written by Nginx.

## License

Apache License 2.0
