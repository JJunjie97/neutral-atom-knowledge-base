# Local Paper Library

`papers/` 只接收已经有 `paper.json` 的论文；新下载文件先放到 `inbox/`。

推荐流程：

1. 下载到 `library/inbox/`；
2. 用 DOI、arXiv 或 OpenAlex ID 匹配数据库 work；
3. 移入稳定论文目录；
4. 创建或更新 `paper.json`；
5. 运行 `python -m neutral_atom_graph sync-library`；
6. 转换为 `markdown/paper.md`；
7. 运行 `python -m neutral_atom_graph index-markdown`。

不要用标题作为文件夹名：标题会变化、可能重名，也不适合跨平台路径。不要把 `canonical_id` 当不可变主键；数据库的 `paper_uid` 才是稳定身份。
