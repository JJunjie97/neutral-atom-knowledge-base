from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any

from .db import LiteratureDB, utc_now


def _json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


def _graph_rows(db: LiteratureDB) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    work_rows = db.conn.execute(
        """
        SELECT DISTINCT w.*
        FROM works w
        LEFT JOIN citations outgoing ON outgoing.citing_work_id=w.work_id
        LEFT JOIN citations incoming ON incoming.cited_work_id=w.work_id
        WHERE w.is_seed=1
           OR outgoing.citing_work_id IS NOT NULL
           OR incoming.cited_work_id IS NOT NULL
        ORDER BY w.year,w.canonical_id
        """
    ).fetchall()
    seed_info: dict[int, dict[str, Any]] = {}
    for row in db.conn.execute(
        "SELECT work_id,bib_key,cited_in_json FROM seed_entries ORDER BY bib_key"
    ):
        info = seed_info.setdefault(
            int(row["work_id"]), {"bib_keys": [], "cited_in": set()}
        )
        info["bib_keys"].append(row["bib_key"])
        info["cited_in"].update(_json(row["cited_in_json"], []))
    aliases: dict[int, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in db.conn.execute(
        "SELECT work_id,scheme,value FROM identifiers ORDER BY scheme,value"
    ):
        aliases[int(row["work_id"])][row["scheme"]].append(row["value"])

    raw_edges = db.conn.execute(
        """
        SELECT c.citing_work_id,c.cited_work_id,c.provider,
               a.canonical_id AS source,b.canonical_id AS target,
               a.is_seed AS source_seed,b.is_seed AS target_seed
        FROM citations c
        JOIN works a ON a.work_id=c.citing_work_id
        JOIN works b ON b.work_id=c.cited_work_id
        ORDER BY source,target,provider
        """
    ).fetchall()
    edge_groups: dict[tuple[int, int], dict[str, Any]] = {}
    degree: dict[int, dict[str, int]] = defaultdict(
        lambda: {"in": 0, "out": 0}
    )
    for row in raw_edges:
        key = (int(row["citing_work_id"]), int(row["cited_work_id"]))
        if key not in edge_groups:
            edge_groups[key] = {
                "source": row["source"],
                "target": row["target"],
                "type": "cites",
                "providers": [],
                "seed_to_seed": bool(row["source_seed"] and row["target_seed"]),
            }
            degree[key[0]]["out"] += 1
            degree[key[1]]["in"] += 1
        edge_groups[key]["providers"].append(row["provider"])

    nodes: list[dict[str, Any]] = []
    for row in work_rows:
        work_id = int(row["work_id"])
        seed = seed_info.get(work_id, {})
        nodes.append(
            {
                "id": row["canonical_id"],
                "paper_uid": row["paper_uid"],
                "title": row["title"],
                "title_source": row["title_source"],
                "metadata_status": row["metadata_status"],
                "entity_kind": row["entity_kind"],
                "year": row["year"],
                "publication_date": row["publication_date"],
                "authors": _json(row["authors_json"], []),
                "venue": row["venue"],
                "work_type": row["work_type"],
                "abstract": row["abstract"],
                "url": row["url"],
                "oa_url": row["oa_url"],
                "doi": row["doi"],
                "arxiv_id": row["arxiv_id"],
                "openalex_id": row["openalex_id"],
                "s2_id": row["s2_id"],
                "topics": _json(row["topics_json"], []),
                "citation_count": row["citation_count"],
                "reference_count": row["reference_count"],
                "is_seed": bool(row["is_seed"]),
                "bib_key": (seed.get("bib_keys") or [None])[0],
                "bib_keys": seed.get("bib_keys", []),
                "cited_in_sections": sorted(seed.get("cited_in", set())),
                "identifiers": dict(aliases[work_id]),
                "in_degree": degree[work_id]["in"],
                "out_degree": degree[work_id]["out"],
            }
        )
    return nodes, list(edge_groups.values())


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            cooked = {
                key: (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict))
                    else value
                )
                for key, value in row.items()
            }
            writer.writerow(cooked)


