from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .db import LiteratureDB, utc_now


def _decode(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


def _normalize_identifier(value: str) -> str:
    text = value.strip()
    lowered = text.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip().lower()
    if lowered.startswith("https://openalex.org/"):
        return text.rsplit("/", 1)[-1].upper()
    if lowered.startswith("arxiv:"):
        return text.split(":", 1)[1].strip().lower()
    return text


def display_title(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip()
    if title:
        return title
    if row.get("entity_kind") == "private_communication":
        return "Private communication"
    for label, field in (
        ("DOI", "doi"),
        ("arXiv", "arxiv_id"),
        ("OpenAlex", "openalex_id"),
    ):
        if row.get(field):
            return f"Metadata unavailable - {label} {row[field]}"
    return f"Metadata unavailable - {row.get('paper_uid') or row.get('canonical_id')}"


def resolve_work_id(db: LiteratureDB, identifier: str) -> int:
    """Resolve paper_uid, canonical ID, DOI, arXiv or OpenAlex ID."""
    raw = identifier.strip()
    value = _normalize_identifier(raw)
    row = db.conn.execute(
        """
        SELECT work_id FROM works
        WHERE paper_uid=? OR canonical_id=? OR doi=? OR arxiv_id=?
           OR openalex_id=? OR s2_id=?
        LIMIT 1
        """,
        (raw, raw, value.lower(), value.lower(), value.upper(), value),
    ).fetchone()
    if not row:
        row = db.conn.execute(
            """
            SELECT work_id FROM identifiers
            WHERE value IN (?,?,?)
            ORDER BY CASE scheme
              WHEN 'doi' THEN 0 WHEN 'arxiv' THEN 1 WHEN 'openalex' THEN 2 ELSE 3
            END LIMIT 1
            """,
            (raw, value.lower(), value.upper()),
        ).fetchone()
    if not row:
        raise KeyError(f"paper not found: {identifier}")
    return int(row["work_id"])


def _compact_work(db: LiteratureDB, work_id: int) -> dict[str, Any]:
    row = db.conn.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
    if not row:
        raise KeyError(f"unknown work_id: {work_id}")
    item = dict(row)
    return {
        "paper_uid": item["paper_uid"],
        "canonical_id": item["canonical_id"],
        "title": item["title"],
        "display_title": display_title(item),
        "title_missing": not bool(str(item.get("title") or "").strip()),
        "metadata_status": item["metadata_status"],
        "entity_kind": item["entity_kind"],
        "year": item["year"],
        "authors": _decode(item["authors_json"], []),
        "venue": item["venue"],
        "doi": item["doi"],
        "arxiv_id": item["arxiv_id"],
        "openalex_id": item["openalex_id"],
        "is_seed": bool(item["is_seed"]),
    }


def get_work(db: LiteratureDB, identifier: str) -> dict[str, Any]:
    work_id = resolve_work_id(db, identifier)
    record = _compact_work(db, work_id)
    identifiers: dict[str, list[str]] = defaultdict(list)
    for row in db.conn.execute(
        "SELECT scheme,value FROM identifiers WHERE work_id=? ORDER BY scheme,value",
        (work_id,),
    ):
        identifiers[row["scheme"]].append(row["value"])
    record["identifiers"] = dict(identifiers)
    record["documents"] = [
        {
            **dict(row),
            "redistributable": bool(row["redistributable"]),
            "metadata": _decode(row["metadata_json"], {}),
        }
        for row in db.conn.execute(
            """
            SELECT document_id,kind,relative_path,media_type,language,source_url,
                   sha256,byte_size,license,redistributable,status,metadata_json
            FROM documents WHERE work_id=? ORDER BY kind,relative_path
            """,
            (work_id,),
        )
    ]
    degree = db.conn.execute(
        """
        SELECT
          (SELECT COUNT(DISTINCT citing_work_id) FROM citations WHERE cited_work_id=?) incoming,
          (SELECT COUNT(DISTINCT cited_work_id) FROM citations WHERE citing_work_id=?) outgoing
        """,
        (work_id, work_id),
    ).fetchone()
    record["graph"] = {
        "incoming_citations_in_database": int(degree["incoming"]),
        "outgoing_references_in_database": int(degree["outgoing"]),
    }
    return record


def citation_neighbors(
    db: LiteratureDB,
    identifier: str,
    *,
    direction: str = "both",
    limit: int = 100,
) -> dict[str, Any]:
    if direction not in {"incoming", "outgoing", "both"}:
        raise ValueError("direction must be incoming, outgoing, or both")
    work_id = resolve_work_id(db, identifier)
    remaining = max(1, min(int(limit), 1000))
    neighbors: list[dict[str, Any]] = []
    queries = []
    if direction in {"incoming", "both"}:
        queries.append(
            (
                "incoming",
                "SELECT citing_work_id neighbor_id,provider FROM citations "
                "WHERE cited_work_id=? ORDER BY citing_work_id,provider LIMIT ?",
            )
        )
    if direction in {"outgoing", "both"}:
        queries.append(
            (
                "outgoing",
                "SELECT cited_work_id neighbor_id,provider FROM citations "
                "WHERE citing_work_id=? ORDER BY cited_work_id,provider LIMIT ?",
            )
        )
    for relation, sql in queries:
        if remaining <= 0:
            break
        rows = db.conn.execute(sql, (work_id, remaining)).fetchall()
        neighbors.extend(
            {
                "direction": relation,
                "provider": row["provider"],
                "paper": _compact_work(db, int(row["neighbor_id"])),
            }
            for row in rows
        )
        remaining -= len(rows)
    return {
        "paper": _compact_work(db, work_id),
        "direction": direction,
        "count": len(neighbors),
        "neighbors": neighbors,
    }


def build_catalog(db: LiteratureDB, out_dir: str | Path) -> dict[str, Any]:
    """Write a full JSONL/CSV catalog and a readable seed-paper catalog."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    identifiers: dict[int, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    documents: dict[int, list[str]] = defaultdict(list)
    degree: dict[int, dict[str, int]] = defaultdict(lambda: {"in": 0, "out": 0})
    for row in db.conn.execute(
        "SELECT work_id,scheme,value FROM identifiers ORDER BY work_id,scheme,value"
    ):
        identifiers[int(row["work_id"])][row["scheme"]].append(row["value"])
    for row in db.conn.execute(
        "SELECT work_id,relative_path FROM documents ORDER BY work_id,relative_path"
    ):
        documents[int(row["work_id"])].append(row["relative_path"])
    for row in db.conn.execute(
        "SELECT citing_work_id,cited_work_id FROM citations "
        "GROUP BY citing_work_id,cited_work_id"
    ):
        degree[int(row["citing_work_id"])]["out"] += 1
        degree[int(row["cited_work_id"])]["in"] += 1

    records = []
    for row in db.conn.execute("SELECT work_id FROM works ORDER BY paper_uid"):
        work_id = int(row["work_id"])
        records.append(
            {
                **_compact_work(db, work_id),
                "identifiers": dict(identifiers[work_id]),
                "documents": documents[work_id],
                "graph": {
                    "incoming_citations_in_database": degree[work_id]["in"],
                    "outgoing_references_in_database": degree[work_id]["out"],
                },
            }
        )

    with (out / "papers.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    with (out / "papers.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        fields = [
            "paper_uid", "canonical_id", "display_title", "year",
            "metadata_status", "entity_kind", "is_seed", "doi", "arxiv",
            "openalex", "incoming", "outgoing", "documents",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            ids = record["identifiers"]
            writer.writerow(
                {
                    "paper_uid": record["paper_uid"],
                    "canonical_id": record["canonical_id"],
                    "display_title": record["display_title"],
                    "year": record["year"],
                    "metadata_status": record["metadata_status"],
                    "entity_kind": record["entity_kind"],
                    "is_seed": record["is_seed"],
                    "doi": ";".join(ids.get("doi", [])),
                    "arxiv": ";".join(ids.get("arxiv", [])),
                    "openalex": ";".join(ids.get("openalex", [])),
                    "incoming": record["graph"]["incoming_citations_in_database"],
                    "outgoing": record["graph"]["outgoing_references_in_database"],
                    "documents": ";".join(record["documents"]),
                }
            )

    seeds = sorted(
        (record for record in records if record["is_seed"]),
        key=lambda record: (
            record["year"] or 9999,
            record["display_title"].casefold(),
        ),
    )
    with (out / "seed-catalog.md").open(
        "w", encoding="utf-8", newline="\n"
    ) as handle:
        handle.write("# Seed literature catalog\n\n")
        handle.write(f"Generated: {utc_now()}\n\n")
        handle.write(
            "| paper_uid | Year | Title | Metadata | Documents |\n"
            "|---|---:|---|---|---:|\n"
        )
        for record in seeds:
            title = record["display_title"].replace("|", "\\|")
            handle.write(
                f"| {record['paper_uid']} | {record['year'] or ''} | {title} | "
                f"{record['metadata_status']} | {len(record['documents'])} |\n"
            )

    report = {
        "generated_at": utc_now(),
        "works": len(records),
        "seed_works": len(seeds),
        "missing_titles": sum(record["title_missing"] for record in records),
        "works_with_documents": sum(bool(record["documents"]) for record in records),
        "files": ["papers.jsonl", "papers.csv", "seed-catalog.md"],
    }
    (out / "catalog-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
