# 验证与排错

## 已提供的测试

```bash
.venv/bin/python -m unittest discover -s tests
node gateway/scripts/check-access.mjs
```

下载测试检查原始字节、校验失败清理、缓存失败保护、大小限制、路径限制及拒绝携带凭据跟随重定向。网关测试检查身份要求、工具限制、固定目标、凭据隔离、可见来源和重定向拒绝。

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
| 网关 403 | 私有 audience、可信用户身份或 operator service 认证 |
| 502 redirect | 配置实际 HTTPS origin；保持禁止转发秘密到新主机 |
| 冷启动超时 | 实例休眠、宿主超时、资源方案；不要重复创建服务 |
| 原生 `isError` | schema、限定名、兼容性或 scope；HTTP 200 不代表原生成功 |
| 结果缺少来源 | 宿主可能省略 `_meta`；检查可见 structured/text 块 |
| 找不到符号 | 先放宽 label / regex；快照可能过时或覆盖不足 |
| 新 Git blob 与托管哈希不符 | 明确报告旧快照，更新配置并重新部署 |

服务日志不能包含请求参数、图谱字节、下载 URL、Authorization、管理凭据或原始私人结果。

## 单一插件验收

MCP initialize 必须返回 Codebase Graph Reader 的 serverInfo.name 和完整 instructions；tools/list 必须只包含五个查询工具，带查询顺序、真实限定名和快照来源的说明。新增用户仅需安装 canonical 插件；验证过程不得依赖旧的额外指令插件。宿主若省略 initialize.instructions，使用工具说明继续同一流程。
