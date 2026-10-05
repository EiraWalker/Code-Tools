# 完整方案

## 为什么需要远程入口

插件包能保存二进制，不意味着聊天宿主会把二进制挂载到执行环境。文本 skill 读取能力也不意味着具备程序执行能力。改变压缩格式或执行权限，不能增加宿主没有的执行接口。

本模板把程序执行交给 Render，把工具调用交给远程 MCP。聊天宿主只需要连接能力。

```mermaid
flowchart TD
  A["Agent / ChatGPT"] --> B["已连接的 MCP 工具"]
  B --> C["Sites OAuth 网关（ChatGPT 路线）"]
  B --> D["直接连接（支持后端认证的客户端）"]
  C --> E["Render HTTP MCP 适配器"]
  D --> E
  E --> F["上游原生查询实现"]
  F --> G["原始 SQLite 图谱快照"]
```

## 单一插件

同一 canonical MCP 连接提供五个查询工具、初始化使用指令和工具级说明。Reader Engine 是 Render 中的实现组件，不创建第二个插件。用户只连接 Codebase Graph Reader。

## 原生引擎

`backend/native/standalone_main.c` 链接固定版本上游的嵌入 API。它建立单进程 MCP 实例、关闭后台任务、设置 analysis 工具 profile。

它不启动上游共享守护进程，因此不走守护进程版本协调所用的 `/proc/<pid>/exe` 路径。它不会关闭操作系统沙箱，也不是未经修改的上游发行版可执行文件。

## HTTP 适配器

`backend/server.py` 通过原生 stdio `tools/list` 获取真实 schema，再只公开五个查询工具。每次调用由原生 `--call` 入口处理；Cypher 也交给上游引擎，不用 Python SQL 重新实现。

适配器只允许配置的项目，将数据库完整性校验放在调用前后，限制并发数，并保留原生错误、分页及截断语义。独立快照缓存中不能混入其他项目。

## 两层认证

Render `/mcp` 使用服务端 Bearer 密钥保护。`/health` 不返回私人图谱信息。

ChatGPT 路线额外使用 Sites 的平台 OAuth 与 owner-private 访问控制。网关仅信任 Sites 注入的用户身份，去掉客户端身份、Authorization 和 Origin，再向固定 Render origin 发送服务端凭据。

通用 Cloudflare Worker 不会自动提供 Sites 的信任边界。不要在公网裸 Worker 中信任客户端可自行设置的 `oai-authenticated-user-id`。

下图展示 ChatGPT 路线的请求顺序与认证边界。未获授权的请求在 Sites 平台被拒绝；获准请求携带平台认证后的身份进入网关，再由网关使用独立服务密钥调用 Render。

![ChatGPT、Sites 平台、网关 Worker 与 Render 的认证时序](images/chatgpt-mcp-auth-sequence.png)

## 快照来源

MCP 宿主可能省略 `_meta`。所以后端在 `structuredContent.graph_snapshot` 和追加文本块中同时返回仓库、图谱路径及校验值。原生结果的原有字段和第一个文本块保持不变。

不要把这些来源字段误认为最新工作树状态。更新快照需要同时更新下载源、校验值并部署。可先核对 GitHub 的新 blob，再决定是否刷新。

## 资源边界

下载脚本默认限制快照为 256 MiB。后端为了完整性校验会读数据库字节；查询引擎也需要内存。大型项目应测量内存、查询时间和冷启动，调整实例与设计。改变大小上限不等于增加可用内存。

模板只实现单项目。多用户隔离、按用户选图、增量索引、后台同步与限流需要独立设计，不能仅删除项目范围检查。
