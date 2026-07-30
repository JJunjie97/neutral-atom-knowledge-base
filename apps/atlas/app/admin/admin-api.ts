export type JsonObject = Record<string, unknown>;

export type AdminSummary = {
  works: number;
  seedWorks: number;
  citationEdges: number;
  unresolvedSeeds: number;
  manualClassifications: number | null;
  databasePath: string | null;
  updatedAt: string | null;
  raw: JsonObject;
};

export type WorkListItem = {
  id: string;
  title: string;
  year: number | null;
  authors: string[];
  venue: string | null;
  doi: string | null;
  metadataStatus: string;
  seed: boolean;
  updatedAt: string | null;
  raw: JsonObject;
};

export type WorkListPage = {
  items: WorkListItem[];
  total: number;
  limit: number;
  offset: number;
};

export type AdminIdentifier = {
  id: string | number | null;
  scheme: string;
  value: string;
  raw: JsonObject;
};

export type AdminClassification = {
  id: string | number | null;
  dimension: string;
  category: string;
  confidence: number | null;
  method: string;
  raw: JsonObject;
};

export type AdminTaxonomyCategory = {
  id: string;
  labelZh: string;
  labelEn: string;
};

export type AdminTaxonomyDimension = {
  id: string;
  labelZh: string;
  labelEn: string;
  categories: AdminTaxonomyCategory[];
};

export type AdminTaxonomy = {
  version: string;
  dimensions: AdminTaxonomyDimension[];
};

export type WorkDetail = {
  id: string;
  work: JsonObject;
  identifiers: AdminIdentifier[];
  classifications: AdminClassification[];
  seedEntries: JsonObject[];
  documents: JsonObject[];
  citationCounts: JsonObject;
  raw: JsonObject;
};

export type WorkPatch = {
  title: string | null;
  abstract: string | null;
  year: number | null;
  publication_date: string | null;
  authors: string[];
  venue: string | null;
  work_type: string | null;
  url: string | null;
  oa_url: string | null;
  metadata_status: string | null;
};

export class AdminApiError extends Error {
  status: number;
  details: unknown;

  constructor(message: string, status = 0, details: unknown = null) {
    super(message);
    this.name = "AdminApiError";
    this.status = status;
    this.details = details;
  }
}

function objectValue(value: unknown): JsonObject {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonObject)
    : {};
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function nullableString(value: unknown): string | null {
  const normalized = stringValue(value).trim();
  return normalized || null;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function booleanValue(value: unknown): boolean {
  return value === true || value === 1 || value === "1" || value === "true";
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value
      .map((item) => stringValue(item).trim())
      .filter(Boolean);
  }
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value) as unknown;
    if (Array.isArray(parsed)) return stringList(parsed);
  } catch {
    // Fall through to the human-friendly delimiter parser.
  }
  return value
    .split(/[;\n]/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

function firstDefined(record: JsonObject, keys: string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return record[key];
  }
  return undefined;
}

export function normalizeLoopbackApiUrl(value: string): string {
  const trimmed = value.trim().replace(/\/+$/u, "");
  if (!trimmed) throw new AdminApiError("请输入本地管理服务地址。", 0);
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new AdminApiError("管理服务地址不是有效 URL。", 0);
  }
  const hostname = parsed.hostname.toLowerCase();
  if (
    parsed.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]", "::1"].includes(hostname)
  ) {
    throw new AdminApiError("管理服务只能连接到本机回环地址（localhost / 127.0.0.1）。", 0);
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new AdminApiError("管理服务地址不能包含凭据、查询参数或片段。", 0);
  }
  return trimmed;
}

export function normalizeAdminSummary(payload: unknown): AdminSummary {
  const root = objectValue(payload);
  const database = objectValue(root.database);
  const source = Object.keys(database).length ? database : root;
  return {
    works: numberValue(firstDefined(source, ["works", "work_count", "workCount"])) ?? 0,
    seedWorks:
      numberValue(firstDefined(source, ["seed_works", "seedWorks", "seed_count"])) ?? 0,
    citationEdges:
      numberValue(
        firstDefined(source, [
          "citation_edges",
          "citation_edges_with_sources",
          "citationEdges",
          "edge_count",
        ]),
      ) ?? 0,
    unresolvedSeeds:
      numberValue(
        firstDefined(root, ["unresolved_seeds", "unresolvedSeeds", "needs_review"]),
      ) ??
      numberValue(firstDefined(source, ["unresolved_seeds", "unresolvedSeeds"])) ??
      0,
    manualClassifications: numberValue(
      firstDefined(root, ["manual_classifications", "manualClassifications"]),
    ),
    databasePath: nullableString(
      firstDefined(root, ["database_path", "databasePath", "db_path"]),
    ),
    updatedAt: nullableString(
      firstDefined(root, ["updated_at", "generated_at", "updatedAt"]),
    ),
    raw: root,
  };
}

