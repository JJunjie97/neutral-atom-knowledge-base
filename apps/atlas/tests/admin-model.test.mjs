import assert from "node:assert/strict";
import test from "node:test";
import {
  normalizeCurrentTaxonomy,
  normalizeLoopbackApiUrl,
  normalizeWorkList,
} from "../app/admin/admin-api.ts";
import {
  draftFromDetail,
  patchFromDraft,
} from "../app/admin/admin-types.ts";

test("admin API URL is restricted to loopback HTTP", () => {
  assert.equal(
    normalizeLoopbackApiUrl("http://127.0.0.1:8765/"),
    "http://127.0.0.1:8765",
  );
  assert.equal(
    normalizeLoopbackApiUrl("http://localhost:8765"),
    "http://localhost:8765",
  );
  assert.throws(() => normalizeLoopbackApiUrl("https://example.com"), /回环地址/u);
  assert.throws(() => normalizeLoopbackApiUrl("http://192.168.1.2:8765"), /回环地址/u);
});

test("work list normalizer accepts backend snake_case fields", () => {
  const page = normalizeWorkList({
    items: [
      {
        paper_uid: "paper-1",
        title: "Neutral atom gates",
        publication_year: 2024,
        authors: '["Ada Lovelace", "Grace Hopper"]',
        metadata_status: "complete",
        is_seed: 1,
      },
    ],
    total: 81,
    limit: 25,
    offset: 50,
  });
  assert.equal(page.total, 81);
  assert.equal(page.offset, 50);
  assert.deepEqual(page.items[0].authors, ["Ada Lovelace", "Grace Hopper"]);
  assert.equal(page.items[0].seed, true);
});

test("missing admin titles retain a stable identity", () => {
  const page = normalizeWorkList({
    items: [{ work_id: 12, canonical_id: "openalex:W12", title: null }],
  });
  assert.equal(page.items[0].title, "Metadata unavailable \u00b7 openalex:W12");
});

test("taxonomy normalizer selects the current bilingual taxonomy", () => {
  const taxonomy = normalizeCurrentTaxonomy({
    current_version: "2026.07",
    taxonomies: [
      {
        version: "2026.07",
        dimensions: [
          {
            id: "atomic_element",
            label_zh: "原子元素",
            label_en: "Atomic element",
            categories: [
              { id: "rubidium", label_zh: "铷", label_en: "Rubidium" },
            ],
          },
        ],
      },
    ],
  });
  assert.equal(taxonomy?.version, "2026.07");
  assert.equal(taxonomy?.dimensions[0].categories[0].labelZh, "铷");
});

test("metadata patch excludes identifiers and normalizes author lines", () => {
  const detail = {
    id: "paper-1",
    work: {
      id: "paper-1",
      title: "A paper",
      abstract: "Abstract",
      year: 2025,
      authors: ["Alice", "Bob"],
      doi: "10.1000/example",
      topics_json: [{ id: "T1", name: "Quantum computing", score: 0.9 }],
      metadata_status: "complete",
    },
    identifiers: [],
    classifications: [],
    seedEntries: [],
    documents: [],
    citationCounts: {},
    raw: {},
  };
  const draft = draftFromDetail(detail);
  draft.authors = "Alice\nBob\nCarol";
  const patch = patchFromDraft(draft);
  assert.deepEqual(patch.authors, ["Alice", "Bob", "Carol"]);
  assert.equal("doi" in patch, false);
  assert.equal("topics" in patch, false);
  assert.equal(patch.abstract, "Abstract");
});
