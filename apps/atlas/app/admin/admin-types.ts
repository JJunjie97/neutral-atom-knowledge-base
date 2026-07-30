import type { JsonObject, WorkDetail, WorkPatch } from "./admin-api";

export type WorkDraft = {
  title: string;
  abstract: string;
  year: string;
  publicationDate: string;
  authors: string;
  venue: string;
  workType: string;
  url: string;
  oaUrl: string;
  metadataStatus: string;
};

function value(record: JsonObject, ...keys: string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null) return record[key];
  }
  return undefined;
}

function text(input: unknown): string {
  return typeof input === "string" ? input : input == null ? "" : String(input);
}

function listText(input: unknown): string {
  if (Array.isArray(input)) return input.map(text).filter(Boolean).join("\n");
  if (typeof input !== "string") return "";
  try {
    const parsed = JSON.parse(input) as unknown;
    if (Array.isArray(parsed)) return parsed.map(text).filter(Boolean).join("\n");
  } catch {
    // Existing human-authored text is already suitable for the textarea.
  }
  return input.replace(/\s*;\s*/gu, "\n");
}

function nullable(input: string): string | null {
  return input.trim() || null;
}

function list(input: string): string[] {
  return input
    .split(/[;\n]/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function draftFromDetail(detail: WorkDetail): WorkDraft {
  const work = detail.work;
  return {
    title: text(value(work, "title", "display_name")),
    abstract: text(value(work, "abstract", "abstract_text")),
    year: text(value(work, "year", "publication_year")),
    publicationDate: text(value(work, "publication_date", "date")),
    authors: listText(value(work, "authors", "author_names")),
    venue: text(value(work, "venue", "journal", "host_venue")),
    workType: text(value(work, "work_type", "type")),
    url: text(value(work, "url", "landing_page_url")),
    oaUrl: text(value(work, "oa_url", "open_access_url")),
    metadataStatus: text(value(work, "metadata_status", "status")),
  };
}

export function patchFromDraft(draft: WorkDraft): WorkPatch {
  const yearText = draft.year.trim();
  const year = yearText ? Number(yearText) : null;
  if (year != null && (!Number.isInteger(year) || year < 1600 || year > 2200)) {
    throw new Error("发表年份应为 1600—2200 之间的整数，或留空。 ");
  }
  for (const [label, url] of [
    ["Landing URL", draft.url],
    ["Open access URL", draft.oaUrl],
  ] as const) {
    if (!url.trim()) continue;
    try {
      const parsed = new URL(url.trim());
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error();
    } catch {
      throw new Error(`${label} 必须是有效的 HTTP(S) URL，或留空。`);
    }
  }
  return {
    title: nullable(draft.title),
    abstract: nullable(draft.abstract),
    year,
    publication_date: nullable(draft.publicationDate),
    authors: list(draft.authors),
    venue: nullable(draft.venue),
    work_type: nullable(draft.workType),
    url: nullable(draft.url),
    oa_url: nullable(draft.oaUrl),
    metadata_status: nullable(draft.metadataStatus),
  };
}

export function updatedAtFromDetail(detail: WorkDetail): string | null {
  const candidate = value(
    detail.work,
    "admin_version",
    "version_token",
    "updated_at",
    "updatedAt",
  );
  return typeof candidate === "string" && candidate.trim() ? candidate : null;
}
