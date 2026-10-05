# Codebase Graph MCP on Render

让 AI Agent 通过远程 MCP 查询原始代码图谱。原生 `codebase-memory-mcp` 查询引擎运行在 Render，聊天端调用工具，不需要挂载插件二进制。

这是可复用的单项目部署模板。你提供自己有权访问的 `.db` 快照，配置自己的认证入口，并创建自己的插件。本仓库不包含任何真实图谱、账户凭据、私人项目资料或已部署服务地址。

**只安装一个 Codebase Graph Reader 插件。** 使用指令通过 MCP `initialize.instructions` 和工具说明提供，不需要另装 Reader Engine 或 skills-only 包。

本模板位于公开仓库 [EiraWalker/Code-Tools](https://github.com/EiraWalker/Code-Tools/tree/main/Plugins/codebase-graph-mcp-render) 的 `Plugins/codebase-graph-mcp-render/`。

**先给 Agent 阅读 [AGENT_SETUP.md](AGENT_SETUP.md)。完整方案见 [docs/architecture.md](docs/architecture.md)。**

## 组件与数据流

1. 本地使用上游工具对代码库建立索引，生成一致的 SQLite 图谱快照。
2. Render 构建固定版本的原生引擎，并获取、校验你的快照。
3. Python 适配器将原生查询结果通过 Streamable HTTP MCP 返回。
4. ChatGPT 路线使用私有 Sites 网关处理平台 OAuth；其他客户端可按自身能力直接连接 Render。
5. 同一个 Codebase Graph Reader 插件同时提供五个工具和 MCP 使用指令；Render 引擎是后端服务。

| 组件 | 作用 | 是否包含在模板中 |
| --- | --- | --- |
| 原生入口 | 链接上游查询实现；关闭守护进程及后台任务 | 是，C 源码 |
| Render 后端 | HTTP MCP、项目范围、校验和服务认证 | 是 |
| 快照获取 | HTTPS 下载原始字节，拒绝重定向，校验后原子安装 | 是 |
| ChatGPT 网关 | 转发 MCP；依赖 Sites 的可信身份边界 | 是，需在你自己的 Sites 项目部署 |
| 查询指令 | MCP 初始化指令及各工具说明，随同一连接提供 | 是 |
| 图谱与密钥 | 你的私人输入 | 否 |

## 五个接口

| 工具 | 用途 |
| --- | --- |
| `list_projects` | 确认可查询的项目 |
| `get_architecture` | 架构、语言、包和节点统计 |
| `search_graph` | 查找符号及限定名 |
| `trace_path` | 查询调用者、被调用者及图路径 |
| `query_graph` | 只读 Cypher 结构查询 |

返回结果保留原生内容、分页、截断字段及 `isError`，并在结构化结果和追加文本块中显示快照来源。接口参数以服务器实际提供的 schema 为准。

## 开始部署

- [给 Agent 的完整执行指令](AGENT_SETUP.md)
- [后续维护与 API 部署顺序](MAINTENANCE.md)
- [准备你自己的索引快照](docs/snapshot.md)
- [Render 部署与 API 管理](docs/render.md)
- [ChatGPT 插件与认证网关](docs/plugin.md)
- [验证与故障定位](docs/verification.md)
- [隐私边界与公开发布检查](SECURITY.md)
- [Discussion 分享帖](docs/discussion-post.zh-CN.md)

上游查询代码固定为 **v0.11.0**，提交 `8972ea69c6ad94b1ef1d4ffbf0a92d78d2db1798`。这是可复现的兼容性基线，不代表上游最新版本。不要假设任意新版本数据库均兼容。

## 快速本地检查

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
.venv/bin/python -m unittest discover -s tests
node gateway/scripts/check-access.mjs
```

准备好自己有权访问的快照和私有环境配置后，再运行 `scripts/verify_native.py`。这个脚本使用快照副本，并执行真实原生 HTTP MCP 查询。上面的下载单元测试只检查传输和校验，不能替代原生集成测试。

## 范围与限制

只查询一个图谱快照。没有在线索引、文件编辑、源码片段或自动快照同步。图谱遗漏不等于代码不存在。Unity 等引擎的运行时回调和序列化引用可能未被完整记录。

`CBM_SERVICE_TOKEN` 是后端服务认证，不是 ChatGPT OAuth。不要把 Render 的服务端密钥写进插件文件。不要把 Sites 的可信身份头机制直接搬到裸露的通用 Worker 上。

Render 免费实例适合试验，存在休眠、冷启动、临时文件系统和配额限制。持久存储方案与可靠性需求应单独评估，详见官方 [免费服务说明](https://render.com/docs/free)。

## 来源与许可

原生图谱查询能力来自 [DeusData/codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp)。本项目提供适配代码和部署方法，不是上游官方托管服务。

模板适配代码使用 MIT 许可。上游 MIT 许可及依赖声明保留在 `backend/native/`。发布自行编译的二进制时，保留对应版本的许可和第三方声明。