def _write_graphml(
    path: Path, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    namespace = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", namespace)
    root = ET.Element(f"{{{namespace}}}graphml")
    keys = [
        ("title", "node", "string"),
        ("year", "node", "int"),
        ("is_seed", "node", "boolean"),
        ("bib_key", "node", "string"),
        ("providers", "edge", "string"),
        ("seed_to_seed", "edge", "boolean"),
    ]
    for key_id, target, value_type in keys:
        ET.SubElement(
            root,
            f"{{{namespace}}}key",
            id=key_id,
            **{"for": target, "attr.name": key_id, "attr.type": value_type},
        )
    graph = ET.SubElement(
        root, f"{{{namespace}}}graph", id="literature", edgedefault="directed"
    )
    for node in nodes:
        element = ET.SubElement(graph, f"{{{namespace}}}node", id=node["id"])
        values = {
            "title": node.get("title") or "",
            "year": node.get("year") or 0,
            "is_seed": str(bool(node.get("is_seed"))).lower(),
            "bib_key": node.get("bib_key") or "",
        }
        for key, value in values.items():
            child = ET.SubElement(element, f"{{{namespace}}}data", key=key)
            child.text = str(value)
    for index, edge in enumerate(edges):
        element = ET.SubElement(
            graph,
            f"{{{namespace}}}edge",
            id=f"e{index}",
            source=edge["source"],
            target=edge["target"],
        )
        values = {
            "providers": ",".join(edge["providers"]),
            "seed_to_seed": str(bool(edge["seed_to_seed"])).lower(),
        }
        for key, value in values.items():
            child = ET.SubElement(element, f"{{{namespace}}}data", key=key)
            child.text = value
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def export_graph(db: LiteratureDB, out_dir: str | Path) -> dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    nodes, edges = _graph_rows(db)
    meta = {
        "generated_at": utc_now(),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "seed_node_count": sum(node["is_seed"] for node in nodes),
        "seed_to_seed_edge_count": sum(edge["seed_to_seed"] for edge in edges),
    }
    graph = {"meta": meta, "nodes": nodes, "edges": edges}
    (out / "graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    seed_ids = {node["id"] for node in nodes if node["is_seed"]}
    seed_graph = {
        "meta": {
            **meta,
            "scope": "seed-only",
            "node_count": len(seed_ids),
            "edge_count": sum(
                edge["source"] in seed_ids and edge["target"] in seed_ids
                for edge in edges
            ),
        },
        "nodes": [node for node in nodes if node["id"] in seed_ids],
        "edges": [
            edge
            for edge in edges
            if edge["source"] in seed_ids and edge["target"] in seed_ids
        ],
    }
    (out / "seed_graph.json").write_text(
        json.dumps(seed_graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(
        out / "nodes.csv",
        nodes,
        [
            "id",
            "title",
            "year",
            "publication_date",
            "authors",
            "venue",
            "work_type",
            "doi",
            "arxiv_id",
            "openalex_id",
            "url",
            "oa_url",
            "topics",
            "citation_count",
            "reference_count",
            "is_seed",
            "bib_key",
            "cited_in_sections",
            "in_degree",
            "out_degree",
        ],
    )
    _write_csv(
        out / "edges.csv",
        edges,
        ["source", "target", "type", "providers", "seed_to_seed"],
    )
    timeline = sorted(
        (
            {
                "year": node["year"],
                "id": node["id"],
                "bib_key": node["bib_key"],
                "title": node["title"],
                "authors": node["authors"],
                "venue": node["venue"],
                "cited_in_sections": node["cited_in_sections"],
            }
            for node in nodes
            if node["is_seed"]
        ),
        key=lambda item: (item["year"] or 9999, item["title"] or ""),
    )
    _write_csv(
        out / "timeline.csv",
        timeline,
        ["year", "id", "bib_key", "bib_keys", "title", "authors", "venue", "cited_in_sections"],
    )
    unresolved = [
        dict(row)
        for row in db.conn.execute(
            """
            SELECT s.bib_key,w.title,w.year,w.doi,w.arxiv_id,
                   m.status,m.score,m.method,m.provider_id,m.evidence_json
            FROM seed_entries s JOIN works w ON w.work_id=s.work_id
            LEFT JOIN matches m ON m.bib_key=s.bib_key AND m.provider='openalex'
            WHERE w.openalex_id IS NULL
            ORDER BY s.bib_key
            """
        )
    ]
    _write_csv(
        out / "unresolved_seeds.csv",
        unresolved,
        [
            "bib_key",
            "title",
            "year",
            "doi",
            "arxiv_id",
            "status",
            "score",
            "method",
            "provider_id",
            "evidence_json",
        ],
    )
    _write_graphml(out / "graph.graphml", nodes, edges)
    report = {"graph": meta, "database": db.stats(), "unresolved_seeds": len(unresolved)}
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
