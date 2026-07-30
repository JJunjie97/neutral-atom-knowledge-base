from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Any, Callable, Iterable

from .classification import Taxonomy, TaxonomyError, classify_works
from .db import LiteratureDB, utc_now


DERIVED_METHODS = ("review_hierarchy", "venue_metadata")

VENUE_ALIASES = {
    "arxiv": "arXiv",
    "arxiv (cornell university)": "arXiv",
    "nat. commun": "Nature Communications",
    "nat. phys": "Nature Physics",
    "new j. phys": "New Journal of Physics",
    "phys. rev. a": "Physical Review A",
    "phys. rev. applied": "Physical Review Applied",
    "phys. rev. b": "Physical Review B",
    "phys. rev. d": "Physical Review D",
    "phys. rev. e": "Physical Review E",
    "phys. rev. lett": "Physical Review Letters",
    "phys. rev. research": "Physical Review Research",
    "phys. rev. x": "Physical Review X",
    "rev. sci. instrum": "Review of Scientific Instruments",
    "sci. adv": "Science Advances",
}


def _short_openalex_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.rsplit("/", 1)[-1].upper()
    return candidate if re.fullmatch(r"[TW]\d+", candidate) else None


def _nested_label(value: Any) -> str | None:
    if isinstance(value, dict):
        label = value.get("display_name") or value.get("name")
        return str(label).strip() if label else None
    return None


def topics_from_cached_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return compact OpenAlex topics while retaining useful hierarchy labels."""

    raw_topics = payload.get("topics")
    if not isinstance(raw_topics, list):
        raw_topics = []
    primary = payload.get("primary_topic")
    if not raw_topics and isinstance(primary, dict):
        raw_topics = [primary]
    primary_id = _short_openalex_id((primary or {}).get("id")) if isinstance(primary, dict) else None
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_topics:
        if not isinstance(raw, dict):
            continue
        topic_id = _short_openalex_id(raw.get("id"))
        name = raw.get("display_name")
        if not topic_id or not name or topic_id in seen:
            continue
        seen.add(topic_id)
        topic = {
            "id": topic_id,
            "name": str(name),
            "score": raw.get("score"),
            "primary": topic_id == primary_id,
            "subfield": _nested_label(raw.get("subfield")),
            "field": _nested_label(raw.get("field")),
            "domain": _nested_label(raw.get("domain")),
        }
        result.append({key: value for key, value in topic.items() if value is not None})
    return result


def backfill_cached_openalex_topics(
    db: LiteratureDB,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Backfill empty ``topics_json`` using provider_records, without network I/O."""

    rows = db.conn.execute(
        """
        SELECT w.work_id,p.payload_json
        FROM works w
        JOIN provider_records p
          ON p.provider='openalex' AND p.provider_id=w.openalex_id
        WHERE w.topics_json IS NULL OR trim(w.topics_json) IN ('','[]')
        ORDER BY w.work_id
        """
    ).fetchall()
    result = {
        "considered": len(rows),
        "updated": 0,
        "without_topics": 0,
        "invalid_payloads": 0,
    }
    updates: list[tuple[str, str, int]] = []
    for position, row in enumerate(rows, start=1):
        if progress and (position % 2000 == 0 or position == len(rows)):
            progress(
                f"[Classify] cached OpenAlex topics {position}/{len(rows)} records"
            )
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            result["invalid_payloads"] += 1
            continue
        if not isinstance(payload, dict):
            result["invalid_payloads"] += 1
            continue
        topics = topics_from_cached_payload(payload)
        if not topics:
            result["without_topics"] += 1
            continue
        updates.append(
            (
                json.dumps(topics, ensure_ascii=False, sort_keys=True),
                utc_now(),
                int(row["work_id"]),
            )
        )
    if updates:
        with db.transaction():
            db.conn.executemany(
                "UPDATE works SET topics_json=?,updated_at=? WHERE work_id=?",
                updates,
            )
    result["updated"] = len(updates)
    return result


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").casefold()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-") or "category"
    digest = hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()[:8]
    return f"{base[:72]}-{digest}"


