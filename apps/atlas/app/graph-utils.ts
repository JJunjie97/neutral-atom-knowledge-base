import type { GraphNode } from "./types";

export function nodeDegree(node: GraphNode) {
  return node.in + node.out;
}

export function formatNumber(value: number | null | undefined) {
  if (value == null) return "—";
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function authorLine(authors: string[], limit = 3) {
  if (!authors.length) return "作者信息缺失";
  const visible = authors.slice(0, limit).join(" · ");
  return authors.length > limit ? `${visible} 等` : visible;
}

export function normalizeSearch(value: string) {
  return value
    .normalize("NFKD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase();
}

export function matchesSearch(
  node: GraphNode,
  normalizedQuery: string,
  facetSearchLabels?: ReadonlyMap<string, string>,
) {
  if (!normalizedQuery) return true;
  const haystack = [
    node.title,
    node.authors.join(" "),
    node.venue,
    node.doi,
    node.arxiv,
    node.openalex,
    node.bibKeys.join(" "),
    node.topics.join(" "),
    ...Object.entries(node.facets ?? {}).flatMap(([dimensionId, categoryIds]) =>
      categoryIds.map(
        (categoryId) =>
          facetSearchLabels?.get(`${dimensionId}:${categoryId}`) ?? categoryId,
      ),
    ),
  ]
    .filter(Boolean)
    .join(" ");
  return normalizeSearch(haystack).includes(normalizedQuery);
}

export function matchesFacetSelections(
  node: GraphNode,
  selections: Record<string, string[]>,
) {
  for (const [dimensionId, selectedCategories] of Object.entries(selections)) {
    if (!selectedCategories.length) continue;
    const nodeCategories = node.facets?.[dimensionId] ?? [];
    if (
      !selectedCategories.some((categoryId) =>
        nodeCategories.includes(categoryId),
      )
    ) {
      return false;
    }
  }
  return true;
}
export function safeExternalUrl(value: string | null | undefined) {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.href
      : null;
  } catch {
    return null;
  }
}
