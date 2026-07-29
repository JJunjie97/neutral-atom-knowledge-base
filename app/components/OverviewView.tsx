"use client";

import {
  ArrowUpRight,
  BookOpen,
  CalendarRange,
  GitFork,
  Network,
} from "lucide-react";
import { useMemo } from "react";
import { authorLine, formatNumber, nodeDegree } from "../graph-utils";
import type { GraphData } from "../types";

type Props = {
  data: GraphData;
  visibleIndices: number[];
  onSelect: (index: number) => void;
};

export default function OverviewView({
  data,
  visibleIndices,
  onSelect,
}: Props) {
  const visibleNodes = useMemo(
    () => visibleIndices.map((index) => data.nodes[index]),
    [data.nodes, visibleIndices],
  );
  const sectionStats = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of visibleNodes) {
      counts.set(node.group, (counts.get(node.group) ?? 0) + 1);
    }
    return data.sections
      .map((section) => ({
        ...section,
        count: counts.get(section.id) ?? 0,
      }))
      .filter((section) => section.count > 0)
      .sort((left, right) => right.count - left.count);
  }, [data.sections, visibleNodes]);
  const topPapers = useMemo(
    () =>
      [...visibleIndices]
        .sort(
          (left, right) =>
            nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]),
        )
        .slice(0, 12),
    [data.nodes, visibleIndices],
  );
  const maxSectionCount = Math.max(
    ...sectionStats.map((section) => section.count),
    1,
  );
  const visibleEdges = useMemo(() => {
    const mask = new Uint8Array(data.nodes.length);
    visibleIndices.forEach((index) => {
      mask[index] = 1;
    });
    return data.edges.reduce(
      (count, [source, target]) =>
        count + (mask[source] && mask[target] ? 1 : 0),
      0,
    );
  }, [data.edges, data.nodes.length, visibleIndices]);
  const years = visibleNodes
    .map((node) => node.year)
    .filter((year): year is number => year != null);
  const yearSpan = years.length
    ? `${Math.min(...years)}—${Math.max(...years)}`
    : "年份未知";

  return (
    <section className="overview-view">
      <div className="view-intro">
        <div>
          <p className="eyebrow">ATLAS OVERVIEW</p>
          <h2>数据库结构概览</h2>
        </div>
        <p>
          指标会随左侧筛选条件实时变化，便于快速判断一个主题、年代或关键词在整体网络中的位置。
        </p>
      </div>

      <div className="metric-grid">
        <article className="metric-card">
          <span className="metric-icon">
            <BookOpen size={19} />
          </span>
          <small>当前文献</small>
          <strong>{formatNumber(visibleIndices.length)}</strong>
          <p>占当前数据集 {Math.round((visibleIndices.length / data.nodes.length) * 100)}%</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon">
            <GitFork size={19} />
          </span>
          <small>筛选内引用边</small>
          <strong>{formatNumber(visibleEdges)}</strong>
          <p>有向边：引用者 → 被引文献</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon">
            <CalendarRange size={19} />
          </span>
          <small>时间跨度</small>
          <strong className="metric-year">{yearSpan}</strong>
          <p>{formatNumber(data.meta.unknownYear)} 篇缺少年份</p>
        </article>
        <article className="metric-card">
          <span className="metric-icon">
            <Network size={19} />
          </span>
          <small>综述收录文献</small>
          <strong>
            {formatNumber(visibleNodes.filter((node) => node.seed).length)}
          </strong>
          <p>综述 BibTeX 去重后的文献实体</p>
        </article>
      </div>

      <div className="overview-columns">
        <article className="overview-panel">
          <div className="panel-heading">
            <div>
              <span className="timeline-kicker">TOPICS</span>
              <h3>综述章节分布</h3>
            </div>
            <small>{sectionStats.length} 个主题簇</small>
          </div>
          <div className="section-bars">
            {sectionStats.map((section) => (
              <div className="section-bar-row" key={section.id}>
                <div>
                  <span
                    className="legend-swatch"
                    style={{ background: section.color }}
                  />
                  <span>{section.label}</span>
                  <strong>{formatNumber(section.count)}</strong>
                </div>
                <span className="bar-track">
                  <span
                    className="bar-fill"
                    style={{
                      background: section.color,
                      width: `${(section.count / maxSectionCount) * 100}%`,
                    }}
                  />
                </span>
              </div>
            ))}
          </div>
        </article>

        <article className="overview-panel">
          <div className="panel-heading">
            <div>
              <span className="timeline-kicker">NETWORK RANKING</span>
              <h3>Most Connected Papers</h3>
            </div>
            <small>Ranked by graph degree</small>
          </div>
          <div className="hub-list">
            {topPapers.map((index, rank) => {
              const node = data.nodes[index];
              return (
                <button
                  key={node.id}
                  onClick={() => onSelect(index)}
                  type="button"
                >
                  <span>{rank + 1}</span>
                  <span>
                    <strong>{node.title}</strong>
                    <small>
                      {node.year ?? "年份未知"} · {authorLine(node.authors, 2)}
                    </small>
                  </span>
                  <span className="hub-degree">{nodeDegree(node)}</span>
                  <ArrowUpRight size={15} />
                </button>
              );
            })}
          </div>
        </article>
      </div>
    </section>
  );
}