def normalize_venue(value: str) -> str:
    """Normalize common journal abbreviations without inferring a topic."""

    label = re.sub(r"\s+", " ", value).strip()
    key = label.casefold().rstrip(".")
    return VENUE_ALIASES.get(key, label)


def _json_list(value: str | None) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _dynamic_assignment(
    work_id: int,
    dimension: str,
    label: str,
    method: str,
    confidence: float,
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "work_id": work_id,
        "dimension_id": dimension,
        "category_id": _slug(label),
        "label": label,
        "method": method,
        "confidence": confidence,
        "matches": matches,
    }


def _derived_assignments(
    db: LiteratureDB, *, work_ids: set[int]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    grouped: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    dynamic_labels: dict[str, dict[str, str]] = defaultdict(dict)

    if work_ids:
        placeholders = ",".join("?" for _ in work_ids)
        for mention in db.conn.execute(
            f"""
            SELECT work_id,mention_id,source_file,section_path_json
            FROM review_mentions
            WHERE work_id IN ({placeholders})
            ORDER BY work_id,mention_id
            """,
            sorted(work_ids),
        ):
            work_id = int(mention["work_id"])
            path = [str(item) for item in _json_list(mention["section_path_json"]) if item]
            if not path:
                continue
            candidates = [("review_section", path[0], 0.98)]
            if len(path) > 1:
                topic_label = " > ".join(path)
                candidates.append(("review_topic", topic_label, 0.95))
            for dimension, label, confidence in candidates:
                category = _slug(label)
                dynamic_labels[dimension][category] = label
                key = (work_id, dimension, category, "review_hierarchy")
                assignment = grouped.setdefault(
                    key,
                    _dynamic_assignment(
                        work_id,
                        dimension,
                        label,
                        "review_hierarchy",
                        confidence,
                        [],
                    ),
                )
                assignment["matches"].append(
                    {
                        "kind": "review_hierarchy",
                        "value": label,
                        "field": "review_section",
                        "mention_id": mention["mention_id"],
                        "source_file": mention["source_file"],
                        "heading": path[-1],
                    }
                )

        for work in db.conn.execute(
            f"""
            SELECT work_id,venue FROM works
            WHERE work_id IN ({placeholders})
              AND venue IS NOT NULL AND trim(venue)<>''
            ORDER BY work_id
            """,
            sorted(work_ids),
        ):
            raw_label = str(work["venue"])
            label = normalize_venue(raw_label)
            category = _slug(label)
            dynamic_labels["venue"][category] = label
            key = (int(work["work_id"]), "venue", category, "venue_metadata")
            grouped[key] = _dynamic_assignment(
                int(work["work_id"]),
                "venue",
                label,
                "venue_metadata",
                1.0,
                [{"kind": "metadata", "value": label, "field": "venue"}],
            )

    assignments = list(grouped.values())
    for assignment in assignments:
        unique = {
            (
                item["kind"],
                item["value"],
                item["field"],
                item.get("mention_id", ""),
            ): item
            for item in assignment["matches"]
        }
        assignment["matches"] = [unique[key] for key in sorted(unique)]
    return assignments, dynamic_labels


def _merge_manifest(
    taxonomy: Taxonomy, dynamic_labels: dict[str, dict[str, str]]
) -> dict[str, Any]:
    dimensions = [dict(dimension) for dimension in taxonomy.dimensions]
    definitions = {
        "review_section": {
            "label_en": "Review section",
            "label_zh": "综述章节",
            "description_en": "Top-level section in which the review cites the work.",
            "description_zh": "该文献在综述中被引用的一级章节；允许多标签。",
        },
        "review_topic": {
            "label_en": "Review topic",
            "label_zh": "综述主题",
            "description_en": "Deepest review heading associated with a citation.",
            "description_zh": "引用位置对应的最深层综述标题路径；允许多标签。",
        },
        "venue": {
            "label_en": "Venue",
            "label_zh": "发表期刊或会议",
            "description_en": "Normalized publication venue metadata; not a topic inference.",
            "description_zh": "规范化发表载体元数据，不作为主题分类结论。",
        },
    }
    by_id = {dimension["id"]: dimension for dimension in dimensions}
    for dimension_id, labels in sorted(dynamic_labels.items()):
        categories = [
            {
                "id": category_id,
                "label_en": label,
                "label_zh": label,
            }
            for category_id, label in sorted(
                labels.items(), key=lambda item: item[1].casefold()
            )
        ]
        if dimension_id in by_id:
            known = {
                category["id"]
                for category in by_id[dimension_id].get("categories", [])
            }
            by_id[dimension_id]["categories"] = (
                list(by_id[dimension_id].get("categories", []))
                + [category for category in categories if category["id"] not in known]
            )
            continue
        definition = definitions[dimension_id]
        dimension = {
            "id": dimension_id,
            **definition,
            "multi": dimension_id != "venue",
            "dynamic": True,
            "categories": categories,
        }
        dimensions.append(dimension)
        by_id[dimension_id] = dimension
    return {
        "version": taxonomy.version,
        "digest": taxonomy.digest,
        "field_weights": taxonomy.field_weights,
        "dimensions": dimensions,
    }


def _register_manifest(
    db: LiteratureDB, taxonomy: Taxonomy, manifest: dict[str, Any]
) -> None:
    existing = db.conn.execute(
        """
        SELECT taxonomy_digest FROM taxonomy_definitions
        WHERE taxonomy_version=?
        """,
        (taxonomy.version,),
    ).fetchone()
    if existing and existing["taxonomy_digest"] != taxonomy.digest:
        raise TaxonomyError(
            f"taxonomy version {taxonomy.version!r} already exists with a "
            "different digest; bump the version before changing rules"
        )
    now = utc_now()
    db.conn.execute(
        """
        INSERT INTO taxonomy_definitions(
          taxonomy_version,taxonomy_digest,definition_json,created_at,updated_at
        ) VALUES(?,?,?,?,?)
        ON CONFLICT(taxonomy_version) DO UPDATE SET
          definition_json=excluded.definition_json,
          updated_at=excluded.updated_at
        """,
        (
            taxonomy.version,
            taxonomy.digest,
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            now,
            now,
        ),
    )


def classify_facets(
    db: LiteratureDB,
    taxonomy: Taxonomy,
    *,
    seed_only: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Backfill cached metadata, run rules, and derive review/venue facets."""

    existing = db.conn.execute(
        "SELECT taxonomy_digest FROM taxonomy_definitions WHERE taxonomy_version=?",
        (taxonomy.version,),
    ).fetchone()
    if existing and existing["taxonomy_digest"] != taxonomy.digest:
        raise TaxonomyError(
            f"taxonomy version {taxonomy.version!r} already exists with a "
            "different digest; bump the version before changing rules"
        )
    if progress:
        progress("[Classify] restoring topics from the local OpenAlex cache")
    cached_topics = backfill_cached_openalex_topics(db, progress=progress)
    if progress:
        progress(
            f"[Classify] applying {len(taxonomy.rules)} deterministic taxonomy rules"
        )
    rule_result = classify_works(
        db, taxonomy, seed_only=seed_only, progress=progress
    )
    where = "WHERE is_seed=1" if seed_only else ""
    work_ids = {
        int(row["work_id"])
        for row in db.conn.execute(f"SELECT work_id FROM works {where}")
    }
    if progress:
        progress("[Classify] deriving review hierarchy and publication venues")
    derived, dynamic_labels = _derived_assignments(db, work_ids=work_ids)
    manifest = _merge_manifest(taxonomy, dynamic_labels)
    with db.transaction():
        _register_manifest(db, taxonomy, manifest)
        seed_scope = (
            " AND work_id IN (SELECT work_id FROM works WHERE is_seed=1)"
            if seed_only
            else ""
        )
        db.conn.execute(
            f"""
            DELETE FROM work_classifications
            WHERE method IN ({','.join('?' for _ in DERIVED_METHODS)})
            {seed_scope}
            """,
            list(DERIVED_METHODS),
        )
        for assignment in derived:
            now = utc_now()
            db.conn.execute(
                """
                INSERT INTO work_classifications(
                  work_id,taxonomy_version,taxonomy_digest,dimension_id,
                  category_id,method,confidence,evidence_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    assignment["work_id"],
                    taxonomy.version,
                    taxonomy.digest,
                    assignment["dimension_id"],
                    assignment["category_id"],
                    assignment["method"],
                    assignment["confidence"],
                    json.dumps(
                        {
                            "label": assignment["label"],
                            "matches": assignment["matches"],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    now,
                ),
            )
    if progress:
        progress("[Classify] classification committed")
    return {
        "cached_openalex_topics": cached_topics,
        "rules": rule_result,
        "derived_assignments": len(derived),
        "dynamic_dimensions": {
            dimension: len(categories)
            for dimension, categories in sorted(dynamic_labels.items())
        },
        "database": db.stats(),
    }


def taxonomy_manifest(db: LiteratureDB) -> dict[str, Any]:
    row = db.conn.execute(
        """
        SELECT definition_json FROM taxonomy_definitions
        ORDER BY updated_at DESC,taxonomy_version DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return {"version": None, "dimensions": []}
    try:
        payload = json.loads(row["definition_json"])
    except json.JSONDecodeError:
        return {"version": None, "dimensions": []}
    return payload if isinstance(payload, dict) else {"version": None, "dimensions": []}


def compact_classification_rows(
    db: LiteratureDB, work_ids: Iterable[int] | None = None
) -> dict[int, list[dict[str, Any]]]:
    manifest = taxonomy_manifest(db)
    active_version = manifest.get("version")
    clauses: list[str] = []
    params: list[Any] = []
    if active_version:
        clauses.append("(taxonomy_version=? OR method='manual')")
        params.append(active_version)
    else:
        clauses.append("method='manual'")
    if work_ids is not None:
        ids = sorted({int(work_id) for work_id in work_ids})
        if not ids:
            return {}
        clauses.append(f"work_id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    where = "WHERE " + " AND ".join(clauses)
    mention_rows = {
        str(row["mention_id"]): row
        for row in db.conn.execute(
            """
            SELECT mention_id,source_file,section_path_json
            FROM review_mentions
            """
        )
    }
    result: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in db.conn.execute(
        f"""
        SELECT work_id,taxonomy_version,dimension_id,category_id,
               method,confidence,evidence_json
        FROM work_classifications
        {where}
        ORDER BY work_id,dimension_id,category_id,method
        """,
        params,
    ):
        try:
            evidence = json.loads(row["evidence_json"] or "{}")
        except json.JSONDecodeError:
            evidence = {}
        matches = evidence.get("matches") if isinstance(evidence, dict) else []
        if not isinstance(matches, list):
            matches = []
        signals: dict[tuple[str, str, str], dict[str, str]] = {}
        sources: dict[tuple[str, str], dict[str, str]] = {}
        for match in matches:
            if not isinstance(match, dict):
                continue
            kind = str(match.get("kind") or "")
            value = str(match.get("value") or "")
            field = str(match.get("field") or "")
            if kind and value and field:
                signals[(kind, value, field)] = {
                    "kind": kind,
                    "value": value,
                    "field": field,
                }
            mention_id = str(match.get("mention_id") or "")
            mention = mention_rows.get(mention_id)
            if mention:
                section_path = [
                    str(item) for item in _json_list(mention["section_path_json"])
                ]
                source_file = str(mention["source_file"])
                heading = section_path[-1] if section_path else ""
                sources[(source_file, heading)] = {
                    "source_file": source_file,
                    "heading": heading,
                    "mention_id": mention_id,
                }
        result[int(row["work_id"])].append(
            {
                "taxonomy_version": row["taxonomy_version"],
                "dimension": row["dimension_id"],
                "category": row["category_id"],
                "method": row["method"],
                "confidence": row["confidence"],
                "rule_ids": (
                    evidence.get("rule_ids", [])
                    if isinstance(evidence, dict)
                    else []
                ),
                "signals": [signals[key] for key in sorted(signals)][:12],
                "review_sources": [sources[key] for key in sorted(sources)][:8],
            }
        )
    return dict(result)
