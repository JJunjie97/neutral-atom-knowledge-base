# Data and Publication Policy

## 可以进入公开 Git 的内容

- 抓取和索引代码
- OpenAlex/Crossref 等可再分发题录
- 引用边和质量状态
- 论文 manifest、校验和与许可证字段
- GitHub Pages 所需的精简静态图数据
- 明确允许再分发的源码

## 默认只保留在本地的内容

- API key、邮箱和 `.env`
- SQLite 工作数据库与 API 缓存
- 未确认许可证的 PDF、补充材料和 Markdown 全文
- 向量索引及可从全文重建的大型产物

## 大文件

SQLite 和未来全文库会超过 GitHub 普通 Git 的限制。推荐：

1. GitHub Releases 发布带 SHA-256 的只读数据库快照；
2. 对象存储保存授权 PDF 与 Markdown；
3. 网页只发布图结构和按论文拆分的小型详情 JSON；
4. 本地通过 `paper.json` 和 `documents` 表恢复完整路径。

Git LFS 可以保存大文件，但 GitHub Pages 不应把 LFS 指针当网页运行时数据。

## 许可证

`paper.json` 的每个 document 可以单独填写 `license` 与 `redistributable`。未知许可证默认视为不可公开分发。摘要也可能受出版商或作者版权约束，因此公开快照应保留来源并按实际授权决定是否发布。
