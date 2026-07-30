import type { GraphNode } from "./types";

export type TemporalLayoutNode = Pick<GraphNode, "id" | "year">;
export type CitationEdge = readonly [source: number, target: number];

export type TemporalCitationLayoutOptions = {
  /** Horizontal distance represented by one elapsed calendar year. */
  yearGap?: number;
  /** Vertical distance between papers in the same year band. */
  nodeGap?: number;
  /** Horizontal distance from the newest known year to the unknown-year lane. */
  unknownYearGap?: number;
  /** Number of deterministic forward/backward barycentric ordering passes. */
  sweeps?: number;
};

export type TemporalNodePlacement = {
  nodeIndex: number;
  nodeId: string;
  year: number | null;
  layerIndex: number;
  order: number;
  x: number;
  y: number;
};

export type TemporalYearLayer = {
  index: number;
  year: number | null;
  kind: "year" | "unknown-year";
  label: string;
  x: number;
  yMin: number;
  yMax: number;
  nodeIndices: number[];
};

export type TemporalCitationLayout = {
  /** The stored citation edges are interpreted as citing -> cited. */
  edgeContract: "citing-to-cited";
  /** Positions follow the reversed knowledge-development flow: cited -> citing. */
  flowDirection: "older-to-newer";
  axis: {
    dimension: "x";
    yearGap: number;
    nodeGap: number;
    unknownYearGap: number;
  };
  yearRange: {
    min: number;
    max: number;
  } | null;
  unknownYearLayerIndex: number | null;
  layers: TemporalYearLayer[];
  /**
   * One placement per input node. The array is indexed by the original node
   * index, so the canvas can use it without building an ID lookup table.
   */
  positions: TemporalNodePlacement[];
  bounds: {
    minX: number;
    maxX: number;
    minY: number;
    maxY: number;
    width: number;
    height: number;
  };
};

type WorkingLayer = {
  index: number;
  year: number | null;
  x: number;
  nodeIndices: number[];
};

const DEFAULT_YEAR_GAP = 180;
const DEFAULT_NODE_GAP = 64;
const DEFAULT_SWEEPS = 4;
const MAX_SWEEPS = 12;

function normalizedYear(year: number | null): number | null {
  return typeof year === "number" && Number.isFinite(year)
    ? Math.trunc(year)
    : null;
}

function positiveNumber(value: number | undefined, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : fallback;
}

function boundedSweepCount(value: number | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return DEFAULT_SWEEPS;
  }
  return Math.max(0, Math.min(MAX_SWEEPS, Math.trunc(value)));
}

