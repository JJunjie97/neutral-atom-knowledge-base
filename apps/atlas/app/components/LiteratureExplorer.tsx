"use client";

import {
  BarChart3,
  BookOpen,
  Clock3,
  Database,
  LoaderCircle,
  Network,
  RotateCcw,
  Search,
  Sparkles,
} from "lucide-react";
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  authorLine,
  formatNumber,
  matchesFacetSelections,
  matchesSearch,
  nodeDegree,
  normalizeSearch,
} from "../graph-utils";
import { publicUrl } from "../site-config";
import type {
  GraphData,
  GraphFilters,
  ViewName,
} from "../types";
import DetailsPanel from "./DetailsPanel";
import FacetFilterPanel from "./FacetFilterPanel";
import GraphCanvas from "./GraphCanvas";
import OverviewView from "./OverviewView";
import TimelineView from "./TimelineView";

const EMPTY_TAXONOMY: GraphData["taxonomy"] = {
  version: null,
  dimensions: [],
};
const INITIAL_FILTERS: GraphFilters = {
  query: "",
  facets: {},
  minYear: 1977,
  maxYear: 2026,
  minDegree: 0,
  includeUnknownYear: true,
  includeUnresolvedMetadata: false,
};

const VIEWS: {
  id: ViewName;
  label: string;
  icon: typeof Network;
}[] = [
  { id: "graph", label: "关系星图", icon: Network },
  { id: "timeline", label: "时间脉络", icon: Clock3 },
  { id: "overview", label: "数据概览", icon: BarChart3 },
];

