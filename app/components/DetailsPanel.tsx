"use client";

import {
  ArrowDownLeft,
  ArrowUpRight,
  BookOpenText,
  ExternalLink,
  GitCommitHorizontal,
  Network,
  X,
} from "lucide-react";
import { useMemo } from "react";
import {
  authorLine,
  formatNumber,
  nodeDegree,
  safeExternalUrl,
} from "../graph-utils";
import type { GraphData } from "../types";

type Props = {
  data: GraphData;
  isIsolatedRoot: boolean;
  selectedIndex: number | null;
  onClose: () => void;
  onIsolate: (index: number) => void;
  onSelect: (index: number) => void;
};

export default function DetailsPanel({
  data,
  isIsolatedRoot,
  selectedIndex,
  onClose,
  onIsolate,
  onSelect,
}: Props) {
  const relations = useMemo(() => {
    if (selectedIndex == null) return { incoming: [], outgoing: [] };
    const incoming: number[] = [];
    const outgoing: number[] = [];
    for (const [source, target] of data.edges) {
      if (source === selectedIndex) outgoing.push(target);
      if (target === selectedIndex) incoming.push(source);
    }
    const rank = (left: number, right: number) =>
      nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]);
    return {
      incoming: incoming.sort(rank),
      outgoing: outgoing.sort(rank),
    };
  }, [data, selectedIndex]);

  if (selectedIndex == null) return null;
  const node = data.nodes[selectedIndex];
  const section = data.sections.find((item) => item.id === node.group);
  const externalUrl =
    safeExternalUrl(node.oaUrl) ??
    safeExternalUrl(node.url) ??
    (node.doi
      ? safeExternalUrl(`https://doi.org/${node.doi}`)
      : null);
  const openAlexUrl = node.openalex
    ? `https://openalex.org/${node.openalex}`
    : null;

  return (
    <aside className="details-panel" aria-label="文献详情">
      <div className="details-header">
        <div className="details-label">
          <span
            className="legend-swatch"
            style={{ background: section?.color ?? "#7F8DA8" }}
          />
          {section?.label ?? "未分类"}
        </div>
        <button
          aria-label="关闭详情"
          className="icon-button"
          onClick={onClose}
          title="关闭"
          type="button"
        >
          <X size={17} />
        </button>
      </div>

      <div className="details-scroll">
        <p className="details-year">{node.year ?? "年份未知"}</p>
        <h2>{node.title}</h2>
        <p className="details-authors">{authorLine(node.authors, 8)}</p>
        <p className="details-venue">{node.venue ?? "来源信息缺失"}</p>

        <div className="details-metrics">
          <div>
            <span>Graph degree</span>
            <strong>{formatNumber(nodeDegree(node))}</strong>
          </div>
          <div>
            <span>Cited by (OpenAlex)</span>
            <strong>{formatNumber(node.citations)}</strong>
          </div>
          <div>
            <span>References</span>
            <strong>{formatNumber(node.references)}</strong>
          </div>
        </div>

        <button
          className="isolate-map-button"
          onClick={() => onIsolate(selectedIndex)}
          type="button"
        >
          <Network size={17} />
          <span>
            <strong>
              {isIsolatedRoot
                ? "Return to full graph"
                : "Open local citation map"}
            </strong>
            <small>
              {isIsolatedRoot ? "Exit local mode" : "Explore 1-hop / 2-hop relations"}
            </small>
          </span>
          <ArrowUpRight size={15} />
        </button>

        {(externalUrl || openAlexUrl) && (
          <div className="external-actions">
            {externalUrl && (
              <a href={externalUrl} rel="noreferrer" target="_blank">
                <BookOpenText size={16} />
                打开原始记录
                <ExternalLink size={14} />
              </a>
            )}
            {openAlexUrl && (
              <a href={openAlexUrl} rel="noreferrer" target="_blank">
                OpenAlex
                <ExternalLink size={14} />
              </a>
            )}
          </div>
        )}

        {(node.doi || node.arxiv || node.openalex || node.bibKey) && (
          <section className="detail-section">
            <h3>标识符</h3>
            <dl className="identifier-list">
              {node.bibKey && (
                <>
                  <dt>BibTeX</dt>
                  <dd>{node.bibKey}</dd>
                </>
              )}
              {node.doi && (
                <>
                  <dt>DOI</dt>
                  <dd>{node.doi}</dd>
                </>
              )}
              {node.arxiv && (
                <>
                  <dt>arXiv</dt>
                  <dd>{node.arxiv}</dd>
                </>
              )}
              {node.openalex && (
                <>
                  <dt>OpenAlex</dt>
                  <dd>{node.openalex}</dd>
                </>
              )}
            </dl>
          </section>
        )}

        {node.topics.length > 0 && (
          <section className="detail-section">
            <h3>主题</h3>
            <div className="topic-tags">
              {node.topics.map((topic) => (
                <span key={topic}>{topic}</span>
              ))}
            </div>
          </section>
        )}

        <RelationList
          data={data}
          icon={<ArrowDownLeft size={15} />}
          indices={relations.outgoing}
          label={`引用了 ${relations.outgoing.length} 篇`}
          onSelect={onSelect}
        />
        <RelationList
          data={data}
          icon={<ArrowUpRight size={15} />}
          indices={relations.incoming}
          label={`被 ${relations.incoming.length} 篇引用`}
          onSelect={onSelect}
        />
      </div>
    </aside>
  );
}

function RelationList({
  data,
  indices,
  icon,
  label,
  onSelect,
}: {
  data: GraphData;
  indices: number[];
  icon: React.ReactNode;
  label: string;
  onSelect: (index: number) => void;
}) {
  if (!indices.length) return null;
  return (
    <section className="detail-section">
      <h3>
        <GitCommitHorizontal size={15} />
        {label}
      </h3>
      <div className="relation-list">
        {indices.slice(0, 10).map((index) => {
          const node = data.nodes[index];
          return (
            <button key={node.id} onClick={() => onSelect(index)} type="button">
              <span>{icon}</span>
              <span>
                <strong>{node.title}</strong>
                <small>{node.year ?? "年份未知"}</small>
              </span>
            </button>
          );
        })}
        {indices.length > 10 && (
          <p>另有 {indices.length - 10} 篇未在此处展开</p>
        )}
      </div>
    </section>
  );
}
