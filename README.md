<h1 align="center">Toolbelt</h1>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="Apache 2.0"></a>
  <a href="./README.en.md"><img src="https://img.shields.io/badge/docs-English-blue" alt="English Docs"></a>
</p>

<p align="center">
  <b>安全的 AI Agent 工具执行网关</b><br/>
  统一管理工具、拦截越权调用、防止 LLM 直接触碰网络与密钥
</p>

---

## 为什么需要 Toolbelt

大语言模型在使用工具（Function Calling）时，天然面临几个风险：

- 🔓 **Prompt Injection**：恶意指令诱导模型调用不该用的接口
- 🌐 **SSRF**：模型被诱导生成内网地址或任意 URL
- 🔑 **凭证泄露**：API Key 被塞进返回内容或日志
- 📦 **权限混乱**：一个工具被所有用户无差别使用

Toolbelt 作为一个**中间层网关**，把这些风险挡在模型之外：

> Agent 只拿到「允许看到的工具」，  
> 工具只调用「预先审核好的接口」，  
> 网络请求从不由 LLM 决定。

---

## 核心能力

- 🛡 **策略鉴权（Policy Engine）**  
  调用前校验用户身份、资源归属和操作风险，拒绝非法请求。
- 📚 **工具目录（Tool Catalog）**  
  支持版本化工具定义，变更可追溯。
- 🔍 **语义检索**  
  根据用户意图自动召回相关工具，避免把上百个工具全部塞给模型。
- 🔌 **多协议适配**  
  内置 HTTP 适配器，预留 MCP、gRPC 扩展能力。
- 📊 **全链路审计**  
  每一次工具调用都有 Trace，便于排查和合规。

---

## 架构示意
