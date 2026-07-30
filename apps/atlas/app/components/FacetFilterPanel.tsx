"use client";

import {
  ChevronDown,
  ChevronRight,
  Layers3,
  Search,
  X,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatNumber, normalizeSearch } from "../graph-utils";
import type {
  GraphTaxonomy,
  TaxonomyCategory,
  TaxonomyDimension,
} from "../types";

type Props = {
  taxonomy: GraphTaxonomy;
  facetCounts: Record<string, Record<string, number>>;
  selections: Record<string, string[]>;
  onToggle: (dimensionId: string, categoryId: string) => void;
  onClearAll: () => void;
};

const DEFAULT_VISIBLE_CATEGORIES = 8;

function dimensionLabel(dimension: TaxonomyDimension) {
  return dimension.label_zh || dimension.label_en || dimension.id;
}

function categoryLabel(category: TaxonomyCategory) {
  return category.label_zh || category.label_en || category.id;
}

export default function FacetFilterPanel({
  taxonomy,
  facetCounts,
  selections,
  onToggle,
  onClearAll,
}: Props) {
  const [openDimensions, setOpenDimensions] = useState<Record<string, boolean>>(
    {},
  );
  const [queries, setQueries] = useState<Record<string, string>>({});
  const [showAll, setShowAll] = useState<Record<string, boolean>>({});

  const dimensionById = useMemo(
    () => new Map(taxonomy.dimensions.map((dimension) => [dimension.id, dimension])),
    [taxonomy.dimensions],
  );
  const selectedItems = useMemo(
    () =>
      Object.entries(selections).flatMap(([dimensionId, categoryIds]) => {
        const dimension = dimensionById.get(dimensionId);
        const categoryById = new Map(
          (dimension?.categories ?? []).map((category) => [category.id, category]),
        );
        return categoryIds.map((categoryId) => ({
          dimensionId,
          categoryId,
          dimensionLabel: dimension ? dimensionLabel(dimension) : dimensionId,
          categoryLabel: categoryById.has(categoryId)
            ? categoryLabel(categoryById.get(categoryId)!)
            : categoryId,
        }));
      }),
    [dimensionById, selections],
  );

  if (!taxonomy.dimensions.length) {
    return (
      <section className="filter-section facet-filter-section">
        <div className="filter-section-heading">
          <span>
            <Layers3 size={14} />
            多维分类
          </span>
          <small>尚未生成</small>
        </div>
        <p className="facet-empty-note">
          当前图快照还没有 taxonomy。运行分类与导出流程后，可按原子元素、平台、技术路线和具体技术筛选。
        </p>
      </section>
    );
  }

  return (
    <section className="filter-section facet-filter-section">
      <div className="filter-section-heading">
        <span>
          <Layers3 size={14} />
          多维分类
        </span>
        <small>{selectedItems.length ? `${selectedItems.length} 已选` : "AND / OR"}</small>
      </div>
      <p className="facet-logic-note">维度内取并集（OR），不同维度取交集（AND）。</p>

      {selectedItems.length > 0 && (
        <div className="active-facets" aria-label="已选分类">
          <div className="active-facets-heading">
            <span>已选条件</span>
            <button onClick={onClearAll} type="button">
              清空
            </button>
          </div>
          <div className="active-facet-chips">
            {selectedItems.map((item) => (
              <button
                aria-label={`移除 ${item.dimensionLabel}：${item.categoryLabel}`}
                key={`${item.dimensionId}:${item.categoryId}`}
                onClick={() => onToggle(item.dimensionId, item.categoryId)}
                title={`${item.dimensionLabel} · ${item.categoryLabel}`}
                type="button"
              >
                <span>{item.categoryLabel}</span>
                <X size={11} />
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="facet-dimensions">
        {taxonomy.dimensions.map((dimension, dimensionIndex) => {
          const selected = selections[dimension.id] ?? [];
          const selectedSet = new Set(selected);
          const counts = facetCounts[dimension.id] ?? {};
          const isOpen =
            openDimensions[dimension.id] ?? dimensionIndex < 3;
          const query = normalizeSearch(queries[dimension.id] ?? "");
          const sortedCategories = [...dimension.categories]
            .filter((category) => {
              if (!query) return true;
              return normalizeSearch(
                [
                  category.label_zh,
                  category.label_en,
                  category.id,
                  ...(category.aliases ?? []),
                ]
                  .filter(Boolean)
                  .join(" "),
              ).includes(query);
            })
            .sort((left, right) => {
              const selectedDiff =
                Number(selectedSet.has(right.id)) - Number(selectedSet.has(left.id));
              if (selectedDiff) return selectedDiff;
              const countDiff = (counts[right.id] ?? 0) - (counts[left.id] ?? 0);
              if (countDiff) return countDiff;
              return categoryLabel(left).localeCompare(categoryLabel(right), "zh-CN");
            });
          let visibleCategories = sortedCategories;
          if (!query && !showAll[dimension.id]) {
            const leading = sortedCategories.slice(0, DEFAULT_VISIBLE_CATEGORIES);
            const leadingIds = new Set(leading.map((category) => category.id));
            visibleCategories = [
              ...leading,
              ...sortedCategories.filter(
                (category) =>
                  selectedSet.has(category.id) && !leadingIds.has(category.id),
              ),
            ];
          }
          const hiddenCount = Math.max(
            0,
            sortedCategories.length - visibleCategories.length,
          );

          return (
            <div className="facet-dimension" key={dimension.id}>
              <button
                aria-expanded={isOpen}
                className="facet-dimension-toggle"
                onClick={() =>
                  setOpenDimensions((current) => ({
                    ...current,
                    [dimension.id]: !isOpen,
                  }))
                }
                type="button"
              >
                <span>
                  {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  <strong>{dimensionLabel(dimension)}</strong>
                </span>
                <small>{selected.length ? `${selected.length} 已选` : dimension.categories.length}</small>
              </button>

              {isOpen && (
                <div className="facet-dimension-body">
                  {dimension.categories.length > DEFAULT_VISIBLE_CATEGORIES && (
                    <label className="facet-search">
                      <Search size={12} />
                      <input
                        aria-label={`搜索${dimensionLabel(dimension)}`}
                        onChange={(event) =>
                          setQueries((current) => ({
                            ...current,
                            [dimension.id]: event.target.value,
                          }))
                        }
                        placeholder="搜索分类…"
                        type="search"
                        value={queries[dimension.id] ?? ""}
                      />
                    </label>
                  )}

                  <div className="facet-category-list">
                    {visibleCategories.map((category) => {
                      const active = selectedSet.has(category.id);
                      return (
                        <button
                          aria-pressed={active}
                          className={active ? "is-active" : ""}
                          key={category.id}
                          onClick={() => onToggle(dimension.id, category.id)}
                          title={
                            category.description_zh ||
                            category.description_en ||
                            category.label_en
                          }
                          type="button"
                        >
                          <span className="facet-check" aria-hidden="true">
                            {active ? "✓" : ""}
                          </span>
                          <span>
                            <strong>{categoryLabel(category)}</strong>
                            {category.label_en &&
                              category.label_en !== categoryLabel(category) && (
                                <small>{category.label_en}</small>
                              )}
                          </span>
                          <em>{formatNumber(counts[category.id] ?? 0)}</em>
                        </button>
                      );
                    })}
                    {!visibleCategories.length && (
                      <p className="facet-no-results">没有匹配的分类。</p>
                    )}
                  </div>

                  {!query &&
                    (hiddenCount > 0 || showAll[dimension.id]) && (
                      <button
                        className="facet-show-more"
                        onClick={() =>
                          setShowAll((current) => ({
                            ...current,
                            [dimension.id]: !current[dimension.id],
                          }))
                        }
                        type="button"
                      >
                        {showAll[dimension.id]
                          ? "收起"
                          : `再显示 ${hiddenCount} 项`}
                      </button>
                    )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}