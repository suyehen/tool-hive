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

## Product Overview

ToolHive is a unified tool platform for agents, business systems, and other service callers. It registers external capabilities as governed tools, then authenticates callers, evaluates tool-call policy, validates arguments, and executes approved requests.

Callers and LLMs can use only the tools ToolHive makes discoverable in the current context. They cannot choose target URLs, HTTP methods, authentication headers, or platform-managed credentials. External business systems remain responsible for their own data authorization and business-rule validation.

## One Application, Clear Boundaries

ToolHive is **one application, one release unit, and one lifecycle unit**. Its management module and tool application module live in the same ToolHive backend and are deployed, started, stopped, and upgraded together. They are not independently deployed or independently operated backend systems.

- **Management module**: `/admin/**` and `/api/admin/**` provide management accounts, roles, caller-system configuration, and tool-catalog administration.
- **Tool application module**: `/api/runtime/**` lets caller systems discover tools, obtain authorization decisions, and execute tools.
- **Access separation**: the two entries use different routes, identities, authentication methods, and control rules. Management accounts cannot invoke tools merely through their administrative role, and caller credentials cannot access management APIs.

```text
Administrator browser                           Caller system / Agent
        │                                                   │
        └──────────── HTTPS ───────┬── Internal HTTPS + signed request ──┘
                                   ▼
                      ┌────────────────────────────┐
                      │      Nginx / security gateway│
                      │ entry protection and routing │
                      └──────────────┬─────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│         One ToolHive backend application: one deployment and lifecycle │
│  Management: accounts, roles, caller systems, and Catalog management  │
│  Tool application: caller auth, discovery, policy, Provider, and Trace│
│  Shared domain: Catalog · Policy · Provider · Audit · configuration     │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ Controlled egress
                                   ▼
                         ┌─────────────────────┐
                         │ External systems/API│
                         └─────────────────────┘
```

## Core Capabilities

- **Central tool catalog**: Providers, tools, tool versions, and capability bundles describe external capabilities; only reviewed and published definitions are callable.
- **Management and caller boundaries**: management accounts configure the platform, while caller systems use separate identities for runtime APIs.
- **Context-aware discovery and revalidation**: ToolHive returns only tools visible to the current caller and context, then rechecks actual arguments, resource scope, and high-risk actions before execution.
- **Controlled Provider execution**: Providers use approved fixed request mappings and handle credential references, timeouts, error normalization, response sanitization, and egress controls.
- **Traceable governance**: management changes, authentication, policy decisions, retrieval, and execution retain necessary redacted trace or audit records.

## Delivery Phases

### Phase 1: Controlled HTTP Tool-Call Loop

Phase 1 delivers the minimum closed loop from management configuration to governed HTTP execution:

- management accounts, MFA, sessions, administrative roles, and operation permissions;
- caller systems, public keys, source-IP rules, capability bundles, Providers, tools, versions, review, and publication;
- signed caller requests, replay protection, tool-call scope, Discover / Execute, JSON Schema validation, and high-risk confirmation;
- fixed HTTP mappings, credential isolation, SSRF protection, timeout/retry/idempotency controls, and foundational Trace and audit records.

### Phase 2: Protocol, Governance, and Scale

After the Phase 1 loop is stable and validated in real use, Phase 2 extends ToolHive with:

- enterprise identity integration such as SSO, OIDC, SAML, or enterprise-specific protocols;
- MCP Providers, an MCP Registry / gateway, gRPC Providers, and other approved protocol adapters;
- host-tool and high-risk capability governance, asynchronous jobs, callbacks, cancellation, and dead-letter handling;
- advanced release governance, gradual rollout, rollback, retrieval-quality evaluation, cost, and quota governance;
- monitoring and alerts, audit reporting, compliance controls, multi-instance deployment, capacity management, and disaster recovery.

## Typical Call Flow

```text
Administrator configures caller systems and tools
  → Tool version is reviewed and published
  → Caller system sends a signed request with its own credentials
  → ToolHive validates source, identity, replay protection, and tool-call scope
  → Discover returns tools allowed in the current context
  → Execute revalidates actual arguments and risk conditions
  → Provider calls an external API through its fixed mapping
  → ToolHive returns a normalized result and writes redacted Trace / audit records
```

## Security Principles

- **Deny by default**: reject unauthenticated, unauthorized, unconfigured, or security-dependency-failed requests.
- **Fixed execution mappings**: an LLM cannot create arbitrary URLs, methods, headers, credentials, or undeclared arguments.
- **Identity isolation**: management sessions, caller authentication material, and Provider credentials are separated and kept out of ordinary logs and model context.
- **Two-stage control**: being discoverable does not imply being executable; execution is re-evaluated against real arguments, business context, and risk requirements.
- **Controlled egress and traceability**: restrict destinations and network egress, sanitize sensitive results, and retain redacted records.

## Documentation

- [Architecture documentation index](./docs/功能架构梳理/README.md)
- [Overall function and architecture](./docs/功能架构梳理/ToolHive总体功能与架构说明.md)
- [Phase 1 goals](./docs/功能架构梳理/一期目标.md)
- [Phase 2 goals](./docs/功能架构梳理/二期目标.md)
- [Phase 1 implementation status](./docs/功能架构梳理/一期开发完成情况.md)

This README describes the finished product and its phased delivery scope. The current implementation state is maintained separately in the Phase 1 implementation-status document.

## License

Apache License 2.0
