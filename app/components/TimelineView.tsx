"use client";

import { ArrowRight, CalendarDays } from "lucide-react";
import { useMemo, useState } from "react";
import { authorLine, formatNumber, nodeDegree } from "../graph-utils";
import type { GraphData } from "../types";

type Props = {
  data: GraphData;
  visibleIndices: number[];
  onSelect: (index: number) => void;
};

export default function TimelineView({
  data,
  visibleIndices,
  onSelect,
}: Props) {
  const colorMap = useMemo(
    () => new Map(data.sections.map((section) => [section.id, section.color])),
    [data.sections],
  );
  const years = useMemo(() => {
    const counts = new Map<number, number>();
    for (const index of visibleIndices) {
      const year = data.nodes[index].year;
      if (year) counts.set(year, (counts.get(year) ?? 0) + 1);
    }
    return Array.from(
      { length: data.meta.yearMax - data.meta.yearMin + 1 },
      (_, offset) => data.meta.yearMin + offset,
    ).map((year) => ({ year, count: counts.get(year) ?? 0 }));
  }, [data.meta.yearMax, data.meta.yearMin, data.nodes, visibleIndices]);

  const latestVisibleYear = useMemo(
    () =>
      [...years]
        .reverse()
        .find((item) => item.count > 0)?.year ?? data.meta.yearMax,
    [data.meta.yearMax, years],
  );
  const [selectedYear, setSelectedYear] = useState(latestVisibleYear);

  const activeYear = years.some(
    (item) => item.year === selectedYear && item.count > 0,
  )
    ? selectedYear
    : latestVisibleYear;

  const yearPapers = useMemo(
    () =>
      visibleIndices
        .filter((index) => data.nodes[index].year === activeYear)
        .sort((left, right) => {
          const degreeDiff =
            nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]);
          if (degreeDiff) return degreeDiff;
          return (
            (data.nodes[right].citations ?? 0) -
            (data.nodes[left].citations ?? 0)
          );
        }),
    [activeYear, data.nodes, visibleIndices],
  );

  const maxCount = Math.max(...years.map((item) => item.count), 1);
  const chartWidth = 1000;
  const chartHeight = 224;
  const paddingX = 34;
  const usableWidth = chartWidth - paddingX * 2;
  const barWidth = Math.max(4, usableWidth / years.length - 4);

  return (
    <section className="timeline-view">
      <div className="view-intro">
        <div>
          <p className="eyebrow">CHRONOLOGY</p>
          <h2>从基础物理到规模化计算</h2>
        </div>
        <p>
          柱高表示当前筛选条件下的论文数量。点击年份，查看当年的关键节点与引用影响。
        </p>
      </div>

      <div className="timeline-chart-card">
        <div className="timeline-chart-header">
          <div>
            <span className="timeline-kicker">YEAR LENS</span>
            <strong>{activeYear}</strong>
          </div>
          <span>{formatNumber(yearPapers.length)} 篇匹配文献</span>
        </div>
        <svg
          aria-label="按年份统计的文献时间线"
          className="timeline-chart"
          role="img"
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
        >
          <line
            className="timeline-axis"
            x1={paddingX}
            x2={chartWidth - paddingX}
            y1={185}
            y2={185}
          />
          {years.map(({ year, count }, offset) => {
            const x =
              paddingX + (offset / Math.max(years.length - 1, 1)) * usableWidth;
            const height =
              count === 0
                ? 2
                : 12 + (Math.sqrt(count) / Math.sqrt(maxCount)) * 142;
            const selected = year === activeYear;
            return (
              <g
                className={`timeline-bar ${selected ? "is-selected" : ""}`}
                key={year}
                onClick={() => count > 0 && setSelectedYear(year)}
                role="button"
                tabIndex={count > 0 ? 0 : -1}
                onKeyDown={(event) => {
                  if (
                    count > 0 &&
                    (event.key === "Enter" || event.key === " ")
                  ) {
                    setSelectedYear(year);
                  }
                }}
              >
                <title>
                  {year}: {count} 篇
                </title>
                <rect
                  height={height}
                  rx={barWidth / 2}
                  width={barWidth}
                  x={x - barWidth / 2}
                  y={185 - height}
                />
                {(year % 5 === 0 || selected) && (
                  <text
                    className="timeline-year-label"
                    textAnchor="middle"
                    x={x}
                    y={208}
                  >
                    {year}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      <div className="year-browser">
        <div className="year-browser-heading">
          <div className="year-badge">
            <CalendarDays size={18} />
            {activeYear}
          </div>
          <div>
            <h3>年度关键文献</h3>
            <p>按核心网络连接度与 OpenAlex 被引数排序</p>
          </div>
        </div>

        {yearPapers.length ? (
          <div className="timeline-paper-list">
            {yearPapers.slice(0, 80).map((index, rank) => {
              const node = data.nodes[index];
              return (
                <button
                  className="timeline-paper"
                  key={node.id}
                  onClick={() => onSelect(index)}
                  type="button"
                >
                  <span className="paper-rank">
                    {String(rank + 1).padStart(2, "0")}
                  </span>
                  <span
                    className="paper-color"
                    style={{
                      background: colorMap.get(node.group) ?? "#7F8DA8",
                    }}
                  />
                  <span className="paper-main">
                    <strong>{node.title}</strong>
                    <small>
                      {authorLine(node.authors)} · {node.venue ?? "来源未知"}
                    </small>
                  </span>
                  <span className="paper-metrics">
                    <small>网络连接</small>
                    <strong>{formatNumber(nodeDegree(node))}</strong>
                  </span>
                  <ArrowRight size={16} />
                </button>
              );
            })}
            {yearPapers.length > 80 && (
              <p className="list-limit-note">
                已显示连接度最高的 80 篇；继续使用左侧筛选器缩小范围。
              </p>
            )}
          </div>
        ) : (
          <div className="empty-state">
            当前年份没有符合筛选条件的文献。
          </div>
        )}
      </div>
    </section>
  );
}
