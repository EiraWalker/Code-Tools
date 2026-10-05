# 构建自己的 Render 后端

## Blueprint 路线

Fork `EiraWalker/Code-Tools`，在 Blueprint 创建页面指定 `Plugins/codebase-graph-mcp-render/render.yaml`。该文件的 `rootDir` 已设置为模板子目录。若将模板复制到独立仓库根目录，移除 `rootDir` 后导入根目录 `render.yaml`。为当前账户使用唯一服务名，选择适合预算的地域及方案。

模板默认是 Python 3.12.12、Free、手动部署、健康检查 `/health`。
构建命令 `bash backend/build-render.sh`；启动命令 `python backend/server.py`。直接通过 API 创建服务时也要将 rootDir 设置为 `Plugins/codebase-graph-mcp-render`；命令相对于 rootDir 执行。
构建会先安装锁定依赖、下载并校验快照，再获取固定上游提交、编译单进程入口。下载在耗时编译之前进行。

部署时配置以下私有输入：

| 变量 | 含义 |
| --- | --- |
| `CBM_PROJECT` | 快照缓存名，不含 `.db` 或路径分隔符 |
| `CBM_SOURCE_REPOSITORY` | 用于来源说明的仓库标识 |
| `CBM_GRAPH_PATH` | 来源仓库中的图谱路径 |
| `CBM_GRAPH_SHA256` | 64 位小写十六进制 SHA256 |
| `CBM_GRAPH_BLOB_SHA` | 40 位小写十六进制 Git blob SHA |
| `CBM_GRAPH_URL` | 授权 HTTPS 原始字节下载入口 |
| `CBM_GRAPH_BEARER_TOKEN` | 下载来源的可选凭据；公开源可设为空 |
| `CBM_SERVICE_TOKEN` | 随机服务端密钥，至少 32 字符 |

本机可用 `python -c 'import secrets; print(secrets.token_urlsafe(48))'` 生成服务密钥，再通过平台秘密字段保存。不要贴到公开帖子或提交文件。

其他变量已由 Blueprint 设置。生产 origin 使用 Render 返回的 `RENDER_EXTERNAL_URL`；不硬编码别人的域名。

## Render API / 插件路线

优先复用已连接的 Render 插件，先读取用户选择的 workspace 与已有服务。工具只读查询不会创建资源。

如果用官方 REST API：

1. 在自己的账户创建 API key，通过环境变量 `RENDER_API_KEY` 提供给部署工具。
2. 根据当前官方 OpenAPI 读取创建服务的 schema。不要猜 ownerId、serviceId 或环境字段。
3. 创建服务，指定本人的模板仓库、分支、上述构建/启动命令、方案和环境配置。
4. 保留创建响应的 service ID、origin 和 deployment ID。
5. 查询指定部署直到 live 或失败终态。发生失败先看这次部署日志，不重复创建同名资源。
6. 配置变化后部署并执行实际 MCP 验证。

Render API key 是管理凭据，`CBM_SERVICE_TOKEN` 是查询后端凭据，`CBM_GRAPH_BEARER_TOKEN` 是图谱来源凭据。三者不能互换。

官方文档：[API](https://render.com/docs/api)、[API reference](https://api-docs.render.com/reference/introduction)、[Blueprint](https://render.com/docs/blueprint-spec)。API schema 会演进；迁移已有服务前应根据当前官方 schema 核对字段。既有服务的仓库、分支和 rootDir 可由 [Update service](https://api-docs.render.com/reference/update-service) 修改，省略的字段保留。修改后必须另行触发部署。

### 已有服务切换到本目录

保持现有 service ID、origin、地域、方案和服务密钥。目标 repo 为 `https://github.com/EiraWalker/Code-Tools`，branch 为 `main`，rootDir 为 `Plugins/codebase-graph-mcp-render`；构建/启动命令使用上述相对路径。将 CBM_BINARY 设为 `backend/.cbm-upstream/build/c/codebase-memory-mcp`，CBM_CACHE_DIR 设为 `.runtime/cache`。原快照的项目名、来源仓库、路径和校验值仍属于私有部署配置。

### 签名临时下载源

有权限的 GitHub 插件可从私有仓库的 contents 目录元数据取得图谱的 `download_url`。该地址带临时访问凭据，必须像秘密一样处理：只在内存中保留并通过 Render API 合并到 CBM_GRAPH_URL，不打印、不提交、不写入公开记录。不要对二进制文件使用只支持文本的 fetch 接口。

每次部署前重新获取该地址，核对 blob SHA，先完成服务来源与命令配置，最后写入环境变量。当前 Render 插件的环境变量工具会自动触发部署，即使 autoDeployTrigger 为 off；使用它返回的 deploy ID，不要再触发一次。直接 REST 配置更新没有触发部署时，再立即调用部署 API。签名 URL 路线要求 autoDeployTrigger 为 off；禁止从旧环境变量复用过期 URL或自动部署。下载失败时刷新 URL，再针对失败原因重试；不能关闭校验、将私人图谱公开或创建未经授权的长期 token。生产自动部署应改用稳定的授权源。详细顺序见 [维护指南](../MAINTENANCE.md)。

## 冷启动与数据持久性

Free 会因空闲休眠，首次请求可能等待约一分钟。它使用临时文件系统，不支持持久磁盘。生产项目需要评估付费计算和存储。见 [官方限制](https://render.com/docs/free)。

快照应在构建产物中准备，或在启动前从可重复授权来源恢复。这个模板采用构建阶段准备，不能把运行时临时上传的 `.db` 当成持久备份。
