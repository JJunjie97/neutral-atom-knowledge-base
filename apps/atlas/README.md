# 中性原子量子计算 · 文献星图

这是知识库的纯静态浏览器界面。它提供核心文献/完整网络、无限缩放画布、时间线、数据概览、单篇文献局部星图和按需摘要，不直接读取 SQLite，也不包含 API key。

## 主要功能

- 637 个综述核心实体及其互引关系；
- 14,000+ 个完整图实体和 30,000+ 条引用边；
- 标题、作者、DOI、arXiv、OpenAlex、BibTeX key 与分类中英文搜索；
- 原子元素/同位素、平台架构、计算模式、具体技术、QEC、编译、光子、网络、应用、venue 与综述层级等多维筛选；
- 同一分类维度内取并集（OR），不同维度间取交集（AND），并显示计数和 active chips；
- 点击论文查看分类置信度、规则 signals 与综述引用位置，以及入边、出边和 1-hop / 2-hop 局部星图；
- 关系星图按“引用者 → 被引用文献”表达原始引用，年份分层的发展脉络则按“被引用文献 → 后续引用工作”展示推导出的发展方向；
- 缺题名节点使用唯一外部 ID，不伪造“未命名文献”；
- 摘要按论文静态分片加载，必要时再回退 OpenAlex；
- 支持 Chrome 内置英文 → 中文题目/摘要翻译，结果只缓存在当前浏览器。
- 本地 `/admin/` 管理页可连接 loopback Python API 校对原始题录；GitHub Pages 上保持静态只读。

两种方向的严格语义、同年/逆序/未知年份的布局规则、当前一层参考网络的数据边界和未来递归抓取路线，见 [引用星图与发展脉络的可视化语义](../../docs/VISUALIZATION.md)。

## 更新数据

先在仓库根目录运行：

```powershell
python -m neutral_atom_graph classify
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
- `apps/atlas/public/data/classifications/<paper_uid>.json`（仅 637 篇综述核心文献的公开分类依据）

图布局在构建前离线计算。全文和分类依据不会放进单个 graph JSON，以免 GitHub Pages 下载体积随文库无限增长。`papers/` 摘要分片只有在确认再分发许可后才应提交；`classifications/` 分片可提交，但只包含 taxonomy assignments、置信度、规则 signals 与综述 heading，不包含摘要、上下文摘录或全文。

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

## 本地数据库管理

管理原始 SQLite 时，在仓库根目录另开一个 PowerShell：

```powershell
python -m neutral_atom_graph admin --host 127.0.0.1 --port 8765
```

保持 `npm run dev` 运行，然后打开 `http://localhost:3000/admin/`，填写 `http://127.0.0.1:8765` 和 Python 服务输出的临时 token。token 只存于当前浏览器会话的 `sessionStorage`，不会进入静态资源。

第一版用于修改受控的题录字段和人工分类；标识符映射、引用边、种子 BibTeX、provider 原始记录、自动分类、论文文件与原始 JSON 保持只读。第一次写入前会通过 SQLite online backup 在 `data/backups/` 建立一致快照，所有成功修改写入审计表；并发版本不一致时返回冲突而不是覆盖。完整说明见 [本地数据库管理](../../docs/DATABASE-ADMIN.md)。

## GitHub Pages

网页使用 Next.js `output: "export"`。推送仓库后，在 GitHub 的 **Settings → Pages → Source** 选择 **GitHub Actions**；根目录的 `.github/workflows/pages.yml` 会构建 `apps/atlas/out` 并发布。`basePath` 由 GitHub 自动注入，因此在用户名主页和项目子路径中都能正确加载脚本、图片和图数据。

GitHub Pages 上的 `/admin/` 是静态说明页，不拥有 SQLite、管理 token 或服务端写权限。修改原始数据必须从 `http://localhost:3000/admin/` 连接只监听本机回环地址的管理 API。

翻译功能依赖支持 Translator API 的桌面版 Chrome（界面会在不支持时给出说明）。它在用户设备本地运行，不会把 API key 放入静态网页。
