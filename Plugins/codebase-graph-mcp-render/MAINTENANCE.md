# 后续维护入口

唯一源码目录：[EiraWalker/Code-Tools / Plugins/codebase-graph-mcp-render](https://github.com/EiraWalker/Code-Tools/tree/main/Plugins/codebase-graph-mcp-render)。从这个目录修正 backend、gateway、测试和文档。私人部署标识、环境变量、图谱及临时下载地址保存在私有平台配置中。

## 维护 Agent 的执行顺序

1. 用 GitHub 插件读取当前 main、目录 tree 和待编辑文件；保留无关文件与并发更新，不强制覆盖分支。
2. 修正源码，运行对应检查。查询适配器变更运行授权快照副本上的 `scripts/verify_native.py`；网关变更运行 `node gateway/scripts/check-access.mjs`。提交前检查公开文件不含秘密或私人项目资料。
3. 用 Render API/插件读取现有服务配置，确认 repo、branch、rootDir 指向本目录。保持已存在的 service ID、origin、方案及密钥；不新建替代服务。REST API 有可用认证及网络时优先使用，不能将插件 OAuth 当成可导出的 API key。
4. 确认私有快照来源和校验值。若使用 GitHub 临时 download_url，通过已授权 GitHub 连接读取目录元数据，核对图谱 blob SHA，获取新 URL；不要输出这个 URL。稳定授权源不需要此刷新步骤。
5. 先完成服务仓库、rootDir、命令等配置，再用 Render 环境变量接口合并 CBM_GRAPH_URL，保留其他变量。不要使用全量 replace。临时源必须关闭自动部署；源码先提交完成，URL 最后刷新。注意：当前 Render 插件的环境变量更新工具会主动触发部署，即使 autoDeployTrigger 为 off；保留其返回的 deploy ID。
6. 若环境变量工具已触发部署，直接跟踪它返回的 deploy ID，不再触发第二次。只有使用未启动部署的 REST 配置更新时，才立即通过 Render API 触发一次部署；只轮询该部署并检查其构建日志。下载并校验快照应在长时间的原生编译之前完成。不得假设缓存存在。
7. 等待 live，核对部署 commit 与提交一致；在目标聊天宿主执行五个工具，确认图谱来源、符号搜索、调用路径、统计、分页及错误语义。服务器 live 不能代替工具验收。
8. 如果改了 gateway，从本目录的 gateway 源码更新已有私有 Sites 项目，保留平台身份、运行时秘密与 audience，走 Sites 所属的发布流程；不创建额外 Reader Engine 或指令插件。Sites 管理的私有源码是部署副本，维护修改以本目录为准。

## 单一 App

唯一安装入口承载 MCP 查询工具、初始化指令和工具说明。原生引擎运行在 Render 后台。迁移时验证 canonical MCP 连接正常后，再移除用户明确授权卸载的旧独立指令包；保留承载 OAuth 的 canonical App。

## 部署输入变化

每次查询都使用服务的本地快照缓存，绝不重新下载。已有索引生成 Actions 在成功发布图谱后，通过 OIDC 自动同步新版本；同版本只发送小型元数据，不上传图谱。参见 [自动刷新](docs/automatic-refresh.md)。不要创建另一个索引工作流，也不要把签名 URL 刷新加入 MCP tools/call 路径。

新部署的 bootstrap 仍需要有效下载来源和校验值。部署完成后运行原有索引 Actions 一次，以同步最新版本；免费实例的临时文件系统不能保证替换实例后保留运行时缓存。部署更新与自动索引同步使用不同认证入口。

更新图谱时同时更新 blob SHA、SHA256 和来源；更换项目时确认下载字节、缓存名与项目范围一致。不要只修改 URL 后继续使用旧校验值。临时 URL 过期会使后续构建失败，不能用自动部署绕过刷新。

新增项目优先调用现有 MCP 的 `add_index`。仅修改初始固定目录时使用私有 `CBM_INDEXES_JSON`，兼容现有单项目环境变量。所有 GitHub 凭据、源 URL 和真实项目配置均保存在私有后端配置。使用同一 App；参见 [多索引说明](docs/multiple-indexes.md)。
