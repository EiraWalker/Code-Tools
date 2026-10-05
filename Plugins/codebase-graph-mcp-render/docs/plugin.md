# 创建自己的插件

## ChatGPT：私有 Sites MCP 网关

这条路线需要账户实际具有 Sites MCP 和插件创建能力。它不是所有聊天宿主都自动具备的功能。

1. 让 Agent 阅读当前安装版本的 Sites / Plugin Creator 技能。
2. 创建一个新的 owner-private Sites 项目，用 Worker ESM 模板。保留返回的 project ID。
3. 将 `gateway/worker/index.js` 放进该项目。用当前 Sites 构建工作流保留构建集成；不要将示例 project ID 当成真实 ID。
4. 将 `gateway/hosting.example.json` 的字段合并到真实 `.openai/hosting.json`，使用平台返回的项目 ID；声明 `capabilities: ["mcp"]`。
5. 设置 `CBM_ENGINE_ORIGIN` 为你自己的实际 Render HTTPS origin，`CBM_SERVICE_TOKEN` 为匹配的服务端秘密变量。
6. 构建、检查、同步 source、部署 private 版本。保留 audience，不改成公开图谱服务。
7. 获取真实 `mcp_connection`。Sites 会生成 canonical App 和私有 Engine 插件，直接复用。
8. 安装/连接后执行实际只读工具调用。确认公开发现仅提供 schema，私人数据调用要求正确身份。

Workers 不支持 `redirect: "error"`。这里使用 `manual` 并拒绝 3xx；也不允许客户端自选目标 origin。

网关可以接受固定服务密钥作为 operator/server 认证，但它仍必须位于 Sites 私有访问边界后面。不要伪造可信身份头绕过 OAuth。

## 可选的指令插件

`plugin-template/` 是 skills-only 包。它指导 Agent 使用已连接的 Engine，没有包含本地 executable、服务凭据或伪造的连接 ID。

```bash
python scripts/package_plugin.py /absolute/path/outside-template/my-graph-reader.zip
```

使用当前 Plugin Creator 的创建接口上传 ZIP，保留返回的 plugin/release ID。若平台返回了 Engine 的真实 App ID，可按平台规范声明依赖；不能把 plugin ID 当成 App ID。

无需额外指令插件也可直接调用 canonical Engine。不要把 Sites canonical plugin 再包装成重复的 MCP App。

## 其他 MCP 客户端

后端提供 HTTPS Streamable HTTP `/mcp`，需要 `Authorization: Bearer` 服务认证。只在客户端明确支持秘密请求头时使用该连接方式。

若客户端或 ChatGPT 要求 OAuth，需要符合宿主要求的认证实现。静态 Bearer 是服务认证，不等于 OAuth；请按 [MCP Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) 实现。

`mcp.json` 的 transport/url 可以按客户端规范配置，但不要把长期 token 提交进去。宿主端秘密存储、OAuth 配置和本地环境变量能力必须逐项确认。
