<h1 align="center">Toolbelt</h1>

<p align="center">
  A secure tool execution gateway for AI agents.<br/>
  Centralized registry, policy-based authorization, and SSRF protection.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg"></a>
</p>

---

## Why Toolbelt?

LLMs often need to call external APIs, but giving them direct control over HTTP requests is dangerous:

- Prompt injection can trigger unintended actions
- Models may leak credentials or generate arbitrary URLs

Toolbelt solves this by acting as a **trusted execution layer**:

- The **LLM only sees tool names and schemas**
- **URLs, methods, and credentials are pre-registered**
- Every call is authorized by a backend policy engine

---

## Features

- Declarative tool definitions (versioned)
- Semantic retrieval: find relevant tools per user intent
- Built-in HTTP provider (MCP & gRPC coming soon)
- Fine-grained capability-based authorization
- Full audit trails for every invocation

---

## Quick Example

Define a tool:
