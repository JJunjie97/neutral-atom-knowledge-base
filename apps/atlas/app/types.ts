export type GraphSection = {
  id: string;
  label: string;
  short: string;
  color: string;
};

export type TaxonomyCategory = {
  id: string;
  label_en: string;
  label_zh: string;
  description_en?: string;
  description_zh?: string;
  parent?: string | null;
  parent_id?: string | null;
  color?: string;
  aliases?: string[];
};

export type TaxonomyDimension = {
  id: string;
  label_en: string;
  label_zh: string;
  description?: string;
  description_en?: string;
  description_zh?: string;
  multi: boolean;
  dynamic?: boolean;
  categories: TaxonomyCategory[];
};

export type GraphTaxonomy = {
  version: string | null;
  digest?: string | null;
  field_weights?: Record<string, number>;
  dimensions: TaxonomyDimension[];
};

export type ClassificationSignal = {
  kind: string;
  value: string;
  field?: string;
};

export type ClassificationReviewSource = {
  source_file: string;
  heading: string;
  mention_id: string;
};

export type ClassificationEvidence = {
  taxonomy_version: string | null;
  dimension: string;
  category: string;
  method: string;
  confidence: number;
  rule_ids: string[];
  signals: ClassificationSignal[];
  review_sources: ClassificationReviewSource[];
};

export type PaperDetail = {
  id?: string;
  paperUid?: string | null;
  abstract?: string | null;
};

export type PaperClassificationDetail = {
  id?: string;
  paperUid?: string | null;
  taxonomyVersion?: string | null;
  facets: Record<string, string[]>;
  classifications: ClassificationEvidence[];
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
  classificationPath: string | null;
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
  facets: Record<string, string[]>;
  layoutGroup: string;
  /** Compatibility alias used by the existing canvas layout. */
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
  facetCounts: Record<string, Record<string, number>>;
  layout: string;
};

/** Stored direction: citing paper -> cited/reference paper. */
export type CitationEdge = [citingIndex: number, citedIndex: number];

export type GraphData = {
  meta: GraphMeta;
  sections: GraphSection[];
  taxonomy: GraphTaxonomy;
  nodes: GraphNode[];
  edges: CitationEdge[];
};

export type ViewName = "graph" | "timeline" | "overview";

export type GraphLayoutMode = "constellation" | "lineage";

export type GraphFilters = {
  query: string;
  facets: Record<string, string[]>;
  minYear: number;
  maxYear: number;
  minDegree: number;
  includeUnknownYear: boolean;
  includeUnresolvedMetadata: boolean;
};
