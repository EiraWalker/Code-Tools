# 创建自己的插件

## ChatGPT：私有 Sites MCP 网关

这条路线需要账户实际具有 Sites MCP 和插件创建能力。它不是所有聊天宿主都自动具备的功能。

1. 让 Agent 阅读当前安装版本的 Sites / Plugin Creator 技能。
2. 创建一个新的 owner-private Sites 项目，用 Worker ESM 模板。保留返回的 project ID。
3. 将 `gateway/worker/index.js` 放进该项目，项目 title 设为 Codebase Graph Reader。用当前 Sites 构建工作流保留构建集成；不要将示例 project ID 当成真实 ID。
4. 将 `gateway/hosting.example.json` 的字段合并到真实 `.openai/hosting.json`，使用平台返回的项目 ID；声明 `capabilities: ["mcp"]`。
5. 设置 `CBM_ENGINE_ORIGIN` 为你自己的实际 Render HTTPS origin，`CBM_SERVICE_TOKEN` 为匹配的服务端秘密变量。
6. 构建、检查、同步 source、部署 private 版本。保留 audience，不改成公开图谱服务。
7. 获取真实 `mcp_connection`。Sites 会生成 canonical App 和唯一的私有 Codebase Graph Reader 插件，直接复用。
8. 安装/连接后执行实际只读工具调用。确认公开发现仅提供 schema，私人数据调用要求正确身份。

Workers 不支持 `redirect: "error"`。这里使用 `manual` 并拒绝 3xx；也不允许客户端自选目标 origin。

网关可以接受固定服务密钥作为 operator/server 认证，但它仍必须位于 Sites 私有访问边界后面。不要伪造可信身份头绕过 OAuth。

## 一个插件，同时提供工具与指令

唯一入口名称为 **Codebase Graph Reader**。Render 引擎是后台服务，不是另一个需要用户安装的插件。Sites 项目 title 使用此名称，保留已有 canonical App/plugin 身份与 OAuth 连接。

网关在 MCP `initialize` 返回 `instructions`，在 `tools/list` 的每个工具说明中补充相应工作流。直接连接 Render 的客户端也由 Python Server 提供同一指令。部分宿主不会显示初始化指令，因此工具说明也包含引导。

工作流是：先 `list_projects` 核对项目与快照来源，再 `get_architecture`；通过 `search_graph` 找到真实限定名后调用 `trace_path`，需要关系或计数时使用只读 `query_graph`。保留错误、分页、截断和快照来源。

这是 MCP 使用指令，不是往 canonical App 中追加 SKILL 文件。Sites canonical App 不支持普通 Plugin Creator archive editor；不要创建第二个包来绕开它。本模板不再提供额外的 skills-only ZIP。

旧版本用户：先更新并验证 canonical 连接，再移除已被替代的旧指令插件。不要删除承载 OAuth 和工具的连接。卸载操作需要用户明确指定旧插件；迁移文档不授予 Agent 擅自删除账户资源的权限。

## 其他 MCP 客户端

后端提供 HTTPS Streamable HTTP `/mcp`，需要 `Authorization: Bearer` 服务认证。只在客户端明确支持秘密请求头时使用该连接方式。

若客户端或 ChatGPT 要求 OAuth，需要符合宿主要求的认证实现。静态 Bearer 是服务认证，不等于 OAuth；请按 [MCP Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) 实现。

`mcp.json` 的 transport/url 可以按客户端规范配置，但不要把长期 token 提交进去。宿主端秘密存储、OAuth 配置和本地环境变量能力必须逐项确认。

新增 GitHub 图谱时，在同一 MCP 连接调用 `add_index`；它是经过授权的目录修改，不是只读查询。发现结果须包含此接口及五个原生查询工具。不要另建 Reader Engine 插件或为每个项目建独立 App。详见 [多索引使用方法](multiple-indexes.md)。
