# 当前状态

更新时间：2026-07-30

## 已完成

- 项目已从综述论文目录迁出，成为独立 Git 仓库。
- 综述源码、PDF、未来 Markdown 与资源已归入 `library/papers/arxiv/2607/2607.21554/`。
- 659 条 BibTeX 种子记录归并为 637 个种子实体。
- 数据库包含 14,073 个实体、30,111 条引用边、4,118 条种子到种子引用边。
- 608 个种子实体已关联 OpenAlex；题录匹配结果为 accepted 579、needs_review 27、not_found 2。
- 数据库有不可变 `paper_uid`、文档 manifest、SHA-256、Markdown chunk、FTS5 和元数据候选表。
- 实现 OpenAlex 精确 DOI 与 Crossref 题名修复，并保留来源与状态。
- 实现星图、时间线、单篇局部引用图、题目/摘要翻译及元数据缺失筛选。
- 网页已改为 Next.js 静态导出，可由 GitHub Actions 发布到 GitHub Pages。
- Python 回归测试覆盖解析、恢复、迁移、全文索引和导出契约。

## 缺失题名的含义

当前 1,583 个外部参考实体没有可靠题名。绝大部分是 OpenAlex 已删除或无法返回元数据的引用 ID；它们仍有真实引用边，因此不会删除，也不会伪造题名。界面使用外部 ID 或 `paper_uid` 唯一标识，并允许默认隐藏。后续可从下载的 PDF/Markdown 参考文献字符串、GROBID 输出或其他可信来源恢复。

## 推荐日常命令

```powershell
python -m neutral_atom_graph sync-library
python -m neutral_atom_graph index-markdown
python -m neutral_atom_graph build-catalog
python -m neutral_atom_graph export
python apps/atlas/scripts/prepare_data.py
```

人工质量审查重点：

- `matches.status = 'needs_review'` 的 27 条种子匹配；
- `metadata_status` 为 `unresolved_reference` 或 `no_title` 的节点；
- `documents.status` 为 `missing` 的 manifest 文件；
- 新下载全文的许可证、哈希和论文实体匹配。

## 下一阶段

1. 批量获取允许下载的 PDF/LaTeX，并通过 inbox 工作流归档。
2. 建立可追溯的 PDF → Markdown 转换流水线。
3. 对齐正文引用标记、参考文献条目与引用图实体。
4. 在 FTS5 基础上加入 embedding rerank 与 MCP 服务。
5. 将大体积 SQLite/全文通过 GitHub Release、对象存储或本地挂载提供，而不是普通 Git。
