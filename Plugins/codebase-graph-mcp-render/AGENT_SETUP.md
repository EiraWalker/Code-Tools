# 交给 Agent 的部署任务

把下面的任务段落复制给你的 Agent，并让它先阅读本仓库。不要把任何密钥粘贴进公开 issue 或 Discussion。

> 使用这个仓库，为我自己的代码项目创建单一 Codebase Graph Reader 插件和 Render 后端。插件必须同时提供工具和使用指令，不要创建两个 Reader/Engine 插件。直接读取 codebase-memory-mcp 的 `.db` 快照，不导出成文本，不使用自制 SQL 服务替代原生工具。复用我的已有连接；新增资源前检查是否已有对应资源。通过 Render API/插件管理部署。保留私有图谱与密钥，支持通过 add_index 添加 GitHub 上已有的索引和按 project 切换；完成五个原生接口及注册接口的实际验证，再报告插件链接、快照来源和未验证事项。需要 ChatGPT 插件时使用我账户自己的私有认证网关。不要把服务器发布成功当成工具调用成功。

## 1. 确认输入

获取下列值。配置在私有会话、平台秘密字段或本机未跟踪的 `.env`；不要提交到这个公开模板。

| 输入 | 来源 |
| --- | --- |
| 项目缓存名 | 原生 `list_projects`；也是快照文件名的 stem |
| 图谱文件 | 授权代码库的一致 `.db` 快照 |
| 来源仓库及路径 | 用户指定的授权范围 |
| Git blob SHA、SHA256 | 源文件元数据和本地校验 |
| 快照下载入口 | 稳定授权 HTTPS 入口；若用签名临时 URL，每次部署前必须刷新 |
| Render 工作区、地域、方案 | 用户已有资源及预算偏好 |
| 插件宿主 | ChatGPT 或支持 Streamable HTTP 的其他客户端 |

普通客户端连接不需要取得部署管理凭据。只有部署 Agent 需要 Render 管理权限。

## 2. 选择部署方式

默认用 `Plugins/codebase-graph-mcp-render/render.yaml` 创建单个后端，Blueprint 的 rootDir 已对应这个子目录。若将模板复制为独立仓库，移除 rootDir。服务名必须对当前用户唯一。
确认已有服务时，读取实际配置，再选择原地更新或创建独立服务。不得凭名称覆盖其他服务。
默认模板选择 `free`、关闭自动部署；不擅自升级到付费方案。后续唯一源码维护目录是 `EiraWalker/Code-Tools` 的 `Plugins/codebase-graph-mcp-render/`；维护流程见 `MAINTENANCE.md`。

私有图谱由 `backend/prepare_snapshot.py` 从授权 HTTPS 源下载到 `.runtime/cache`。
源 Bearer 凭据只在 Render 秘密环境变量中保存；不进入插件、Git 或日志。
如使用不同的认证下载协议，在私有部署副本中实现，并增加相应测试。

## 3. 构建并部署

设置 `docs/render.md` 中的环境变量。运行 `backend/build-render.sh`，再启动 `backend/server.py`。
通过 Render 插件或官方 API 查询实际部署 ID；只轮询这次部署，直到终态。
保留返回的真实服务 origin，不猜测子域名。
`GET /health` 应返回 ready；未认证 `POST /mcp` 应返回 401。

## 4. 创建自己的插件连接

ChatGPT 路线按 `docs/plugin.md` 创建自己的 owner-private Sites MCP 网关，配置两个运行时变量，然后发布。
Sites 生成的 canonical plugin 就是唯一的 Codebase Graph Reader。保留真实连接身份，将 title 设为 Codebase Graph Reader，复用现有 App，不再创建额外指令插件或重复 MCP App。
安装并完成连接后，在目标聊天宿主执行真实查询。

查询工作流已在 `initialize.instructions` 和五个工具说明中提供。部署时验证这些字段，确保即使宿主省略初始化指令，工具说明仍包含操作引导。不得尝试用 Plugin Creator 的 archive editor 编辑 Sites canonical App；通过所属 Sites 源码更新。
其他客户端按自己的认证能力连接 Render。若宿主要求 OAuth 而客户端只有静态 Bearer，先实现正确认证网关，不把两者混为一谈。

## 5. 验收并交付

- 只需一个插件连接即可执行工作流；初始化和 tools/list 提供使用指令。
- 五个接口都有实际调用结果；至少一次 `search_graph` 找到符号。
- 从搜索/图查询中取得真实限定名，再调用 `trace_path`。
- 节点计数与架构统计一致。
- 分页/截断字段原样保留；查询错误的 `isError` 原样保留。
- 未认证请求失败；不允许索引工具及其他项目。
- `graph_snapshot` 在宿主可见，校验值匹配输入快照。
- 查询前后 `.db` 字节不变。
- 公开源码和 Discussion 未包含私人图谱、真实符号、部署标识或秘密。

若工具没有出现在宿主，不重复要求已安装的用户安装。检查当前工具库存、连接状态与部署日志。
若无法创建仓库、部署、取得图谱或执行宿主工具，报告精确失败点与已完成部分，不编造成功。

## 通用索引阅读器

先阅读 [多索引与 add_index](docs/multiple-indexes.md)。保留一个 canonical App，新增图谱使用同一 App 的 `add_index`；不要为每个仓库创建一个插件。仅添加已有的原始 `.db`，没有图谱时复用用户现有索引生成流水线。不要把 GitHub Connector 的 OAuth 凭据导出到 Render；私有仓库的后端读取凭据须由用户私下配置。
