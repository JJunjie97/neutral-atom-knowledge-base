from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .bibtex import (
    clean_latex_text,
    load_bibtex,
    normalize_doi,
    normalize_title,
    scan_tex_citations,
)
from .db import LiteratureDB
from .openalex import OpenAlexClient, OpenAlexError, chunks, short_openalex_id


def ingest(
    db: LiteratureDB, bib_path: str | Path, tex_dir: str | Path | None
) -> dict[str, int]:
    entries = load_bibtex(bib_path)
    citation_map = scan_tex_citations(tex_dir) if tex_dir else {}
    return db.ingest_bib_entries(entries, citation_map)


def _authors(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for authorship in payload.get("authorships") or []:
        name = (authorship.get("author") or {}).get("display_name")
        if name:
            names.append(name)
    return names


def _venue(payload: dict[str, Any]) -> str | None:
    location = payload.get("primary_location") or {}
    source = location.get("source") or {}
    return source.get("display_name")


def _landing_url(payload: dict[str, Any]) -> str | None:
    location = payload.get("primary_location") or {}
    return location.get("landing_page_url")


def _oa_url(payload: dict[str, Any]) -> str | None:
    location = payload.get("best_oa_location") or {}
    return location.get("pdf_url") or location.get("landing_page_url")


def _topics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for topic in payload.get("topics") or []:
        if topic.get("id") and topic.get("display_name"):
            result.append(
                {
                    "id": topic["id"].rsplit("/", 1)[-1],
                    "name": topic["display_name"],
                    "score": topic.get("score"),
                }
            )
    return result


def _abstract(payload: dict[str, Any]) -> str | None:
    inverted = payload.get("abstract_inverted_index")
    if not isinstance(inverted, dict):
        return None
    positioned_words: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                positioned_words.append((position, word))
    positioned_words.sort(key=lambda item: item[0])
    return " ".join(word for _, word in positioned_words).strip() or None


def upsert_openalex_payload(
    db: LiteratureDB,
    payload: dict[str, Any],
    *,
    preferred_work_id: int | None = None,
    is_seed: bool = False,
) -> int:
    openalex_id = short_openalex_id(payload.get("id"))
    if not openalex_id:
        raise ValueError("OpenAlex payload has no valid work id")
    doi = normalize_doi(payload.get("doi"))
    identifiers = [("openalex", openalex_id)]
    if doi:
        identifiers.append(("doi", doi))
    title = payload.get("title") or payload.get("display_name")
    data = {
        "title": title,
        "title_source": "openalex" if title else None,
        "metadata_status": "complete" if title else "no_title",
        "entity_kind": "scholarly_work",
        "year": payload.get("publication_year"),
        "publication_date": payload.get("publication_date"),
        "venue": _venue(payload),
        "work_type": payload.get("type"),
        "abstract": _abstract(payload),
        "url": _landing_url(payload),
        "oa_url": _oa_url(payload),
        "doi": doi,
        "openalex_id": openalex_id,
        "authors_json": _authors(payload),
        "topics_json": _topics(payload),
        "citation_count": payload.get("cited_by_count"),
        "reference_count": payload.get("referenced_works_count"),
    }
    work_id = db.upsert_work(
        data,
        identifiers,
        is_seed=is_seed,
        preferred_work_id=preferred_work_id,
    )
    db.save_provider_record("openalex", openalex_id, payload)
    return work_id


def _surname(name: str) -> str:
    name = normalize_title(name)
    return name.split()[-1] if name else ""


def score_title_candidate(
    seed: dict[str, Any], candidate: dict[str, Any]
) -> tuple[float, dict[str, Any]]:
    seed_title = normalize_title(seed.get("title"))
    candidate_title = normalize_title(
        candidate.get("title") or candidate.get("display_name")
    )
    title_score = SequenceMatcher(None, seed_title, candidate_title).ratio()
    seed_year = seed.get("year")
    candidate_year = candidate.get("publication_year")
    if seed_year and candidate_year:
        delta = abs(int(seed_year) - int(candidate_year))
        year_score = 1.0 if delta == 0 else (0.5 if delta == 1 else 0.0)
    else:
        delta = None
        year_score = 0.5
    seed_authors = {_surname(name) for name in seed.get("authors", [])}
    candidate_authors = {_surname(name) for name in _authors(candidate)}
    seed_authors.discard("")
    candidate_authors.discard("")
    author_overlap = (
        len(seed_authors & candidate_authors) / max(1, min(len(seed_authors), 3))
        if seed_authors and candidate_authors
        else 0.0
    )
    score = 0.86 * title_score + 0.08 * year_score + 0.06 * min(author_overlap, 1)
    evidence = {
        "seed_title_normalized": seed_title,
        "candidate_title_normalized": candidate_title,
        "title_score": round(title_score, 6),
        "seed_year": seed_year,
        "candidate_year": candidate_year,
        "year_delta": delta,
        "author_overlap": round(author_overlap, 6),
    }
    return score, evidence


def resolve_openalex_seeds(
    db: LiteratureDB,
    client: OpenAlexClient,
    *,
    limit: int | None = None,
    title_search: bool = True,
    accept_score: float = 0.91,
    ambiguity_gap: float = 0.025,
) -> dict[str, int]:
    rows = db.seed_rows(unresolved_provider="openalex")
    if limit is not None:
        rows = rows[:limit]
    counts = {
        "considered": len(rows),
        "resolved_by_doi": 0,
        "resolved_by_title": 0,
        "needs_review": 0,
        "not_found": 0,
        "errors": 0,
    }
    by_doi = {row["doi"]: row for row in rows if row["doi"]}

    doi_batches = list(chunks(list(by_doi), 100))
    for batch_index, batch in enumerate(doi_batches, start=1):
        print(
            f"[OpenAlex] DOI batch {batch_index}/{len(doi_batches)} "
            f"({len(batch)} records)", flush=True
        )
        results = client.works_by_dois(batch)
        returned: set[str] = set()
        with db.transaction():
            for payload in results:
                doi = normalize_doi(payload.get("doi"))
                seed = by_doi.get(doi)
                if not seed:
                    continue
                returned.add(doi)
                openalex_id = short_openalex_id(payload.get("id"))
                work_id = upsert_openalex_payload(
                    db,
                    payload,
                    preferred_work_id=int(seed["work_id"]),
                    is_seed=True,
                )
                db.record_match(
                    seed["bib_key"],
                    "openalex",
                    openalex_id,
                    "doi",
                    1.0,
                    "accepted",
                    {"doi": doi},
                )
                db.mark_fetch("openalex", work_id, "resolve", "done")
                counts["resolved_by_doi"] += 1
            for doi in set(batch) - returned:
                seed = by_doi[doi]
                db.record_match(
                    seed["bib_key"],
                    "openalex",
                    None,
                    "doi",
                    None,
                    "not_found",
                    {"doi": doi},
                )

    if not title_search:
        return counts

    remaining = db.seed_rows(unresolved_provider="openalex")
    selected_keys = {row["bib_key"] for row in rows}
    remaining = [row for row in remaining if row["bib_key"] in selected_keys]
    for row_index, row in enumerate(remaining, start=1):
        print(
            f"[OpenAlex] title match {row_index}/{len(remaining)}: "
            f"{row['bib_key']}", flush=True
        )
        raw = json.loads(row["raw_json"])
        title = clean_latex_text(raw.get("title")) or row["title"]
        if not title:
            counts["not_found"] += 1
            db.record_match(
                row["bib_key"],
                "openalex",
                None,
                "title",
                None,
                "not_found",
                {"reason": "missing title"},
            )
            db.conn.commit()
            continue
        seed_data = {
            "title": title,
            "year": row["year"],
            "authors": json.loads(row["authors_json"] or "[]"),
        }
        try:
            candidates = client.search_work(title, row["year"])
        except OpenAlexError as exc:
            counts["errors"] += 1
            db.record_match(
                row["bib_key"],
                "openalex",
                None,
                "title",
                None,
                "error",
                {"query": title, "error": str(exc)},
            )
            db.conn.commit()
            print(
                f"[OpenAlex] skipped {row['bib_key']}: {exc}",
                flush=True,
            )
            continue
        scored = sorted(
            (
                (*score_title_candidate(seed_data, candidate), candidate)
                for candidate in candidates
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scored:
            counts["not_found"] += 1
            db.record_match(
                row["bib_key"],
                "openalex",
                None,
                "title",
                None,
                "not_found",
                {"query": title},
            )
            db.conn.commit()
            continue
        best_score, evidence, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        exact_title = evidence["seed_title_normalized"] == evidence["candidate_title_normalized"]
        accepted = (best_score >= accept_score or exact_title) and (
            exact_title or best_score - runner_up >= ambiguity_gap
        )
        openalex_id = short_openalex_id(best.get("id"))
        evidence.update(
            {
                "query": title,
                "runner_up_score": round(runner_up, 6),
                "candidate_title": best.get("title") or best.get("display_name"),
            }
        )
        with db.transaction():
            if accepted:
                work_id = upsert_openalex_payload(
                    db,
                    best,
                    preferred_work_id=int(row["work_id"]),
                    is_seed=True,
                )
                db.mark_fetch("openalex", work_id, "resolve", "done")
                counts["resolved_by_title"] += 1
                status = "accepted"
            else:
                counts["needs_review"] += 1
                status = "needs_review"
            db.record_match(
                row["bib_key"],
                "openalex",
                openalex_id,
                "title",
                round(best_score, 6),
                status,
                evidence,
            )
    return counts


def discover_openalex_references(
    db: LiteratureDB,
    client: OpenAlexClient,
    *,
    limit_seeds: int | None = None,
) -> dict[str, int]:
    pending_rows = []
    seen_work_ids: set[int] = set()
    for row in db.resolved_seed_rows("openalex"):
        work_id = int(row["work_id"])
        if work_id in seen_work_ids:
            continue
        seen_work_ids.add(work_id)
        done = db.conn.execute(
            """
            SELECT 1 FROM fetch_status
            WHERE provider='openalex' AND work_id=? AND operation='references'
              AND status='done'
            """,
            (work_id,),
        ).fetchone()
        if not done:
            pending_rows.append(row)
    rows = pending_rows[:limit_seeds] if limit_seeds is not None else pending_rows
    counts = {"seeds": 0, "edges_added": 0, "empty_reference_lists": 0}
    for row_index, row in enumerate(rows, start=1):
        print(
            f"[OpenAlex] references {row_index}/{len(rows)}: "
            f"{row['bib_key']}", flush=True
        )
        try:
            payload = db.get_provider_record("openalex", row["openalex_id"])
            if payload is None or "referenced_works" not in payload:
                payload = client.work(row["openalex_id"])
            with db.transaction():
                source_id = upsert_openalex_payload(
                    db,
                    payload,
                    preferred_work_id=int(row["work_id"]),
                    is_seed=True,
                )
                reference_ids = [
                    value
                    for item in payload.get("referenced_works") or []
                    if (value := short_openalex_id(item))
                ]
                if not reference_ids:
                    counts["empty_reference_lists"] += 1
                for openalex_id in dict.fromkeys(reference_ids):
                    target_id = db.upsert_work(
                        {"openalex_id": openalex_id},
                        [("openalex", openalex_id)],
                    )
                    before = db.conn.total_changes
                    db.add_citation(source_id, target_id, "openalex")
                    counts["edges_added"] += int(db.conn.total_changes > before)
                db.mark_fetch("openalex", source_id, "references", "done")
            counts["seeds"] += 1
        except Exception as exc:
            db.mark_fetch(
                "openalex", int(row["work_id"]), "references", "error", str(exc)
            )
            db.conn.commit()
            raise
    return counts


def fetch_openalex_reference_metadata(
    db: LiteratureDB,
    client: OpenAlexClient,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    rows = db.pending_reference_metadata(
        "openalex", include_not_found=client.refresh
    )
    if limit is not None:
        rows = rows[:limit]
    by_id = {row["openalex_id"]: row for row in rows}
    counts = {
        "requested": len(rows),
        "fetched": 0,
        "without_title": 0,
        "not_found": 0,
    }
    metadata_batches = list(chunks(list(by_id), 100))
    for batch_index, batch in enumerate(metadata_batches, start=1):
        print(
            f"[OpenAlex] reference metadata batch "
            f"{batch_index}/{len(metadata_batches)} ({len(batch)} records)",
            flush=True,
        )
        payloads = client.works_by_ids(batch)
        returned: set[str] = set()
        with db.transaction():
            for payload in payloads:
                openalex_id = short_openalex_id(payload.get("id"))
                if not openalex_id:
                    continue
                returned.add(openalex_id)
                preferred = by_id.get(openalex_id)
                work_id = upsert_openalex_payload(
                    db,
                    payload,
                    preferred_work_id=(
                        int(preferred["work_id"]) if preferred is not None else None
                    ),
                )
                title = payload.get("title") or payload.get("display_name")
                if title:
                    db.mark_fetch("openalex", work_id, "metadata", "done")
                    counts["fetched"] += 1
                else:
                    db.mark_fetch(
                        "openalex",
                        work_id,
                        "metadata",
                        "no_title",
                        "OpenAlex record has no title",
                    )
                    counts["without_title"] += 1
            for missing in set(batch) - returned:
                row = by_id[missing]
                db.mark_fetch(
                    "openalex",
                    int(row["work_id"]),
                    "metadata",
                    "not_found",
                    "OpenAlex batch did not return this id",
                )
                counts["not_found"] += 1
    return counts


def repair_openalex_doi_titles(
    db: LiteratureDB,
    client: OpenAlexClient,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    rows = db.conn.execute(
        """
        SELECT * FROM works
        WHERE (title IS NULL OR trim(title)='') AND doi IS NOT NULL
        ORDER BY work_id
        """
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    by_doi = {normalize_doi(row["doi"]): row for row in rows}
    counts = {"requested": len(rows), "recovered": 0, "without_title": 0}
    for batch_index, batch in enumerate(chunks(list(by_doi), 50), start=1):
        print(
            f"[OpenAlex] DOI title repair batch {batch_index} "
            f"({len(batch)} records)",
            flush=True,
        )
        payloads = client.works_by_dois(batch)
        with db.transaction():
            for payload in payloads:
                doi = normalize_doi(payload.get("doi"))
                row = by_doi.get(doi)
                if row is None:
                    continue
                title = payload.get("title") or payload.get("display_name")
                if not title:
                    counts["without_title"] += 1
                    continue
                work_id = upsert_openalex_payload(
                    db,
                    payload,
                    preferred_work_id=int(row["work_id"]),
                )
                primary_openalex = short_openalex_id(payload.get("id"))
                db.conn.execute(
                    """
                    UPDATE works
                    SET openalex_id=?,title_source='openalex_doi',
                        metadata_status='complete'
                    WHERE work_id=?
                    """,
                    (primary_openalex, work_id),
                )
                db.mark_fetch("openalex", work_id, "title_repair", "done")
                counts["recovered"] += 1
    return counts


def fetch_openalex_abstracts(    db: LiteratureDB,
    client: OpenAlexClient,
    *,
    limit: int | None = None,
) -> dict[str, int]:
    rows = db.pending_abstract_metadata(
        "openalex", include_processed=client.refresh
    )
    if limit is not None:
        rows = rows[:limit]
    by_id = {row["openalex_id"]: row for row in rows}
    counts = {
        "requested": len(rows),
        "fetched": 0,
        "without_abstract": 0,
        "not_found": 0,
    }
    abstract_batches = list(chunks(list(by_id), 100))
    for batch_index, batch in enumerate(abstract_batches, start=1):
        print(
            f"[OpenAlex] abstract batch {batch_index}/"
            f"{len(abstract_batches)} ({len(batch)} records)",
            flush=True,
        )
        payloads = client.works_by_ids(batch)
        returned: set[str] = set()
        with db.transaction():
            for payload in payloads:
                openalex_id = short_openalex_id(payload.get("id"))
                if not openalex_id:
                    continue
                returned.add(openalex_id)
                preferred = by_id.get(openalex_id)
                work_id = upsert_openalex_payload(
                    db,
                    payload,
                    preferred_work_id=(
                        int(preferred["work_id"])
                        if preferred is not None
                        else None
                    ),
                )
                if _abstract(payload):
                    db.mark_fetch("openalex", work_id, "abstract", "done")
                    counts["fetched"] += 1
                else:
                    db.mark_fetch(
                        "openalex",
                        work_id,
                        "abstract",
                        "no_abstract",
                        "OpenAlex record has no abstract",
                    )
                    counts["without_abstract"] += 1
            for missing in set(batch) - returned:
                row = by_id[missing]
                db.mark_fetch(
                    "openalex",
                    int(row["work_id"]),
                    "abstract",
                    "not_found",
                    "OpenAlex batch did not return this id",
                )
                counts["not_found"] += 1
    return counts

def crawl_openalex(
    db: LiteratureDB,
    client: OpenAlexClient,
    *,
    limit_seeds: int | None = None,
    limit_reference_records: int | None = None,
    title_search: bool = True,
) -> dict[str, Any]:
    return {
        "resolve": resolve_openalex_seeds(
            db, client, limit=limit_seeds, title_search=title_search
        ),
        "references": discover_openalex_references(
            db, client, limit_seeds=limit_seeds
        ),
        "reference_metadata": fetch_openalex_reference_metadata(
            db, client, limit=limit_reference_records
        ),
        "database": db.stats(),
    }