function compareText(left: string, right: string) {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function mean(values: readonly number[]) {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

/**
 * Create a deterministic, Sugiyama-style year-band layout for a citation DAG
 * (cycles and same-year citations are also accepted).
 *
 * Input edges retain the atlas contract `[citingIndex, citedIndex]`. For
 * ordering, the relation is viewed as an influence flow from the cited paper
 * to the later citing paper. Known years are placed from old to new on the
 * x-axis using elapsed calendar-year spacing. Papers without a valid year are
 * placed in one separate lane after the newest known year.
 *
 * The function does not mutate nodes, edges, or their nested arrays.
 */
export function createTemporalCitationLayout(
  nodes: readonly TemporalLayoutNode[],
  edges: readonly CitationEdge[],
  options: TemporalCitationLayoutOptions = {},
): TemporalCitationLayout {
  const yearGap = positiveNumber(options.yearGap, DEFAULT_YEAR_GAP);
  const nodeGap = positiveNumber(options.nodeGap, DEFAULT_NODE_GAP);
  const unknownYearGap = positiveNumber(options.unknownYearGap, yearGap);
  const sweeps = boundedSweepCount(options.sweeps);
  const years = nodes.map((node) => normalizedYear(node.year));
  const knownYears = Array.from(
    new Set(years.filter((year): year is number => year !== null)),
  ).sort((left, right) => left - right);
  const minYear = knownYears.at(0) ?? null;
  const maxYear = knownYears.at(-1) ?? null;
  const hasUnknownYear = years.some((year) => year === null);
  const workingLayers: WorkingLayer[] = [];
  const layerIndexByYear = new Map<number, number>();

  for (const year of knownYears) {
    const index = workingLayers.length;
    layerIndexByYear.set(year, index);
    workingLayers.push({
      index,
      year,
      x: minYear === null ? 0 : (year - minYear) * yearGap,
      nodeIndices: [],
    });
  }

  const unknownYearLayerIndex = hasUnknownYear
    ? workingLayers.length
    : null;
  if (unknownYearLayerIndex !== null) {
    workingLayers.push({
      index: unknownYearLayerIndex,
      year: null,
      x:
        minYear === null || maxYear === null
          ? 0
          : (maxYear - minYear) * yearGap + unknownYearGap,
      nodeIndices: [],
    });
  }

  const layerByNode = new Array<number>(nodes.length);
  const stableKeyByNode = nodes.map(
    (node, nodeIndex) => `${node.id}\u0000${String(nodeIndex).padStart(12, "0")}`,
  );

  for (let nodeIndex = 0; nodeIndex < nodes.length; nodeIndex += 1) {
    const year = years[nodeIndex];
    const layerIndex =
      year === null
        ? unknownYearLayerIndex
        : (layerIndexByYear.get(year) ?? null);
    if (layerIndex === null) continue;
    layerByNode[nodeIndex] = layerIndex;
    workingLayers[layerIndex].nodeIndices.push(nodeIndex);
  }

  for (const layer of workingLayers) {
    layer.nodeIndices.sort((left, right) =>
      compareText(stableKeyByNode[left], stableKeyByNode[right]),
    );
  }

  const developmentParents = Array.from(
    { length: nodes.length },
    () => [] as number[],
  );
  const developmentChildren = Array.from(
    { length: nodes.length },
    () => [] as number[],
  );

  for (const [source, target] of edges) {
    if (
      !Number.isInteger(source) ||
      !Number.isInteger(target) ||
      source < 0 ||
      target < 0 ||
      source >= nodes.length ||
      target >= nodes.length ||
      source === target
    ) {
      continue;
    }
    // Stored edges are citing -> cited; the development flow is cited -> citing.
    const from = target;
    const to = source;
    developmentParents[to].push(from);
    developmentChildren[from].push(to);
  }

  const rankByNode = new Array<number>(nodes.length).fill(0);
  const normalizedRankByNode = new Array<number>(nodes.length).fill(0.5);

  const refreshRanks = () => {
    for (const layer of workingLayers) {
      const denominator = Math.max(1, layer.nodeIndices.length - 1);
      for (let rank = 0; rank < layer.nodeIndices.length; rank += 1) {
        const nodeIndex = layer.nodeIndices[rank];
        rankByNode[nodeIndex] = rank;
        normalizedRankByNode[nodeIndex] =
          layer.nodeIndices.length === 1 ? 0.5 : rank / denominator;
      }
    }
  };

  const reorderLayer = (
    layer: WorkingLayer,
    neighborsFor: (nodeIndex: number) => readonly number[],
  ) => {
    if (layer.nodeIndices.length < 2) return;
    const previousRank = new Map(
      layer.nodeIndices.map((nodeIndex, rank) => [nodeIndex, rank]),
    );
    const scored = layer.nodeIndices.map((nodeIndex) => {
      const neighborRanks = neighborsFor(nodeIndex).map(
        (neighborIndex) => normalizedRankByNode[neighborIndex],
      );
      return {
        nodeIndex,
        score:
          neighborRanks.length > 0
            ? mean(neighborRanks)
            : normalizedRankByNode[nodeIndex],
      };
    });

    scored.sort((left, right) => {
      const byScore = left.score - right.score;
      if (Math.abs(byScore) > Number.EPSILON) return byScore;
      const byPreviousRank =
        (previousRank.get(left.nodeIndex) ?? 0) -
        (previousRank.get(right.nodeIndex) ?? 0);
      if (byPreviousRank !== 0) return byPreviousRank;
      return compareText(
        stableKeyByNode[left.nodeIndex],
        stableKeyByNode[right.nodeIndex],
      );
    });
    layer.nodeIndices = scored.map(({ nodeIndex }) => nodeIndex);
  };

  refreshRanks();
  for (let sweep = 0; sweep < sweeps; sweep += 1) {
    for (const layer of workingLayers) {
      if (layer.year === null) continue;
      reorderLayer(layer, (nodeIndex) =>
        developmentParents[nodeIndex].filter(
          (parentIndex) =>
            years[parentIndex] !== null &&
            layerByNode[parentIndex] < layer.index,
        ),
      );
      refreshRanks();
    }

    for (let index = workingLayers.length - 1; index >= 0; index -= 1) {
      const layer = workingLayers[index];
      if (layer.year === null) continue;
      reorderLayer(layer, (nodeIndex) =>
        developmentChildren[nodeIndex].filter(
          (childIndex) =>
            years[childIndex] !== null &&
            layerByNode[childIndex] > layer.index,
        ),
      );
      refreshRanks();
    }

    if (unknownYearLayerIndex !== null) {
      const unknownLayer = workingLayers[unknownYearLayerIndex];
      reorderLayer(unknownLayer, (nodeIndex) =>
        [
          ...developmentParents[nodeIndex],
          ...developmentChildren[nodeIndex],
        ].filter((neighborIndex) => years[neighborIndex] !== null),
      );
      refreshRanks();
    }
  }

  const positions = new Array<TemporalNodePlacement>(nodes.length);
  const layers = workingLayers.map<TemporalYearLayer>((layer) => {
    const center = (layer.nodeIndices.length - 1) / 2;
    for (let order = 0; order < layer.nodeIndices.length; order += 1) {
      const nodeIndex = layer.nodeIndices[order];
      positions[nodeIndex] = {
        nodeIndex,
        nodeId: nodes[nodeIndex].id,
        year: years[nodeIndex],
        layerIndex: layer.index,
        order,
        x: layer.x,
        y: (order - center) * nodeGap,
      };
    }
    const halfSpan = Math.max(0, center * nodeGap);
    return {
      index: layer.index,
      year: layer.year,
      kind: layer.year === null ? "unknown-year" : "year",
      label: layer.year === null ? "Unknown year" : String(layer.year),
      x: layer.x,
      yMin: -halfSpan,
      yMax: halfSpan,
      nodeIndices: [...layer.nodeIndices],
    };
  });

  const xValues = positions.map((position) => position.x);
  const yValues = positions.map((position) => position.y);
  const minX = xValues.length > 0 ? Math.min(...xValues) : 0;
  const maxX = xValues.length > 0 ? Math.max(...xValues) : 0;
  const minY = yValues.length > 0 ? Math.min(...yValues) : 0;
  const maxY = yValues.length > 0 ? Math.max(...yValues) : 0;

  return {
    edgeContract: "citing-to-cited",
    flowDirection: "older-to-newer",
    axis: {
      dimension: "x",
      yearGap,
      nodeGap,
      unknownYearGap,
    },
    yearRange:
      minYear === null || maxYear === null
        ? null
        : { min: minYear, max: maxYear },
    unknownYearLayerIndex,
    layers,
    positions,
    bounds: {
      minX,
      maxX,
      minY,
      maxY,
      width: maxX - minX,
      height: maxY - minY,
    },
  };
}