export function normalizeWorkList(payload: unknown): WorkListPage {
  const root = objectValue(payload);
  const source = arrayValue(
    firstDefined(root, ["items", "works", "results", "records"]),
  );
  const items = source.map((value, index): WorkListItem => {
    const item = objectValue(value);
    const id = firstDefined(item, ["id", "work_id", "paper_uid", "paperUid"]);
    const stableIdentity =
      nullableString(
        firstDefined(item, [
          "canonical_id",
          "doi",
          "arxiv_id",
          "openalex_id",
          "paper_uid",
          "paperUid",
        ]),
      ) ?? String(id ?? index);
    return {
      id: String(id ?? index),
      title:
        nullableString(firstDefined(item, ["title", "display_name", "name"])) ??
        `Metadata unavailable \u00b7 ${stableIdentity}`,
      year: numberValue(firstDefined(item, ["year", "publication_year"])),
      authors: stringList(firstDefined(item, ["authors", "author_names"])),
      venue: nullableString(firstDefined(item, ["venue", "journal", "host_venue"])),
      doi: nullableString(firstDefined(item, ["doi", "doi_norm"])),
      metadataStatus:
        nullableString(firstDefined(item, ["metadata_status", "metadataStatus", "status"])) ??
        "unknown",
      seed: booleanValue(firstDefined(item, ["seed", "is_seed"])),
      updatedAt: nullableString(firstDefined(item, ["updated_at", "updatedAt"])),
      raw: item,
    };
  });
  return {
    items,
    total:
      numberValue(firstDefined(root, ["total", "total_count", "count"])) ?? items.length,
    limit: numberValue(root.limit) ?? items.length,
    offset: numberValue(root.offset) ?? 0,
  };
}

export function normalizeWorkDetail(payload: unknown): WorkDetail {
  const root = objectValue(payload);
  const work = Object.keys(objectValue(root.work)).length
    ? objectValue(root.work)
    : root;
  const id = firstDefined(work, ["id", "work_id", "paper_uid", "paperUid"]);
  const identifiers = arrayValue(root.identifiers).map((value): AdminIdentifier => {
    const item = objectValue(value);
    return {
      id: (firstDefined(item, ["id", "identifier_id"]) as string | number | null) ?? null,
      scheme:
        nullableString(firstDefined(item, ["scheme", "type", "identifier_type"])) ??
        "identifier",
      value:
        nullableString(firstDefined(item, ["value", "identifier", "identifier_value"])) ??
        "",
      raw: item,
    };
  });
  const classifications = arrayValue(root.classifications).map(
    (value): AdminClassification => {
      const item = objectValue(value);
      return {
        id:
          (firstDefined(item, ["id", "classification_id"]) as
            | string
            | number
            | null) ?? null,
        dimension:
          nullableString(firstDefined(item, ["dimension", "dimension_id"])) ?? "",
        category:
          nullableString(firstDefined(item, ["category", "category_id"])) ?? "",
        confidence: numberValue(item.confidence),
        method: nullableString(item.method) ?? "unknown",
        raw: item,
      };
    },
  );
  return {
    id: String(id ?? ""),
    work,
    identifiers,
    classifications,
    seedEntries: arrayValue(firstDefined(root, ["seed_entries", "seedEntries"]))
      .map(objectValue),
    documents: arrayValue(firstDefined(root, ["documents", "document_records"]))
      .map(objectValue),
    citationCounts: objectValue(
      firstDefined(root, ["citation_counts", "citationCounts", "citations"]),
    ),
    raw: root,
  };
}

function normalizeTaxonomy(value: unknown): AdminTaxonomy | null {
  const taxonomy = objectValue(value);
  const version = nullableString(
    firstDefined(taxonomy, ["version", "taxonomy_version", "id"]),
  );
  const dimensions = arrayValue(taxonomy.dimensions).map((dimensionValue) => {
    const dimension = objectValue(dimensionValue);
    return {
      id: nullableString(firstDefined(dimension, ["id", "dimension_id"])) ?? "",
      labelZh:
        nullableString(firstDefined(dimension, ["label_zh", "labelZh"])) ?? "",
      labelEn:
        nullableString(firstDefined(dimension, ["label_en", "labelEn", "label"])) ?? "",
      categories: arrayValue(dimension.categories).map((categoryValue) => {
        const category = objectValue(categoryValue);
        return {
          id: nullableString(firstDefined(category, ["id", "category_id"])) ?? "",
          labelZh:
            nullableString(firstDefined(category, ["label_zh", "labelZh"])) ?? "",
          labelEn:
            nullableString(firstDefined(category, ["label_en", "labelEn", "label"])) ?? "",
        };
      }).filter((category) => category.id),
    };
  }).filter((dimension) => dimension.id);
  return version && dimensions.length ? { version, dimensions } : null;
}

