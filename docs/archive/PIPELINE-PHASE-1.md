# 中性原子量子计算文献关系图（历史第一阶段）

这是第一阶段的数据管线：从综述的 `bibliography.bib` 出发，解析 659 条种子记录、合并重复条目，再匹配 OpenAlex 文献实体，获取每篇种子论文的参考文献，并建立可追溯的有向引用图。

当前实现只使用 Python 标准库，核心数据保存在 SQLite 中，网络请求会缓存，任务中断后可以续跑。原始论文、Markdown 全文和可视化界面属于后续阶段。

## 为什么先用 OpenAlex

- OpenAlex 数据为 CC0，适合构建可再分发的长期数据库。
- Work 实体直接提供 `referenced_works`，能建立 `citing -> cited` 的有向边。
- DOI 可批量精确匹配；没有 DOI 的条目再进行标题、年份和作者联合打分。
- 模糊匹配不会静默写入：低分或候选过近的结果进入 `needs_review`。

OpenAlex 当前要求 API key 才适合规模化使用。免费 key 每日额度足以完成本项目的一跳引用图；在 <https://openalex.org/settings/api> 获取后放入环境变量，不要写进代码或数据库。

## 快速开始

在本目录运行：

```powershell
$env:OPENALEX_API_KEY = "你的 key"
$env:LITGRAPH_EMAIL = "你的联系邮箱"

python -m neutral_atom_graph ingest
python -m neutral_atom_graph crawl-openalex
python -m neutral_atom_graph export
python -m neutral_atom_graph stats
```

第一次建议先跑小样本：

```powershell
python -m neutral_atom_graph crawl-openalex --limit-seeds 10
python -m neutral_atom_graph export
```

一条命令也可以完成全部流程：

```powershell
python -m neutral_atom_graph all
```

安装为命令行工具是可选的：

```powershell
python -m pip install -e .
neutral-atom-graph stats
```

## 主要输出

默认数据库为 `data/literature.sqlite`，默认导出目录为 `output/`。

- `graph.json`：去重后的种子实体及其一跳参考文献完整图。
- `seed_graph.json`：只保留去重后的种子实体及它们之间的引用边。
- `nodes.csv` / `edges.csv`：适合 pandas、Gephi、Cytoscape。
- `graph.graphml`：可直接导入 Gephi/Cytoscape。
- `timeline.csv`：按年份整理的种子文献时间线。
- `unresolved_seeds.csv`：未匹配或需要人工复核的种子条目。
- `report.json`：节点数、边数、解析覆盖率等质量指标。

引用边方向固定为：

```text
较新的引用论文  --cites-->  被引用的较早论文
```

## 数据库设计

SQLite 中最重要的表是：

- `works`：规范化文献实体。
- `identifiers`：DOI、arXiv、OpenAlex、BibTeX key 等别名到实体的映射。
- `seed_entries`：综述 BibTeX 条目、原字段和正文所在章节。
- `citations`：有向引用边，并保留数据来源。
- `matches`：种子文献匹配方法、分数、状态和证据。
- `provider_records`：外部数据源返回的原始 JSON。
- `api_cache`：请求缓存。
- `fetch_status`：分文献、分步骤的续跑状态。

数据库内部用整数外键保证合并安全；导出时使用 `doi:`、`arxiv:`、`openalex:` 等稳定字符串作为节点 ID。若一个 OpenAlex 占位节点后来发现 DOI 与种子文献相同，系统会合并实体并保留已有引用边。

## 质量控制

匹配优先级是：

1. DOI 精确匹配；
2. 规范化标题相似度；
3. 年份一致性；
4. 作者姓氏重叠；
5. 低分或前两名过近时进入人工复核。

全量完成后，首先检查：

```powershell
python -m neutral_atom_graph stats
Import-Csv output/unresolved_seeds.csv | Format-Table
```

运行测试：

```powershell
python -m unittest discover -s tests -v
```

## 当前边界

- 当前深度为一跳：只展开每个种子实体的参考文献，不递归展开所有参考节点的参考文献。
- OpenAlex 可能缺少某些出版商未开放或未解析的参考文献。
- `private communication` 等非论文 BibTeX 项会保留为种子节点，但不会强行匹配。
- 后续应引入 Semantic Scholar/Crossref 做差异对照和缺边补全，而不是覆盖 OpenAlex 结果；`citations.provider` 已为多源合并预留。
