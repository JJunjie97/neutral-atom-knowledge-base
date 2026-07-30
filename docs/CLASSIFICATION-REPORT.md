# 分类快照质量报告

本报告对应 taxonomy `2026.07.30.5` 和 2026-07-30 生成的本地数据库快照。

## 总体结果

- 17 个静态维度、159 个双语类别、159 条确定性规则；
- 另有 3 个数据驱动维度：`review_section`、`review_topic`、`venue`，网页共展示 20 个维度；
- 14,073 个数据库实体中，3,309 个获得至少一个具体规则标签，共 4,669 条规则 assignments；
- 叠加综述层级和 publication venue 后，图中的 14,072 个节点有 11,938 个至少带一个 facet，覆盖率 84.84%；
- 637 个综述核心实体全部带有可筛选 facet，其中 619 个获得至少一个具体规则标签；
- 1,089 个综述 citation mentions 已全部关联，覆盖 630 个 citation keys；BibLaTeX `ids` 别名已映射，未解析 mention 为 0，歧义别名为 0；
- 637 个核心实体各有独立的公开 classification shard；其中不包含摘要、综述上下文原文或论文全文。

“84.84%”包含 venue 元数据，不能解释为 84.84% 的论文已经获得完整技术标注。更有意义的技术规则覆盖是 3,309 个实体；核心文献的初始规则覆盖为 619/637。

## 核心文献维度覆盖

| 维度 | 核心实体数 |
|---|---:|
| venue | 611 |
| review_section | 602 |
| review_domain | 586 |
| review_topic | 566 |
| physical_platform | 110 |
| qec_code | 82 |
| qec_technique | 80 |
| platform_architecture | 56 |
| control_and_operation | 50 |
| application | 49 |
| interaction_and_gate | 47 |
| photonics | 46 |
| isotope | 41 |
| networking | 34 |
| qubit_encoding | 29 |
| computing_mode | 29 |
| readout_and_noise | 28 |
| decoder | 23 |
| atomic_element | 21 |
| compilation_stage | 6 |

低数量不一定表示缺陷。例如元素标签刻意只接受论文自身标题/摘要中的明确元素名，避免综述一句话比较 Rb/Cs/Sr/Yb 时把四种元素错误地赋给每个 citation。随着本地 Markdown 全文和摘要覆盖增加，这些高精度维度会自然扩展。

## 已检查并处理的误判

- `Rydberg` 激发或阻塞不会自动等于 Rydberg qubit encoding；circular Rydberg encoding 要求明确的 qubit/encoding/computing 表述。
- Rb、Cs、Sr、Yb 的元素缩写使用大小写敏感匹配，避免普通英文词片段误命中。
- LiNbO3/TFLN 和 LiTaO3/TFLT 只进入 photonics material，不产生 Li 原子标签。
- neutral atom、trapped ion、superconducting 和 photonic quantum computing 是独立 physical-platform 类别。
- 应用标签不再从综述共享上下文推断；transport dynamics 也不采用过宽的 OpenAlex transport topic。
- 综述上下文从整段缩小到 citation 所在句；表格仍按行提取。
- `Phys. Rev. Lett.` / `Physical Review Letters`、`Phys. Rev. X` / `Physical Review X`、arXiv 等常见 venue 别名已规范化。
- 自动分类升级会替换旧版本规则标签，但保留 `manual` 人工确认标签；`--seed-only` 不会删除外部参考论文的标签。

## 仍需人工与全文增强的部分

- 期刊规范化目前覆盖常见别名，不是完整的 ISSN/ROR 级 venue authority file。
- 少量宽泛 OpenAlex topics 仍只应作为低权重证据；网页会显示其 method、confidence 和 signals。
- 当前本地可再分发摘要很少，因此一些标题不包含技术细节的论文只能使用综述章节或较粗粒度 topic。
- 综述章节是强监督来源，但不是论文唯一主题；跨章节、多元素和多技术路线必须保持多标签。
- 下一阶段应在 Markdown 全文建立后增加“候选标签”管线，并把人工确认结果写为 `manual`，而不是静默覆盖确定性结果。

复现命令：

```powershell
python -m neutral_atom_graph classify
python -m neutral_atom_graph export
python apps/atlas/scripts/prepare_data.py
```
