# 中性原子量子计算 · 文献星图

这是知识库的纯静态浏览器界面。它提供核心文献/完整网络、无限缩放画布、时间线、数据概览、单篇文献局部星图和按需摘要，不直接读取 SQLite，也不包含 API key。

## 主要功能

- 637 个综述核心实体及其互引关系；
- 14,000+ 个完整图实体和 30,000+ 条引用边；
- 标题、作者、DOI、arXiv、OpenAlex、BibTeX key 搜索；
- 章节、年份、graph degree 与元数据状态筛选；
- 点击论文查看入边、出边，并切换 1-hop / 2-hop 局部星图；
- 缺题名节点使用唯一外部 ID，不伪造“未命名文献”；
- 摘要按论文静态分片加载，必要时再回退 OpenAlex；
- 支持 Chrome 内置英文 → 中文题目/摘要翻译，结果只缓存在当前浏览器。

## 更新数据

先在仓库根目录运行：

```powershell
python -m neutral_atom_graph export
python apps/atlas/scripts/prepare_data.py
```

脚本读取：

- `data/exports/seed_graph.json`
- `data/exports/graph.json`

并生成：

- `apps/atlas/public/data/core-graph.json`
- `apps/atlas/public/data/full-graph.json`
- `apps/atlas/public/data/papers/<paper_uid>.json`（仅有本地摘要时；默认不提交）

图布局在构建前离线计算。全文不会放进单个 graph JSON，以免 GitHub Pages 下载体积随文库无限增长。摘要分片只有在确认再分发许可后才应提交；否则网页会按需回退到 OpenAlex。

## 本地运行

需要 Node.js 22.13+；重新生成图数据还需要 Python 和项目的 `atlas` 可选依赖。

```powershell
# 仓库根目录
python -m pip install -e ".[atlas]"

cd apps/atlas
npm ci
npm run dev
```

打开 `http://127.0.0.1:3000`。静态发布前验证：

```powershell
npm run lint
npm run test:pages
```

模拟 GitHub 项目子路径：

```powershell
$env:PAGES_BASE_PATH = "/neutral-atom-knowledge-base"
npm run test:pages
```

## GitHub Pages

网页使用 Next.js `output: "export"`。推送仓库后，在 GitHub 的 **Settings → Pages → Source** 选择 **GitHub Actions**；根目录的 `.github/workflows/pages.yml` 会构建 `apps/atlas/out` 并发布。`basePath` 由 GitHub 自动注入，因此在用户名主页和项目子路径中都能正确加载脚本、图片和图数据。

翻译功能依赖支持 Translator API 的桌面版 Chrome（界面会在不支持时给出说明）。它在用户设备本地运行，不会把 API key 放入静态网页。