export function normalizeCurrentTaxonomy(payload: unknown): AdminTaxonomy | null {
  const root = objectValue(payload);
  const direct = normalizeTaxonomy(root.current ?? root.taxonomy ?? root);
  if (direct) return direct;
  const taxonomies = arrayValue(
    firstDefined(root, ["taxonomies", "versions", "items"]),
  )
    .map(normalizeTaxonomy)
    .filter((item): item is AdminTaxonomy => item != null);
  if (!taxonomies.length) return null;
  const currentVersion = nullableString(
    firstDefined(root, ["current_version", "currentVersion", "taxonomy_version"]),
  );
  return taxonomies.find((item) => item.version === currentVersion) ?? taxonomies[0];
}

export class AdminApiClient {
  readonly baseUrl: string;
  readonly token: string;

  constructor(baseUrl: string, token: string) {
    this.baseUrl = normalizeLoopbackApiUrl(baseUrl);
    this.token = token.trim();
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (this.token) headers.set("Authorization", `Bearer ${this.token}`);
    if (init.body != null) headers.set("Content-Type", "application/json");
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        cache: "no-store",
        headers,
      });
    } catch (cause) {
      throw new AdminApiError(
        "无法连接本地管理服务。请确认服务已启动，并从 localhost 打开本页面。",
        0,
        cause,
      );
    }
    const text = await response.text();
    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text) as unknown;
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      const record = objectValue(payload);
      const message =
        nullableString(firstDefined(record, ["message", "error", "detail"])) ??
        `本地管理服务返回 HTTP ${response.status}`;
      throw new AdminApiError(message, response.status, payload);
    }
    return payload as T;
  }

  async health(): Promise<JsonObject> {
    return objectValue(await this.request<unknown>("/api/health"));
  }

  async summary(): Promise<AdminSummary> {
    return normalizeAdminSummary(await this.request<unknown>("/api/admin/summary"));
  }

  async currentTaxonomy(): Promise<AdminTaxonomy | null> {
    return normalizeCurrentTaxonomy(
      await this.request<unknown>("/api/admin/taxonomies"),
    );
  }

  async listWorks(options: {
    query?: string;
    status?: string;
    seed?: "all" | "seed" | "reference";
    limit: number;
    offset: number;
  }): Promise<WorkListPage> {
    const params = new URLSearchParams({
      limit: String(options.limit),
      offset: String(options.offset),
    });
    if (options.query?.trim()) params.set("q", options.query.trim());
    if (options.status?.trim()) params.set("metadata_status", options.status.trim());
    if (options.seed && options.seed !== "all") {
      params.set("seed", options.seed === "seed" ? "true" : "false");
    }
    return normalizeWorkList(
      await this.request<unknown>(`/api/works?${params.toString()}`),
    );
  }

  async getWork(workId: string): Promise<WorkDetail> {
    return normalizeWorkDetail(
      await this.request<unknown>(`/api/works/${encodeURIComponent(workId)}`),
    );
  }

  async updateWork(
    workId: string,
    changes: WorkPatch,
    expectedUpdatedAt: string | null,
  ): Promise<WorkDetail> {
    return normalizeWorkDetail(
      await this.request<unknown>(`/api/works/${encodeURIComponent(workId)}`, {
        method: "PATCH",
        body: JSON.stringify({ changes, expected_updated_at: expectedUpdatedAt }),
      }),
    );
  }

  async addManualClassification(
    workId: string,
    classification: { dimension: string; category: string; confidence: number },
    expectedUpdatedAt: string | null,
    taxonomyVersion: string,
  ): Promise<WorkDetail> {
    return normalizeWorkDetail(
      await this.request<unknown>(
        `/api/works/${encodeURIComponent(workId)}/classifications`,
        {
          method: "POST",
          body: JSON.stringify({
            taxonomy_version: taxonomyVersion,
            dimension_id: classification.dimension,
            category_id: classification.category,
            confidence: classification.confidence,
            method: "manual",
            expected_updated_at: expectedUpdatedAt,
          }),
        },
      ),
    );
  }

  async deleteManualClassification(
    workId: string,
    classification: AdminClassification,
    expectedUpdatedAt: string | null,
  ): Promise<WorkDetail> {
    const suffix =
      classification.id == null
        ? `?${new URLSearchParams({
            dimension: classification.dimension,
            category: classification.category,
          }).toString()}`
        : `/${encodeURIComponent(String(classification.id))}`;
    return normalizeWorkDetail(
      await this.request<unknown>(
        `/api/works/${encodeURIComponent(workId)}/classifications${suffix}`,
        {
          method: "DELETE",
          body: JSON.stringify({ expected_updated_at: expectedUpdatedAt }),
        },
      ),
    );
  }
}
