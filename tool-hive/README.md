<h1 align="center">ToolHive</h1>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"></a>
  <a href="./README.en.md"><img src="https://img.shields.io/badge/docs-English-blue" alt="English Docs"></a>
</p>

<p align="center">
  <b>Agent 的工具蜂巢</b><br/>
  统一托管、策略鉴权、安全执行，让 LLM 只负责思考，不动手碰网络。
</p>

---

## 为什么需要 ToolHive

当你给 AI Agent 接外部系统时，通常会遇到：

- 🔓 Prompt Injection 诱导模型调用敏感接口
- 🌐 模型尝试访问任意 URL（SSRF 风险）
- 🔑 API Key 意外出现在回复或日志里
- 📦 所有用户共享同一套工具，缺乏权限隔离

ToolHive 作为 Agent 和外部能力之间的**中间层网关**，把工具聚合成一个受控的「蜂巢」：

> Agent 只能看到被授权的工具清单，
> 真正的网络请求由 ToolHive 按预定义模板执行，
> 模型永远拿不到 URL、Header 和凭据。

## 核心特性

- 📚 **集中目录**：所有工具版本化注册，单一事实来源
- 🛡 **策略引擎**：调用前鉴权，拒绝越权、高风险操作
- 🔍 **智能召回**：根据用户意图自动筛选最相关的工具，避免塞爆上下文
- 🔌 **多协议适配**：内置 HTTP，预留 MCP / gRPC 扩展
- 📊 **全链路审计**：每次调用可追溯、可观测

## 架构示意

```
┌──────────┐    tool_name + args    ┌────────────┐
│   Agent  │ ────────────────────▶ │  ToolHive   │
└──────────┘                       └─────┬────────┘
                                        │ 校验身份 / 参数 / 权限
                                        ▼
                                ┌───────────────┐
                                │    Provider    │
                                │  HTTP / MCP …  │
                                └───────┬───────┘
                                        │ 固定端点，无动态拼接
                                        ▼
                                ┌───────────────┐
                                │  业务系统 API   │
                                └───────────────┘
```

## 快速体验

### 注册一个工具

通过管理接口定义一个订单查询工具：

```bash
curl -X POST https://tools.example.com/api/v1/tools \
  -H "Content-Type: application/json" \
  -d '{
    "name": "order_query",
    "description": "根据订单号查询订单详情",
    "input_schema": {
      "order_id": { "type": "string" }
    },
    "provider": {
      "type": "http",
      "method": "GET",
      "url_template": "/orders/{order_id}",
      "credential_ref": "order-service"
    }
  }'
```

### Agent 调用

Agent 只需提交工具名和参数：

```json
{
  "tool": "order_query",
  "arguments": { "order_id": "ORD123" }
}
```

ToolHive 会自动完成鉴权、填参、注入凭据，并把清洗后的结果返回给 Agent。

## 安全原则

- ✅ **模型不知道调用地址**：URL 由管理员预配置
- ✅ **模型不能发明工具**：只能从服务端下发的列表中选择
- ✅ **凭据零泄漏**：只存引用，不进代码、不进日志
- ✅ **出口白名单**：防止内网探测和 SSRF

## 开发状态

ToolHive 正在活跃开发中，当前阶段聚焦于 HTTP 工具接入与基础策略模型。

更详细的设计文档见 [architecture.md](./docs/architecture.md)。

## License

Apache License 2.0
