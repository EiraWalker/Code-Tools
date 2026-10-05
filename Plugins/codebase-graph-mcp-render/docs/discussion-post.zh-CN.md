# 让聊天 Agent 直接查询代码图谱：原生 MCP + Render 后端的可复用方案

我整理了一套模板，让聊天中的 Agent 通过原生 `codebase-memory-mcp` 接口查询代码索引图谱。你可以把仓库交给自己的 Agent，让它部署 Render 后端、配置认证入口，并创建自己的插件。

最初的问题是：把原生可执行文件放进插件包，不代表聊天环境能取得并执行它。即使有 shell，插件资源也可能没有挂载到该沙箱。

这套方案把执行端移到 Render。聊天端调用已连接的远程 MCP 工具，后端用上游原生实现直接读取原始 SQLite `.db` 快照。图谱不会先被导出为 Markdown、摘要或一套自制 SQL API。

提供五个原生查询接口，并可通过 `add_index` 从 GitHub 链接添加已有索引：

- `list_projects`：确认项目；
- `get_architecture`：查看架构、语言和包；
- `search_graph`：搜索符号；
- `trace_path`：追踪调用者和被调用者；
- `query_graph`：执行只读 Cypher。

仓库包含 C 原生入口、Python HTTP MCP、Render Blueprint、快照下载与完整性校验、ChatGPT 私有 Sites 网关、随 MCP 提供的使用指令，以及可以直接给 Agent 的部署任务。

用户只连接一个 **Codebase Graph Reader** 插件，它同时提供五个查询工具、索引注册和查询工作流。Render 上的原生引擎是后端组件，不再拆成一个 Reader 加一个 Reader Engine 插件。

ChatGPT 路线由 Sites 处理平台 OAuth，Render 保存服务端查询密钥。静态 Bearer 密钥没有被当成 OAuth，也不会写进插件包。其他 MCP 客户端可以按自身的认证能力连接。

实现过程中有两个值得注意的细节。Cloudflare Workers 不支持 `redirect: "error"`，需要使用 `manual` 并拒绝重定向。部分聊天宿主会省略 MCP `_meta`，所以快照来源同时放进可见的结构化结果和追加文本块。

原型已经验证过真实原生查询、符号搜索、调用路径和分页。模板附带传输/认证测试，并提供基于用户授权快照副本的原生集成验证脚本。新部署仍需用自己的图谱，在目标宿主执行一次完整验收；只有服务器显示 live 不够。

现在同一个 MCP 可以注册多个 GitHub 图谱，按项目选择、独立缓存和刷新。已有索引 Actions 可推送更新；链接注册项目会检查 blob 变化。远程源码变化但尚未重新生成 `.db` 时，阅读器仍读取原有索引。没有编辑文件或在线索引生成功能。Render 免费实例适合试验，但有休眠与临时文件系统限制。长期使用需要评估资源和可靠性。

上游项目：https://github.com/DeusData/codebase-memory-mcp

完整模板和 Agent 部署指南：[EiraWalker/Code-Tools](https://github.com/EiraWalker/Code-Tools/tree/main/Plugins/codebase-graph-mcp-render)。从 README 进入 AGENT_SETUP.md，即可把实施任务交给自己的 Agent。

公开模板不包含真实图谱、私人项目资料、部署标识或凭据。每个人使用自己的数据、账户和服务。

欢迎讨论：你的索引发布流程更适合 Actions 推送更新，还是 GitHub 链接加版本检查？
