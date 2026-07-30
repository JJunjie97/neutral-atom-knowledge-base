# Neutral Atom Quantum Computing Knowledge Base

这是一个独立于综述论文源码的中性原子量子计算知识库。它把题录、引用关系、论文文件、Markdown 全文、全文检索和交互式星图放在同一套可追溯的数据模型中，目标是让研究人员和 AI 在算法开发、硬件分析、纠错、编译和文献核查时直接检索相关证据。

## 当前数据

- 659 条综述 BibTeX 种子记录
- 637 个去重后的种子文献实体
- 14,073 个知识实体（包含综述本身）
- 30,111 条引用边
- 4,118 条种子文献之间的引用边
- 1,583 个仅保留引用身份、暂无可靠题名的外部参考节点
- SQLite、OpenAlex 请求缓存和断点续传状态
- 星图、时间线、局部引用网络、中文题目与摘要翻译

## 目录

```text
.
├── apps/atlas/                 # 可发布到 GitHub Pages 的文献星图
├── src/neutral_atom_graph/     # 抓取、去重、导出和本地全文索引
├── taxonomy/                   # 多维分类定义、双语标签与可审计规则
├── tests/                      # Python 回归测试
├── library/
│   ├── inbox/                  # 新下载、尚未归档的论文
│   └── papers/                 # 数据库登记后的论文目录
├── data/
│   ├── database/               # 本地 SQLite；默认不进入 Git
│   ├── backups/                # 写入前的一致性快照；默认不进入 Git
│   ├── exports/                # 可重建的图数据；默认不进入 Git
│   └── catalog/                # AI 友好的 JSONL/CSV/Markdown 总目录
├── collections/                # 综述、专题或课程的种子集合
├── docs/                       # 架构、AI 接入和数据发布策略
└── .github/workflows/          # CI 与 GitHub Pages
```

每篇论文使用独立目录：

```text
library/papers/<identifier-scheme>/<shard>/<paper-id>/
├── paper.json                  # 标识符、标题、文件清单和许可证
├── original/                   # PDF/HTML/补充材料；默认不提交
├── source/                     # LaTeX 或其他公开源码
├── markdown/                   # 转换后的规范 Markdown；默认不提交
└── assets/                     # Markdown 使用的图片、表格和公式资源
```

数据库使用不可变 `paper_uid` 连接论文文件。DOI、arXiv 和 OpenAlex ID 可以补充或合并，但不会改变文件索引的内部身份。

## 快速开始

需要 Python 3.11+ 和 Node.js 22.13+。

```powershell
Copy-Item .env.example .env
python -m pip install -e ".[atlas]"

python -m neutral_atom_graph stats
python -m neutral_atom_graph sync-library
python -m neutral_atom_graph index-markdown
python -m neutral_atom_graph search-library "Rydberg blockade"
python -m neutral_atom_graph build-catalog
python -m neutral_atom_graph get-work paper-00000001
python -m neutral_atom_graph neighbors paper-00000001 --direction both
```

更新引用图：

```powershell
python -m neutral_atom_graph ingest
python -m neutral_atom_graph crawl-openalex
python -m neutral_atom_graph repair-metadata
python -m neutral_atom_graph classify
python -m neutral_atom_graph export

cd apps/atlas
python scripts/prepare_data.py
npm install
npm run dev
```

本地校对原始题录时，在仓库根目录另开一个 PowerShell 启动只监听回环地址的管理 API：

```powershell
python -m neutral_atom_graph admin --host 127.0.0.1 --port 8765
```

复制终端输出的临时 token，然后打开 `http://localhost:3000/admin/`。token 只进入当前浏览器会话的 `sessionStorage`；首次实际写入前会创建 SQLite online backup，成功修改会进入审计日志。可编辑字段、只读关系数据和恢复流程见 [本地数据库管理](docs/DATABASE-ADMIN.md)。

`classify` 会从本地 OpenAlex 缓存恢复 topics，解析综述中的 citation context 和章节路径，并生成元素/同位素、物理平台、架构、门与控制技术、QEC、编译、光子、网络、应用和 venue 等独立 facets。它不需要联网，并会持续输出处理进度；规则结果保留置信度和来源，人工标签不会被重跑覆盖。

原先界面中的“未命名文献”不会再被伪装成同名节点。没有可靠题名时，系统保留其 DOI、arXiv、OpenAlex 或稳定 `paper_uid`，显示为 `Metadata unavailable - <identifier>`；这类节点仍然承载真实引用边，可在网页中单独显示或隐藏。`private communication` 会作为非论文知识实体单独标记。

## GitHub Pages

`apps/atlas` 使用 Next.js 静态导出，不需要服务器或 API key。推送到 GitHub 后，在仓库 **Settings → Pages → Source** 选择 **GitHub Actions**；`.github/workflows/pages.yml` 会在 `main` 分支更新时构建并发布。网页路径会自动适配 `https://<user>.github.io/<repository>/`。

GitHub Pages 上的 `/admin/` 仅显示静态说明，不会也不能直接修改本地 SQLite。真正的数据管理只在 `http://localhost:3000/admin/` 与 loopback Python API 之间进行，数据库和 token 均不会进入 Pages 构建产物。

## GitHub 与数据边界

公开仓库只提交代码、manifest、测试和网页所需的精简图快照。以下内容默认不会提交：

- `data/database/literature.sqlite`
- `data/backups/` 中的数据库快照
- API 缓存和本地环境变量
- 未确认再分发许可证的 PDF
- 仅授权 arXiv 分发、或许可证尚未确认的论文源码
- 未确认再分发许可证的 Markdown 全文

因此，公开克隆包含可直接浏览的图快照和论文 manifest，但重新运行 `ingest` 前需要按 manifest 的 `source_url` 把综述源码放回对应 `source/` 目录。本机现有源码不会被删除，只是不进入 Git。

SQLite 当前超过 GitHub 普通 Git 的单文件限制，因此应通过 Release、对象存储或可重建快照发布，而不是直接提交。详细策略见 [docs/DATA-POLICY.md](docs/DATA-POLICY.md)。

## 文档

- [系统架构](docs/ARCHITECTURE.md)
- [AI 检索与接入](docs/AI-ACCESS.md)
- [本地数据库管理、安全写入与恢复](docs/DATABASE-ADMIN.md)
- [多维分类体系与证据模型](docs/CLASSIFICATION.md)
- [当前分类覆盖与误判审计报告](docs/CLASSIFICATION-REPORT.md)
- [引用方向与年份分层发展脉络](docs/VISUALIZATION.md)
- [论文下载、归档与 Markdown 流程](docs/PAPER-INGESTION.md)
- [数据与版权边界](docs/DATA-POLICY.md)
- [网页说明](apps/atlas/README.md)
