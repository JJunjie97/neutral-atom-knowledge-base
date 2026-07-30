# AI Access

## 当前可用

本地 Markdown 可以被切分并写入 SQLite FTS5：

```powershell
python -m neutral_atom_graph sync-library
python -m neutral_atom_graph index-markdown
python -m neutral_atom_graph search-library "fault-tolerant neutral atom compilation"
python -m neutral_atom_graph build-catalog
python -m neutral_atom_graph get-work paper-00000001
python -m neutral_atom_graph neighbors paper-00000001 --direction both
```

搜索结果包含：

- `paper_uid` 与外部标识符
- 论文题目
- Markdown 相对路径
- 章节标题和 chunk 序号
- 可直接引用的正文片段

这使 AI 可以先检索证据，再沿引用图扩展相关论文，而不是把整个文库一次性塞进上下文。

`build-catalog` 生成三种互补入口：

- `papers.jsonl`：每行一个实体，包含稳定身份、外部标识符、元数据质量、文档路径和图内入/出度；
- `papers.csv`：适合人工筛选和数据质量审查；
- `seed-catalog.md`：综述核心文献的可读总目录。

`get-work` 与 `neighbors` 使用 `paper_uid`、DOI、arXiv 或 OpenAlex ID 均可调用，因此已经可以作为本地 AI 工具的稳定底层接口。缺失题名不会被编造；返回值同时包含 `title_missing` 与 `metadata_status`。

## 推荐检索流程

```text
用户问题
  ├── 关键词 / FTS 召回
  ├── 选中论文的一跳引用扩展
  ├── 向量重排（后续）
  ├── 读取少量章节原文
  └── 返回答案 + paper_uid + 章节来源
```

## 计划中的 MCP 接口

- `search_knowledge(query, filters)`
- `get_work(paper_uid)`
- `get_document(paper_uid, section)`
- `citation_neighbors(paper_uid, direction, depth)`
- `trace_claim(chunk_id)`

MCP 服务应只读取本地数据库和已授权全文，不向公开网页暴露 API key 或受版权保护的文件。
