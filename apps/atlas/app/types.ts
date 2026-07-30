export type GraphSection = {
  id: string;
  label: string;
  short: string;
  color: string;
};

export type GraphNode = {
  id: string;
  paperUid: string | null;
  title: string;
  titleSource: string | null;
  titleMissing: boolean;
  metadataStatus: string;
  entityKind: string;
  year: number | null;
  date: string | null;
  authors: string[];
  venue: string | null;
  type: string | null;
  abstract: string | null;
  detailPath: string | null;
  url: string | null;
  oaUrl: string | null;
  doi: string | null;
  arxiv: string | null;
  openalex: string | null;
  topics: string[];
  citations: number | null;
  references: number | null;
  seed: boolean;
  bibKey: string | null;
  bibKeys: string[];
  sections: string[];
  group: string;
  in: number;
  out: number;
  x: number;
  y: number;
};

export type GraphMeta = {
  generated_at?: string;
  nodeCount: number;
  edgeCount: number;
  seedCount: number;
  yearMin: number;
  yearMax: number;
  unknownYear: number;
  missingTitleCount: number;
  fullNodeCount?: number;
  yearCounts: [number, number][];
  sectionCounts: Record<string, number>;
  layout: string;
};

export type GraphData = {
  meta: GraphMeta;
  sections: GraphSection[];
  nodes: GraphNode[];
  edges: [number, number][];
};

export type ViewName = "graph" | "timeline" | "overview";

export type GraphFilters = {
  query: string;
  group: string;
  minYear: number;
  maxYear: number;
  minDegree: number;
  includeUnknownYear: boolean;
  includeUnresolvedMetadata: boolean;
};