export default function LiteratureExplorer() {
  const [coreData, setCoreData] = useState<GraphData | null>(null);
  const [fullData, setFullData] = useState<GraphData | null>(null);
  const [scope, setScope] = useState<"core" | "full">("core");
  const [view, setView] = useState<ViewName>("graph");
  const [filters, setFilters] = useState<GraphFilters>(INITIAL_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isolateRootId, setIsolateRootId] = useState<string | null>(null);
  const [isolateDepth, setIsolateDepth] = useState<1 | 2>(1);
  const [loadingFull, setLoadingFull] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const deferredQuery = useDeferredValue(filters.query);

  useEffect(() => {
    let cancelled = false;
    fetch(publicUrl("/data/core-graph.json"))
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<GraphData>;
      })
      .then((data) => {
        if (!cancelled) {
          setCoreData(data);
          setFilters((current) => ({
            ...current,
            minYear: data.meta.yearMin,
            maxYear: data.meta.yearMax,
          }));
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(
            `核心图数据加载失败：${
              cause instanceof Error ? cause.message : String(cause)
            }`,
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const data = scope === "full" ? fullData ?? coreData : coreData;
  const generatedLabel = data?.meta.generated_at
    ? new Date(data.meta.generated_at).toLocaleDateString("zh-CN")
    : "本地快照";
  const taxonomy = data?.taxonomy ?? EMPTY_TAXONOMY;
  const facetSearchLabels = useMemo(
    () =>
      new Map(
        taxonomy.dimensions.flatMap((dimension) =>
          dimension.categories.map(
            (category) =>
              [
                `${dimension.id}:${category.id}`,
                [
                  dimension.label_zh,
                  dimension.label_en,
                  category.label_zh,
                  category.label_en,
                  ...(category.aliases ?? []),
                ]
                  .filter(Boolean)
                  .join(" "),
              ] as const,
          ),
        ),
      ),
    [taxonomy],
  );

  const nodeIndexById = useMemo(
    () =>
      new Map(
        (data?.nodes ?? []).map((node, index) => [node.id, index] as const),
      ),
    [data],
  );
  const selectedIndex =
    selectedId == null ? null : (nodeIndexById.get(selectedId) ?? null);
  const isolateRootIndex =
    isolateRootId == null ? null : (nodeIndexById.get(isolateRootId) ?? null);

  const visibleIndices = useMemo(() => {
    if (!data) return [];
    const query = normalizeSearch(deferredQuery.trim());
    return data.nodes.reduce<number[]>((indices, node, index) => {
      if (!filters.includeUnresolvedMetadata && node.titleMissing) {
        return indices;
      }
      if (!matchesFacetSelections(node, filters.facets)) return indices;
      if (
        node.year == null
          ? !filters.includeUnknownYear
          : node.year < filters.minYear || node.year > filters.maxYear
      ) {
        return indices;
      }
      if (nodeDegree(node) < filters.minDegree) return indices;
      if (!matchesSearch(node, query, facetSearchLabels)) return indices;
      indices.push(index);
      return indices;
    }, []);
  }, [data, deferredQuery, facetSearchLabels, filters]);

  const searchResults = useMemo(() => {
    if (!data || deferredQuery.trim().length < 2) return [];
    return visibleIndices
      .slice()
      .sort(
        (left, right) =>
          nodeDegree(data.nodes[right]) - nodeDegree(data.nodes[left]),
      )
      .slice(0, 7);
  }, [data, deferredQuery, visibleIndices]);

  async function switchScope(nextScope: "core" | "full") {
    setIsolateRootId(null);
    if (nextScope === "core") {
      setScope("core");
      return;
    }
    if (fullData) {
      setScope("full");
      return;
    }
    setLoadingFull(true);
    setError(null);
    try {
      const response = await fetch(publicUrl("/data/full-graph.json"));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const loaded = (await response.json()) as GraphData;
      setFullData(loaded);
      setScope("full");
    } catch (cause) {
      setError(
        `完整网络加载失败：${
          cause instanceof Error ? cause.message : String(cause)
        }`,
      );
    } finally {
      setLoadingFull(false);
    }
  }

  function updateFilter<Key extends keyof GraphFilters>(
    key: Key,
    value: GraphFilters[Key],
  ) {
    setFilters((current) => ({ ...current, [key]: value }));
  }
  function toggleFacet(dimensionId: string, categoryId: string) {
    setFilters((current) => {
      const selected = current.facets[dimensionId] ?? [];
      const nextSelected = selected.includes(categoryId)
        ? selected.filter((id) => id !== categoryId)
        : [...selected, categoryId];
      const facets = { ...current.facets };
      if (nextSelected.length) facets[dimensionId] = nextSelected;
      else delete facets[dimensionId];
      return { ...current, facets };
    });
  }

  function clearFacets() {
    setFilters((current) => ({ ...current, facets: {} }));
  }

  function selectIndex(index: number | null) {
    setSelectedId(index == null || !data ? null : data.nodes[index].id);
  }

  function toggleLocalGraph(index: number) {
    if (!data) return;
    const nodeId = data.nodes[index].id;
    setView("graph");
    if (isolateRootId === nodeId) {
      setIsolateRootId(null);
      return;
    }
    setIsolateRootId(nodeId);
    setIsolateDepth(1);
  }

  if (error && !coreData) {
    return (
      <main className="fatal-state">
        <Sparkles size={30} />
        <h1>星图数据未能载入</h1>
        <p>{error}</p>
        <p>请先运行：python scripts/prepare_data.py</p>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="loading-state">
        <LoaderCircle className="spin" size={28} />
        <p>正在装载中性原子文献宇宙…</p>
      </main>
    );
  }

  return (
    <main className="atlas-app">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div>
            <p>NEUTRAL ATOM KNOWLEDGE ATLAS</p>
            <h1>中性原子量子计算 · 文献星图</h1>
          </div>
        </div>
        <nav className="view-tabs" aria-label="可视化视图">
          {VIEWS.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={view === item.id ? "is-active" : ""}
                key={item.id}
                onClick={() => setView(item.id)}
                type="button"
              >
                <Icon size={16} />
                {item.label}
              </button>
            );
          })}
        </nav>
        <div className="dataset-stamp">
          <Database size={15} />
          <span>更新于 {generatedLabel}</span>
        </div>
      </header>

      <div className="atlas-layout">
        <aside className="filter-panel">
          <section className="scope-switcher">
            <div className="filter-section-heading">
              <span>数据范围</span>
              <small>两级加载</small>
            </div>
            <div className="segmented-control">
              <button
                className={scope === "core" ? "is-active" : ""}
                onClick={() => void switchScope("core")}
                type="button"
              >
                <strong>{formatNumber(coreData?.meta.nodeCount ?? 0)}</strong>
                <span>核心文献</span>
              </button>
              <button
                className={scope === "full" ? "is-active" : ""}
                disabled={loadingFull}
                onClick={() => void switchScope("full")}
                type="button"
              >
                {loadingFull ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <strong>
                    {formatNumber(
                      fullData?.meta.nodeCount ??
                        coreData?.meta.fullNodeCount ??
                        0,
                    )}
                  </strong>
                )}
                <span>完整网络</span>
              </button>
            </div>
            <p className="scope-note">
              {scope === "core"
                ? "只显示综述 BibTeX 中的去重文献及其互引关系。"
                : "显示核心文献与它们引用的全部 OpenAlex 记录。"}
            </p>
          </section>

          <section className="filter-section search-section">
            <label htmlFor="paper-search">
              <Search size={15} />
              搜索
            </label>
            <div className="search-input-wrap">
              <input
                autoComplete="off"
                id="paper-search"
                onChange={(event) => updateFilter("query", event.target.value)}
                placeholder="标题、作者、DOI、分类、BibTeX…"
                type="search"
                value={filters.query}
              />
            </div>
            {searchResults.length > 0 && (
              <div className="search-results">
                {searchResults.map((index) => {
                  const node = data.nodes[index];
                  return (
                    <button
                      key={node.id}
                      onClick={() => {
                        selectIndex(index);
                        setFilters((current) => ({ ...current, query: "" }));
                      }}
                      type="button"
                    >
                      <strong>{node.title}</strong>
                      <span>
                        {node.year ?? "年份未知"} ·{" "}
                        {authorLine(node.authors, 2)}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <FacetFilterPanel
            facetCounts={data.meta.facetCounts ?? {}}
            onClearAll={clearFacets}
            onToggle={toggleFacet}
            selections={filters.facets}
            taxonomy={taxonomy}
          />
          <section className="filter-section">
            <div className="filter-section-heading">
              <span>发表年份</span>
              <small>
                {filters.minYear}—{filters.maxYear}
              </small>
            </div>
            <div className="year-inputs">
              <label>
                从
                <input
                  max={filters.maxYear}
                  min={data.meta.yearMin}
                  onChange={(event) =>
                    updateFilter("minYear", Number(event.target.value))
                  }
                  type="number"
                  value={filters.minYear}
                />
              </label>
              <span />
              <label>
                到
                <input
                  max={data.meta.yearMax}
                  min={filters.minYear}
                  onChange={(event) =>
                    updateFilter("maxYear", Number(event.target.value))
                  }
                  type="number"
                  value={filters.maxYear}
                />
              </label>
            </div>
            <label className="check-row">
              <input
                checked={filters.includeUnknownYear}
                onChange={(event) =>
                  updateFilter("includeUnknownYear", event.target.checked)
                }
                type="checkbox"
              />
              <span>包含年份未知记录</span>
              <small>{data.meta.unknownYear}</small>
            </label>
            <label className="check-row">
              <input
                checked={filters.includeUnresolvedMetadata}
                onChange={(event) =>
                  updateFilter(
                    "includeUnresolvedMetadata",
                    event.target.checked,
                  )
                }
                type="checkbox"
              />
              <span>显示元数据未解析记录</span>
              <small>{data.meta.missingTitleCount ?? 0}</small>
            </label>
          </section>

          <section className="filter-section">
            <div className="filter-section-heading">
              <span>Minimum graph degree</span>
              <strong>{filters.minDegree}</strong>
            </div>
            <input
              aria-label="Minimum graph degree"
              className="degree-slider"
              max={scope === "core" ? 80 : 30}
              min={0}
              onChange={(event) =>
                updateFilter("minDegree", Number(event.target.value))
              }
              type="range"
              value={filters.minDegree}
            />
            <div className="range-labels">
              <span>全部</span>
              <span>High degree</span>
            </div>
          </section>

          <button
            className="reset-button"
            onClick={() =>
              setFilters({
                ...INITIAL_FILTERS,
                minYear: data.meta.yearMin,
                maxYear: data.meta.yearMax,
              })
            }
            type="button"
          >
            <RotateCcw size={15} />
            重置全部筛选
          </button>

          <div className="filter-footer">
            <BookOpen size={15} />
            <span>
              当前显示
              <strong>{formatNumber(visibleIndices.length)}</strong>
              篇
            </span>
          </div>
        </aside>

        <section className="workspace">
          {error && <div className="inline-error">{error}</div>}

          {view === "graph" && (
            <GraphCanvas
              data={data}
              isolateDepth={isolateDepth}
              isolateRootIndex={isolateRootIndex}
              key={`${scope}-${isolateRootId ?? "global"}-${isolateDepth}`}
              onExitIsolate={() => setIsolateRootId(null)}
              onIsolateDepthChange={setIsolateDepth}
              onSelect={selectIndex}
              selectedIndex={selectedIndex}
              visibleIndices={visibleIndices}
            />
          )}
          {view === "timeline" && (
            <TimelineView
              data={data}
              onSelect={(index) => selectIndex(index)}
              visibleIndices={visibleIndices}
            />
          )}
          {view === "overview" && (
            <OverviewView
              data={data}
              onSelect={(index) => selectIndex(index)}
              visibleIndices={visibleIndices}
            />
          )}

          <DetailsPanel
            data={data}
            isIsolatedRoot={
              selectedId != null && selectedId === isolateRootId
            }
            onClose={() => setSelectedId(null)}
            onFacetSelect={toggleFacet}
            onIsolate={toggleLocalGraph}
            onSelect={(index) => selectIndex(index)}
            selectedIndex={selectedIndex}
          />
        </section>
      </div>
    </main>
  );
}
