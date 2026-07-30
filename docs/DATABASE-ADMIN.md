# 本地数据库管理

文献星图本身可以发布为纯静态网页，但原始 SQLite 数据只能由本机管理服务修改。这个边界可以避免把数据库、管理 token、OpenAlex 缓存或尚未确认再分发许可的摘要和全文暴露到 GitHub Pages。

## 启动方式

需要 Python 3.11+、Node.js 22.13+，并已在仓库根目录安装项目：

```powershell
python -m pip install -e ".[atlas]"
```

打开两个 PowerShell 窗口。第一个窗口从仓库根目录启动只监听本机回环地址的管理 API：

```powershell
python -m neutral_atom_graph admin --host 127.0.0.1 --port 8765
```

服务启动时会输出本次运行使用的随机 token。不要把 token 写入代码、`.env`、截图、Issue 或 Git 历史。

第二个窗口启动网页：

```powershell
cd apps/atlas
npm run dev
```

然后打开：

```text
http://localhost:3000/admin/
```

在连接面板填写 `http://127.0.0.1:8765` 和管理服务输出的 token。token 只保存在当前站点的 `sessionStorage`，关闭标签页或浏览器会话后需要重新输入；它不会写入数据库、静态导出或 GitHub Pages 构建产物。

管理服务只应绑定 `127.0.0.1` 或其他明确的 loopback 地址。不要改成 `0.0.0.0`，也不要通过端口转发把它暴露到局域网或互联网。

## 当前管理范围

第一版管理界面采用受控字段白名单，而不是任意 SQL 编辑器。它用于检索记录、修复缺失或错误题录，并查看一篇文献连接的原始关系数据。

可编辑的人工校对字段包括：

- 题名、年份和出版日期；
- 作者、期刊或会议、文献类型；
- 摘要、落地页 URL 和开放获取 URL；
- 元数据状态；
- 分类法中已经定义的人工分类标签。

人工修改题名时，服务端会同步更新规范化题名和来源标记。作者必须保持为字符串数组；OpenAlex topics 在数据库中是包含 `id`、`name` 和 `score` 的对象数组，不能用简单字符串列表覆盖。

以下数据在第一版中只读：

- `work_id`、稳定的 `paper_uid`、`canonical_id` 和创建时间；
- 知识实体类型 `entity_kind`；
- DOI、arXiv、OpenAlex、Semantic Scholar 与 BibTeX 标识符映射；
- 引用边、种子 BibTeX 原始记录和综述引用位置；
- OpenAlex 等 provider 的原始响应、抓取状态和引用数统计；
- 自动分类结果、论文文件记录和全文索引；
- 详情面板中的原始 JSON。

这些关系数据需要专门的合并、拆分或溯源流程。尤其是 DOI 和 arXiv ID 同时参与实体去重与 `canonical_id` 计算，直接改一列可能把两个文献实体错误合并。因此第一版不提供删除文献、合并实体、修改引用边或执行任意 SQL 的入口。

人工分类只能新增或删除 `method=manual` 的记录，并且维度和类别必须存在于当前活动 taxonomy。规则推导、综述层级和 venue 分类保持只读，重新运行 `classify` 不会覆盖人工标签。

## 保存、并发冲突与恢复

打开编辑器时，网页会保存该记录的服务端版本。提交时服务端在一个事务中比较版本；如果另一个标签页、抓取任务或命令行进程已经更新同一记录，接口返回 `409 Conflict`，不会用旧表单静默覆盖新数据。此时应重新加载记录、比较变化后再保存。

管理服务在本次进程的第一次写入前使用 SQLite online backup 创建一致快照，默认保存在：

```text
data/backups/
```

数据库使用 WAL 模式，因此不能把正在使用的 `literature.sqlite` 单文件直接复制后当成可靠备份。online backup 会把主库和 WAL 中已经提交的数据合并成一致快照。数据库较大时首次保存可能需要等待；终端会输出备份进度。备份失败时不应继续写入。

每次成功修改会在同一事务中写入 `admin_audit_log`，记录操作、实体、变更前后数据、请求 ID 和时间。审计记录不保存管理 token。审计日志用于追查人工校对，不替代定期离线备份。

## GitHub Pages 上的管理页

`apps/atlas` 使用 Next.js 静态导出。GitHub Pages 上的 `/admin/` 路由只提供架构说明和本地启动指引，不直接连接、上传或修改 SQLite，也不会包含管理 token。GitHub Pages 没有可信的持久化后端和用户授权层，因此不能安全地承担原始数据写入。

需要修改数据时，始终从 `http://localhost:3000/admin/` 打开本地页面，并保持 Python API 只监听回环地址。修改完成后按正常流程重新生成可公开的精简快照：

```powershell
python -m neutral_atom_graph classify
python -m neutral_atom_graph export
python apps/atlas/scripts/prepare_data.py
```

只有经过版权和隐私检查的静态图数据才应提交到 GitHub。

## 数据与密钥边界

以下内容默认不提交：

- `data/database/literature.sqlite` 及其 WAL/SHM 文件；
- `data/backups/` 中的数据库快照；
- 管理 token、`.env` 和 API key；
- OpenAlex/API 缓存；
- 未确认再分发许可的摘要、PDF、源码和 Markdown 全文。

提交前可运行：

```powershell
git status --short
git check-ignore data/database/literature.sqlite data/backups/example.sqlite .env
```

> Backup retention: the service never deletes snapshots automatically. After verifying a newer snapshot and an offline copy, archive or remove obsolete backups manually so repeated first-write snapshots do not fill the disk.

如果数据库管理服务无法连接，先确认两个进程仍在运行、页面确实从 `localhost:3000` 打开、API 地址是 loopback HTTP 地址，并重新复制当前服务进程输出的 token。不要通过降低 CORS、关闭 token 验证或绑定公网地址来规避连接问题。
