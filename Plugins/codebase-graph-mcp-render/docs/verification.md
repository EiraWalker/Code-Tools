# 验证与排错

## 已提供的测试

```bash
.venv/bin/python -m unittest discover -s tests
node gateway/scripts/check-access.mjs
```

下载测试检查原始字节、校验失败清理、缓存失败保护、大小限制、路径限制及拒绝携带凭据跟随重定向。网关测试检查身份要求、工具限制、固定目标、凭据隔离、可见来源和重定向拒绝。

缓存同步测试检查：同版本只发元数据、不上传数据库；损坏文件或原生校验失败不改变活动缓存；活动 manifest 重启后可恢复；旧运行不能覆盖新运行；切换等待当前查询释放版本锁。OIDC 测试覆盖签名、过期、issuer/audience、仓库/分支/工作流范围及带 owner/repo ID 的不可变 subject。

它们不包含私人图谱，也不替代原生查询。

## 实际原生集成测试

在私有配置中设置 backend 所需变量和已经编译的 `CBM_BINARY`，再执行：

```bash
.venv/bin/python scripts/verify_native.py
```

脚本复制授权快照到临时目录，只对副本运行本地 HTTP MCP。它检查五个工具的发现、原生查询、节点计数、项目范围、原生错误、未认证访问及查询前后文件不变。若快照没有 CALLS 边，会明确报告 `trace_tested: false`，不能把它当成调用路径验证通过。

## 在目标宿主验收

1. `list_projects` 确認项目和统计。
2. `get_architecture` 获取结构和总数。
3. `search_graph` 搜索真实符号；根据返回的 `qn_rule` 构造限定名。C# 方法常标注为 `Method`，不要一律假设 `Function`。
4. `trace_path` 使用这个限定名；检查总数及分页。
5. `query_graph` 执行 `MATCH (n) RETURN count(n) AS nodes`，与架构统计核对。
6. 检查 `structuredContent.graph_snapshot` 或追加文本块的来源及哈希。
7. 如有分页标记，根据实际 next_offset / next_cursor 继续，不自行猜 continuation。

分别记录：构建通过、服务 live、HTTP 查询通过、目标宿主工具调用通过。四者不是同一结论。

## 常见失败

| 现象 | 检查 |
| --- | --- |
| 找不到包内 executable | 使用远程工具；资源打包不等于沙箱挂载 |
| `/mcp` 401 | 服务端 token 或宿主 OAuth；不要关闭认证 |
| `/snapshot-sync` 401 | GitHub OIDC 签名及限定 identity；新仓库 subject 含 owner/repo ID，配置 `CBM_SYNC_OWNER_ID`，不能套用仅名称的旧格式 |
| `/snapshot-sync` 422 | 文件大小、SQLite 头、SHA256、blob SHA、原生项目身份与来源提交；旧缓存应继续可读 |
| 网关 403 | 私有 audience、可信用户身份或 operator service 认证 |
| 502 redirect | 配置实际 HTTPS origin；保持禁止转发秘密到新主机 |
| 冷启动超时 | 实例休眠、宿主超时、资源方案；不要重复创建服务 |
| 原生 `isError` | schema、限定名、兼容性或 scope；HTTP 200 不代表原生成功 |
| 结果缺少来源 | 宿主可能省略 `_meta`；检查可见 structured/text 块 |
| 找不到符号 | 先放宽 label / regex；快照可能过时或覆盖不足 |
| 新 Git blob 与托管哈希不符 | 明确报告旧快照；启用自动同步时检查原索引 Actions 的发布及刷新步骤，修正后重跑原任务。新部署的 bootstrap 输入另按维护流程更新 |

服务日志不能包含请求参数、图谱字节、下载 URL、Authorization、管理凭据或原始私人结果。

## 自动刷新验收

按 [自动刷新](automatic-refresh.md) 配置现有索引生成工作流，在 Render live 后运行原任务。既有生成和私有仓库发布步骤必须成功，随后新增刷新步骤必须返回 `Graph reader cache: refreshed.` 或 `unchanged.`。

在真实 MCP 宿主重新调用五个接口，确认活动 blob SHA、SHA256、来源提交、节点及边数量与本次发布的图谱和 provenance 一致。连续查询仍应使用同一缓存版本，查询路径不调用下载脚本。工作流失败、Render live 和快照已激活分别记录，不能互相替代。

此流程已在真实发布任务及目标 MCP 宿主验证；公开仓库仅保留实现和验证方法，不包含私人运行标识、图谱字节、部署地址或认证凭据。

## 单一插件验收

MCP initialize 必须返回 Codebase Graph Reader 的 serverInfo.name 和完整 instructions；tools/list 必须包含五个原生查询工具和适配层 `add_index`，不得暴露 `index_repository` 等原生写工具，带查询顺序、真实限定名和快照来源的说明。新增用户仅需安装 canonical 插件；验证过程不得依赖旧的额外指令插件。宿主若省略 initialize.instructions，使用工具说明继续同一流程。

## 多索引与注册验证

设置 `CBM_TEST_BINARY` 为原生 snapshot host 后运行全部 tests。测试使用合成图谱验证两个独立缓存的原生 Cypher、GitHub 注册、同一 blob 不重复下载、远程变化更新、损坏更新保留旧缓存、注册表在同一文件系统恢复，以及认证绑定目标项目。合成 fixture 的 SQLite 写入只用于构造公开测试数据，阅读器不执行 SQL 来代替查询。

真实 MCP 宿主还需发现 `add_index`，调用公开合成样例，确认新增项目出现在 `list_projects`；重试同一链接应为 `already_registered`。对已有真实项目重复五个接口验收。免费实例冷启动会丢失运行时注册表，不能把同一文件系统的重启测试当成跨实例持久化证明。
