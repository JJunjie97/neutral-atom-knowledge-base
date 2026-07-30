# 论文下载、归档与 Markdown 流程

## 1. 文件先进入 inbox

新下载的 PDF、HTML、LaTeX 或补充材料先放入 `library/inbox/`。不要直接按题目创建文件夹：题目会变化、可能重名，也不适合作为跨平台路径。

## 2. 匹配数据库实体

优先按 DOI，其次按 arXiv、OpenAlex，最后才使用题目与作者匹配。确认后读取该实体的稳定 `paper_uid`：

```powershell
python -m neutral_atom_graph get-work 10.1103/PhysRevLett.123.123456
```

若数据库没有该论文，先创建或补充 `paper.json`，再运行 `sync-library`。不要把不确定的文件强行绑定；以后可通过 `metadata_candidates` 审核队列处理。

## 3. 归档目录

```text
library/papers/<scheme>/<shard>/<identifier>/
├── paper.json
├── original/
├── source/
├── markdown/
└── assets/
```

`paper.json` 至少包含一个外部标识符，并逐项记录文件类型、相对路径、语言、来源、许可证和是否允许再分发。运行：

```powershell
python -m neutral_atom_graph sync-library
```

系统会计算 SHA-256 和文件大小，将本地文档与不可变 `paper_uid` 关联。

## 4. 转为规范 Markdown

推荐主文件为 `markdown/paper.md`。转换器可选 GROBID、MinerU、Nougat 或其他工具，但输出应尽量保留：

- 标题层级与章节编号；
- 公式、图、表及其编号；
- 正文引用标记；
- 参考文献列表；
- 原始页码或可追溯锚点；
- 转换工具、版本和时间等 provenance。

图片和表格资源放入 `assets/`，Markdown 使用相对路径。转换后再次 `sync-library`，然后建立全文索引：

```powershell
python -m neutral_atom_graph index-markdown
python -m neutral_atom_graph search-library "Rydberg blockade"
```

## 5. 生成总目录和图索引

```powershell
python -m neutral_atom_graph build-catalog
python -m neutral_atom_graph export
python apps/atlas/scripts/prepare_data.py
```

`data/catalog/papers.jsonl` 适合 AI 批量读取；`papers.csv` 适合人工审查；`seed-catalog.md` 是综述核心文献总目录。全文不塞入星图 JSON，而是按论文按需读取，避免网页和 AI 上下文无限膨胀。

## 6. 许可与 Git

PDF、论文源码、转换全文和摘要分片默认被 `.gitignore` 排除。只有确认许可证允许本项目再次分发后，才应调整对应 manifest 和 Git 规则。公开仓库始终可以只保存代码、manifest、引用图快照和可重建索引；本地文件不会因此被删除。
