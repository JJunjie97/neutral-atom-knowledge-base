# 多维文献分类体系

星图中的“布局分区”只负责决定节点的初始位置和颜色，不再被当作论文的唯一主题。论文分类采用可多选、可追溯的 facets；同一篇论文可以同时属于某个原子体系、硬件架构、门机制、纠错码和应用方向。

## 分类维度

首版 taxonomy 覆盖以下维度：

- 综述引用位置：一级章节和完整标题路径；
- 原子体系：元素、同位素、neutral atom / trapped ion 等物理平台；
- 编码与架构：qubit encoding、tweezer/lattice、2D/3D、dual-species、zone-based、modular 等；
- 相互作用与门：Rydberg blockade、Förster resonance、cavity QED、single-/two-/multi-qubit gates 等；
- 控制、装载与读出：寻址、光束调制、transport/rearrangement、continuous reloading、fluorescence、QND、erasure 等；
- 计算模式：digital、analog、hybrid、fault-tolerant；
- QEC：code family、fault-tolerant technique、decoder；
- compilation、integrated photonics、networking 和 application；
- publication facets：期刊/会议、文献类型和年份。期刊是独立元数据筛选项，不用于推断技术主题。

正式定义位于 [`taxonomy/neutral_atom_taxonomy.json`](../taxonomy/neutral_atom_taxonomy.json)。类别包含稳定 ID、中英文名称、说明和确定性匹配规则，便于网页、数据库查询和 AI 工具共同使用。

## 证据和置信度

每条自动分类都保留来源，不只保存最终标签。主要证据按可靠性大致排序为：

1. 综述中的精确章节路径；
2. 论文在综述中的引用句或相邻上下文；
3. 论文标题和摘要；
4. OpenAlex topic 层级；
5. 期刊/文献类型元数据（仅用于 publication facets）。

导出结果包含分类方法、置信度、命中的字段和规则，以及可定位到综述源文件及标题路径的引用来源。网页只发布这些短证据，不发布综述段落或论文摘要全文。

自动规则是初始标注，不是假装绝对正确。规则重跑只替换 `deterministic_rule`、`review_hierarchy` 和 `venue_metadata` 结果，`manual` 人工审核标签会永久保留。

## 防误判原则

- 普通的 `Rydberg` 不等同于 “Rydberg qubit encoding”；后者要求明确的 circular Rydberg、Rydberg encoding 等表述。
- `lithium niobate` 和 `lithium tantalate` 是光子材料，不能据此标记 Li 原子。
- 综述 networking 表格中的 Ca⁺、Ba⁺、Cd⁺ 等结果必须标为 trapped-ion platform，不能混入 neutral-atom hardware。
- 期刊名称不承担科学主题分类。
- 一个引用段落可能同时引用多篇论文，因此上下文命中应低于论文标题/精确小节的可解释性，并保留证据供人工复核。

## 运行流程

在仓库根目录执行：

```powershell
python -m neutral_atom_graph classify
python -m neutral_atom_graph export
python apps/atlas/scripts/prepare_data.py
```

`classify` 会：

1. 从本地 OpenAlex `provider_records` 离线回填 topics，不发起网络请求；
2. 解析综述 TeX 的引用位置和章节路径；
3. 对数据库论文运行 taxonomy 规则；
4. 生成 review hierarchy 和 publication venue facets；
5. 原子化提交分类和 taxonomy manifest。

若本机没有综述 TeX 源码，可在已有 `review_mentions` 的数据库上使用 `--skip-review-sync`。只试跑 BibTeX 核心论文时可使用 `--seed-only`。

修改 taxonomy 规则时必须提升 `version`。同一 version 对应不同文件摘要会被拒绝，避免无意中改变历史分类含义。

## 后续扩展

当 PDF 转换为 Markdown 并建立全文索引后，可增加摘要/正文分类器、向量检索和 LLM 辅助建议。机器模型只能产生带模型版本、prompt、时间和证据片段的候选标签；高价值标签经人工确认后写为 `manual`，以便形成可持续维护的数据集。
