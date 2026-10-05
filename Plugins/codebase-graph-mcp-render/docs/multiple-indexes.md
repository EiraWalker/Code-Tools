# 通用索引阅读 MCP

同一个 Codebase Graph Reader App 支持多个项目。Render 运行原生查询引擎；注册和缓存属于适配层。五个原生查询接口保持只读，`add_index` 修改授权用户的项目目录。

## 通过 MCP 添加 GitHub 图谱

对 Agent 说：“添加这个 GitHub 仓库的代码图谱：`https://github.com/owner/graph-snapshots`，之后查询它。”

Agent 调用：

```json
{"name":"add_index","arguments":{"github_url":"https://github.com/owner/graph-snapshots"}}
```

仓库恰好有一个 `.db` 时自动选择。多个文件时返回 `choose_graph` 和 `candidates`，再次调用并提供 `graph_path`。没有 `.db` 时返回 `index_required`；需先使用仓库已有的索引 Actions 生成并发布，阅读器不会扫描源码建立新索引。也支持 `/blob/<ref>/<path>` 或 `/tree/<ref>/<directory>` 链接。非默认分支含 `/` 且链接有歧义时显式提供 `ref`。

```json
{"name":"add_index","arguments":{"github_url":"https://github.com/owner/graph-snapshots","graph_path":"graphs/project-alpha.db","ref":"main"}}
```

`project` 默认取 `.db` 文件名，必须与图谱内部的原始项目名一致；可以显式提供原始名，但不会修改图谱内容。不同来源不能占用同一原始项目名。下载使用解析 ref 后的不可变 commit，检验 Git blob SHA、SHA256、大小和 SQLite 文件头，再通过原生 `list_projects` 检验项目身份。校验失败不会激活项目。

成功后调用 `list_projects`，再把返回的项目名传给 `get_architecture`、`search_graph`、`trace_path`、`query_graph` 的 `project`。重复注册相同项目/来源返回 `already_registered`，无需另建插件或部署。多项目时必须显式选择；不会悄悄使用目录中的第一个项目。目录有稳定分页，每条项目携带自己的 `graph_snapshot`，汇总来源字段为 `graph_snapshots`。原生查询返回该次查询实际使用的单个快照。

## 公开验证样例

本仓库的 `tests/fixtures/reader-demo.db` 是合成样例，三个节点、一条 `CALLS` 边，没有真实仓库内容。可通过以下链接验证注册：

```json
{"github_url":"https://github.com/EiraWalker/Code-Tools/blob/main/Plugins/codebase-graph-mcp-render/tests/fixtures/reader-demo.db"}
```

原始项目名为 `reader-demo`。注册后查询 `MATCH (n) RETURN count(n) AS nodes` 应得到 3；符号 `demo.entry` 调用 `demo.helper`。样例用于验证阅读流程，不表示真实项目由这个阅读器生成了索引。

## 缓存及自动更新

链接注册项目第一次添加时下载原始字节，之后使用独立缓存。默认在使用该项目时每 300 秒检查一次 GitHub 元数据；`CBM_GITHUB_CHECK_SECONDS` 可调整，最少 30 秒。Git blob SHA 未变化时不重新下载；变化时下载并校验，原子切换活动快照。更新失败保留旧快照，并返回 `refresh_warning`，Agent 必须保留这个说明。这个检查是查询触发，不是无人使用时仍运行的后台定时器。

原有固定项目继续复用索引 Actions 的 OIDC 推送。多项目推送需指定 `X-Snapshot-Project`；附加脚本自动从 `.db` 文件名取项目，或通过 `CBM_SYNC_PROJECT` 覆盖。每项目独立绑定发布仓库、不可变 ID、分支、workflow 和 run 水位，其他项目的发布身份不能更新该缓存。动态注册项目默认采用 GitHub 版本检查，不自动创建新 Actions。

## 私有仓库凭据

在 Render 的私有环境变量设置 `CBM_GITHUB_TOKEN`，只授予需要读取的仓库 Contents read。不把 token 作为 `add_index` 参数，不在聊天提供凭据，不写进公开仓库。现有 GitHub Connector 的授权不会自动成为 Render 的凭据；未配置时公开仓库可读，私有仓库会给出访问配置说明。所有项目沿用同一个 App 的 owner-private 访问范围；没有每访客独立权限。

## 固定初始目录与旧配置

旧的 `CBM_PROJECT` / `CBM_GRAPH_*` / `CBM_SOURCE_REPOSITORY` 和 `CBM_SYNC_*` 配置仍有效，保留原来的缓存位置与流程。它可以与运行时 `add_index` 注册项目共存。

如果需要部署时固定多个索引，将 [indexes.example.json](../backend/indexes.example.json) 的内容作为 Render 私有环境变量 `CBM_INDEXES_JSON`。替换全部示例项目、hash 和 publisher ID，配置每个 `url_env` 引用的 HTTPS 图谱下载地址；可选 `bearer_token_env` 引用私有凭据环境变量。目录启用后，每条记录使用自己的发布策略，不继承旧单项目 `CBM_SYNC_*`。初始配置最多 32 项，全部目录（固定加动态）也最多 32 项。后续增加项目可以直接用 MCP。

## 持久化边界

注册表、各项目活动快照和前一代上传版本保存在后端缓存文件系统。在同一文件系统启动时可以恢复。当前 Render 免费实例的文件系统是临时的：重新部署、实例重启或休眠冷启动可能丢失运行时注册与更新，回到构建时固定目录。重新调用 `add_index` 可以恢复链接项目，已有固定项目可以重跑原来的发布 Actions。此版本没有升级付费存储，也没有承诺跨实例持久化。稳定长期使用需要单独配置持久存储和运行时缓存初始化；不能仅把构建时路径改成 disk 挂载点。
