# Architecture

## 1. 四层数据模型

1. **Bibliographic layer**：`works`、`identifiers`、作者、题目、摘要和来源。
2. **Graph layer**：`citations` 保存有方向、有来源的引用关系。
3. **Document layer**：`documents` 把数据库实体连接到 PDF、LaTeX、HTML 和 Markdown。
4. **Knowledge layer**：`document_chunks` 与 FTS5 保存可引用的章节片段，后续可附加向量嵌入。

```text
identifier ──> work ──> citation graph
                  │
                  └──> document ──> chunks ──> FTS / embeddings / AI
```

## 2. 稳定身份

`canonical_id` 会在后续发现 DOI 时改变，因此不能作为永久文件夹主键。数据库为每个 work 维护不可变的 `paper_uid`。外部标识符仍保存在 `identifiers`，用于匹配、合并和生成可读 URL。

论文文件夹使用人类可读的来源标识分片，但数据库最终以 `documents.work_id` 与 `paper_uid` 为准。移动文件后运行 `sync-library` 会重新计算路径、大小和 SHA-256。

## 3. 数据流

```text
BibTeX / TeX
    │
    ▼
SQLite works + seed_entries
    │
    ├── OpenAlex / Crossref metadata
    ├── citations
    ├── local documents
    └── Markdown chunks + FTS5
             │
             ├── CLI search
             ├── future MCP/RAG service
             └── static per-paper detail shards
```

## 4. 网页发布

`apps/atlas` 只消费经过裁剪的静态 JSON，不读取 SQLite，也不包含 API key。GitHub Pages 构建使用仓库子路径感知的静态导出。摘要和未来全文按论文分片，避免把全部内容塞入单个 `full-graph.json`。

## 5. 后续扩展

- GROBID / Nougat / MinerU：PDF 到结构化 Markdown。
- 章节级引文对齐：把正文中的参考标号映射回 `works`。
- 混合检索：FTS5 + citation expansion + embedding rerank。
- MCP 服务：向编码助手提供 `search`, `get_paper`, `neighbors`, `trace_evidence`。
- 数据质量队列：缺题目、低置信匹配、缺全文和许可证待核查。
