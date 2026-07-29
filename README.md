# 中性原子量子计算 · 文献星图

基于 `literature_graph/output` 导出结果构建的交互式可视化站点。

## 已实现

- 637 篇综述核心文献的稳定力导向星图
- 14,072 篇文献、30,111 条引用边的按需完整网络
- 标题、作者、DOI、arXiv、OpenAlex 与 BibTeX key 搜索
- 章节主题、年份、最小连接度筛选
- 1977–2026 年交互式时间线
- 主题分布、网络枢纽和动态统计概览
- 文献详情、入边/出边关系与原始记录外链
- 桌面端与移动端响应式界面

## 更新数据

先在上一级项目中重新执行爬取与导出，然后运行：

```powershell
python scripts\prepare_data.py
```

脚本读取：

- `../output/seed_graph.json`
- `../output/graph.json`

并生成：

- `public/data/core-graph.json`
- `public/data/full-graph.json`

布局会离线预计算，因此用户打开页面时不需要在浏览器内重新执行昂贵的力导向迭代。

## 本地运行

需要 Node.js 22.13 或更高版本。

```powershell
npm install
npm run dev
```

然后打开 `http://127.0.0.1:3000`。生产验证：

```powershell
npm run lint
npm test
```

## 交互说明

- 星图：拖拽平移，滚轮缩放，点击节点查看详情
- 数据范围：默认加载核心网络，完整网络仅在选择后加载
- 时间线：点击年份查看年度关键文献
- 数据概览：指标会随左侧筛选条件实时变化
