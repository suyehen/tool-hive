<h1 align="center">ToolHive</h1>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="./README.md"><img src="https://img.shields.io/badge/docs-中文-red" alt="中文文档"></a>
</p>

<p align="center">
  A secure tool registry and execution gateway for AI agents.<br/>
  Let the LLM reason, not reach the network.
</p>

---

## Why ToolHive?

Connecting LLMs to APIs introduces risks:

- Prompt injection can trigger unintended actions
- LLMs might attempt to access arbitrary URLs (SSRF)
- Credentials can leak into outputs or traces
- No built-in concept of user-scoped permissions

ToolHive acts as a trusted middleware. Think of it as a **hive** where all external capabilities live under management:

> Agents receive only the tools they're allowed to see.
> Network requests are made via pre-approved templates.
> The model never sees URLs, headers, or secrets.

## Features

- **Central Registry**: Versioned tool definitions in one place
- **Policy Engine**: Enforces identity, scope, and risk before any call
- **Intent-aware Retrieval**: Returns only relevant tools to the agent
- **Pluggable Providers**: HTTP built-in; MCP and gRPC on the roadmap
- **Audit Trails**: Full visibility into what was called and why

## How it works

```
Agent ──▶ ToolHive ──▶ Provider ──▶ Your Backend
```

1. Agent sends user context + tool arguments
2. ToolHive resolves which tools are permitted
3. Provider executes a fixed, pre-configured request
4. Result is normalized and returned

## Quick Example

Define a tool:

```json
{
  "name": "get_weather",
  "input": { "city": "string" },
  "provider": {
    "type": "http",
    "endpoint": "https://api.weather.internal/{city}",
    "credential_ref": "weather-api"
  }
}
```

Agent invokes:

```json
{ "tool": "get_weather", "arguments": { "city": "Beijing" } }
```

That's it. No URLs or tokens ever touch the model.

## Security

- No dynamic URL construction from LLM output
- No raw secrets in logs or responses
- Egress restricted to allowlisted destinations
- Immutable tool versions

## Documentation

See [Architecture](docs/architecture.md) for internals.

## License

Apache 2.0
