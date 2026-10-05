# 准备原始图谱快照

1. 在你有权限的真实代码库上使用上游 `codebase-memory-mcp` 建立索引。按上游固定版本的说明配置；本模板不代替索引器。
2. 使用原生 `list_projects` 确认项目缓存名和索引状态。不要从展示名称猜缓存名。
3. 获得一致的 SQLite 快照。停掉写入后复制，或使用 SQLite 官方 backup API。若正在使用 WAL，不能只复制主 `.db` 并忽略尚未 checkpoint 的 WAL。
4. 在本机运行 `python scripts/snapshot_identity.py /absolute/path/to/snapshot.db`。保存 size、SHA256 和 Git blob SHA。
5. 将快照保存在自己的私有仓库或授权 HTTPS 对象存储。不要提交到这个公共模板。

SQLite 一致性说明见 [Online Backup API](https://www.sqlite.org/backup.html) 和 [WAL](https://www.sqlite.org/wal.html)。

## 授权下载

`prepare_snapshot.py` 从 `CBM_GRAPH_URL` 下载原始字节。可在 `CBM_GRAPH_BEARER_TOKEN` 中配置读取凭据。它不跟随重定向，避免把凭据发送到别的主机。

一种来源是 GitHub Contents API 的原始媒体类型：

```text
https://api.github.com/repos/OWNER/PRIVATE_REPO/contents/PATH_TO_GRAPH?ref=IMMUTABLE_COMMIT
```

这是结构示例，不是真实仓库地址。为读取授权使用最小仓库范围；令牌保存在 Render 秘密配置中。大文件/媒体响应限制以 [GitHub Contents API 文档](https://docs.github.com/en/rest/repos/contents#get-repository-content) 为准。若接口返回 JSON 或重定向，本模板会拒绝；改用可返回原始字节的受控来源。

不要将一次性下载链接当成持久部署来源。Render 重建时需要能重新取得同一快照。

## 缓存与更新

已有目标文件时脚本先校验，不擅自覆盖校验失败的缓存。更新需要换成新部署产物，或在维护窗口管理缓存，然后部署匹配的新校验配置。

设置 `CBM_GRAPH_MAX_BYTES` 可调整下载上限；必须同步评估机器内存。原生引擎和数据库版本需兼容；先在快照副本上测试。
