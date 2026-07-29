from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np


SECTION_META = {
    "section_introduction.tex": {
        "label": "基础与综述",
        "short": "基础",
        "color": "#AEB8FF",
    },
    "section_atomhardware.tex": {
        "label": "原子与硬件",
        "short": "硬件",
        "color": "#5AD6C3",
    },
    "section_compilation.tex": {
        "label": "编译与控制",
        "short": "编译",
        "color": "#F5A65B",
    },
    "section_QEC.tex": {
        "label": "量子纠错",
        "short": "纠错",
        "color": "#FF718B",
    },
    "section_advantage.tex": {
        "label": "量子优势",
        "short": "优势",
        "color": "#C69BFF",
    },
    "section_networking.tex": {
        "label": "网络与通信",
        "short": "网络",
        "color": "#55A8FF",
    },
    "section_photonics.tex": {
        "label": "光子与集成",
        "short": "光子",
        "color": "#F3CF63",
    },
    "other": {
        "label": "其他 / 未分类",
        "short": "其他",
        "color": "#7F8DA8",
    },
}


def stable_fraction(value: str, salt: str = "") -> float:
    digest = hashlib.blake2b(
        f"{salt}:{value}".encode("utf-8"), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") / (2**64 - 1)


def spring_layout(
    node_ids: list[str],
    edges: list[dict[str, Any]],
    *,
    iterations: int = 110,
    seed: int = 42,
) -> dict[str, tuple[float, float]]:
    n = len(node_ids)
    if not n:
        return {}

    index = {node_id: idx for idx, node_id in enumerate(node_ids)}
    edge_pairs = [
        (index[edge["source"]], index[edge["target"]])
        for edge in edges
        if edge["source"] in index
        and edge["target"] in index
        and edge["source"] != edge["target"]
    ]
    rng = np.random.default_rng(seed)
    positions = rng.normal(0.0, 0.34, size=(n, 2))

    if edge_pairs:
        sources = np.fromiter((pair[0] for pair in edge_pairs), dtype=np.int32)
        targets = np.fromiter((pair[1] for pair in edge_pairs), dtype=np.int32)
    else:
        sources = np.array([], dtype=np.int32)
        targets = np.array([], dtype=np.int32)

    k = math.sqrt(3.2 / max(n, 1))
    temperature = 0.15

    for _ in range(iterations):
        delta = positions[:, None, :] - positions[None, :, :]
        distance_sq = np.sum(delta * delta, axis=2)
        np.fill_diagonal(distance_sq, np.inf)
        repulsion = np.sum(
            delta / distance_sq[:, :, None] * (k * k), axis=1
        )

        displacement = repulsion
        if len(sources):
            edge_delta = positions[sources] - positions[targets]
            edge_distance = np.sqrt(
                np.sum(edge_delta * edge_delta, axis=1)
            ).clip(min=1e-5)
            attraction = edge_delta * (edge_distance / k)[:, None]
            np.add.at(displacement, sources, -attraction)
            np.add.at(displacement, targets, attraction)

        displacement -= positions * 0.085
        lengths = np.linalg.norm(displacement, axis=1).clip(min=1e-9)
        steps = displacement / lengths[:, None]
        steps *= np.minimum(lengths, temperature)[:, None]
        positions += steps
        positions -= positions.mean(axis=0)
        temperature *= 0.969

    radius = np.linalg.norm(positions, axis=1)
    scale = float(np.quantile(radius, 0.96)) or 1.0
    positions /= scale
    return {
        node_id: (round(float(positions[idx, 0]), 6), round(float(positions[idx, 1]), 6))
        for idx, node_id in enumerate(node_ids)
    }


def section_for_node(
    node: dict[str, Any],
    inherited: Counter[str] | None = None,
) -> str:
    sections = node.get("cited_in_sections") or []
    if sections:
        return sections[0]
    if inherited:
        return inherited.most_common(1)[0][0]
    return "other"


def compact_node(
    node: dict[str, Any],
    position: tuple[float, float],
    *,
    group: str,
) -> dict[str, Any]:
    topics = []
    for topic in node.get("topics") or []:
        if isinstance(topic, dict) and topic.get("name"):
            topics.append(topic["name"])
        elif isinstance(topic, str):
            topics.append(topic)

    return {
        "id": node["id"],
        "title": node.get("title") or "未命名文献",
        "year": node.get("year"),
        "date": node.get("publication_date"),
        "authors": node.get("authors") or [],
        "venue": node.get("venue"),
        "type": node.get("work_type"),
        "url": node.get("url"),
        "oaUrl": node.get("oa_url"),
        "doi": node.get("doi"),
        "arxiv": node.get("arxiv_id"),
        "openalex": node.get("openalex_id"),
        "topics": topics[:4],
        "citations": node.get("citation_count"),
        "references": node.get("reference_count"),
        "seed": bool(node.get("is_seed")),
        "bibKey": node.get("bib_key"),
        "bibKeys": node.get("bib_keys") or [],
        "sections": node.get("cited_in_sections") or [],
        "group": group if group in SECTION_META else "other",
        "in": int(node.get("in_degree") or 0),
        "out": int(node.get("out_degree") or 0),
        "x": position[0],
        "y": position[1],
    }


def compact_graph(
    graph: dict[str, Any],
    positions: dict[str, tuple[float, float]],
    inherited_groups: dict[str, Counter[str]] | None = None,
) -> dict[str, Any]:
    nodes = graph["nodes"]
    node_index = {node["id"]: idx for idx, node in enumerate(nodes)}
    compact_nodes = []
    for node in nodes:
        group = section_for_node(
            node,
            inherited_groups.get(node["id"]) if inherited_groups else None,
        )
        compact_nodes.append(
            compact_node(node, positions[node["id"]], group=group)
        )

    compact_edges = [
        [node_index[edge["source"]], node_index[edge["target"]]]
        for edge in graph["edges"]
        if edge["source"] in node_index and edge["target"] in node_index
    ]
    years = [node["year"] for node in nodes if node.get("year")]
    year_counts = Counter(years)
    section_counts = Counter(node["group"] for node in compact_nodes)

    return {
        "meta": {
            **(graph.get("meta") or {}),
            "nodeCount": len(compact_nodes),
            "edgeCount": len(compact_edges),
            "seedCount": sum(1 for node in compact_nodes if node["seed"]),
            "yearMin": min(years) if years else None,
            "yearMax": max(years) if years else None,
            "unknownYear": sum(1 for node in nodes if not node.get("year")),
            "yearCounts": sorted(
                ([int(year), count] for year, count in year_counts.items()),
                key=lambda item: item[0],
            ),
            "sectionCounts": dict(section_counts),
            "layout": "offline-force-v1",
        },
        "sections": [
            {"id": section_id, **meta}
            for section_id, meta in SECTION_META.items()
        ],
        "nodes": compact_nodes,
        "edges": compact_edges,
    }


def full_layout(
    full_graph: dict[str, Any],
    seed_graph: dict[str, Any],
    seed_positions: dict[str, tuple[float, float]],
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, Counter[str]],
]:
    seed_nodes = {
        node["id"]: node for node in seed_graph["nodes"]
    }
    attached_seeds: dict[str, set[str]] = defaultdict(set)
    for edge in full_graph["edges"]:
        source = edge["source"]
        target = edge["target"]
        if source in seed_nodes and target not in seed_nodes:
            attached_seeds[target].add(source)
        if target in seed_nodes and source not in seed_nodes:
            attached_seeds[source].add(target)

    inherited_groups: dict[str, Counter[str]] = {}
    positions = dict(seed_positions)
    cluster_cursor: Counter[str] = Counter()

    for node in sorted(full_graph["nodes"], key=lambda item: item["id"]):
        node_id = node["id"]
        if node_id in positions:
            continue

        anchors = sorted(attached_seeds.get(node_id, set()))
        inherited = Counter()
        for anchor_id in anchors:
            for section in seed_nodes[anchor_id].get("cited_in_sections") or []:
                inherited[section] += 1
        if inherited:
            inherited_groups[node_id] = inherited

        if anchors:
            anchor_positions = np.array(
                [seed_positions[anchor_id] for anchor_id in anchors]
            )
            center = anchor_positions.mean(axis=0)
            primary_anchor = anchors[0]
            cursor = cluster_cursor[primary_anchor]
            cluster_cursor[primary_anchor] += 1
            angle = cursor * 2.399963229728653 + stable_fraction(node_id) * 0.9
            shared_factor = 0.48 if len(anchors) > 1 else 1.0
            radius = (0.022 + 0.0095 * math.sqrt(cursor + 1)) * shared_factor
            positions[node_id] = (
                round(float(center[0] + math.cos(angle) * radius), 6),
                round(float(center[1] + math.sin(angle) * radius), 6),
            )
        else:
            angle = stable_fraction(node_id, "angle") * math.tau
            radius = 1.22 + stable_fraction(node_id, "radius") * 0.24
            positions[node_id] = (
                round(math.cos(angle) * radius, 6),
                round(math.sin(angle) * radius, 6),
            )

    return positions, inherited_groups


def parse_args() -> argparse.Namespace:
    project_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Prepare compact, pre-laid-out literature graph data."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=project_root / "output",
        help="Directory containing graph.json and seed_graph.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "public" / "data",
        help="Destination for browser-ready graph data.",
    )
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    seed_graph = json.loads(
        (args.source / "seed_graph.json").read_text(encoding="utf-8")
    )
    full_graph = json.loads(
        (args.source / "graph.json").read_text(encoding="utf-8")
    )

    seed_ids = [node["id"] for node in seed_graph["nodes"]]
    seed_positions = spring_layout(seed_ids, seed_graph["edges"])
    core_payload = compact_graph(seed_graph, seed_positions)
    full_positions, inherited_groups = full_layout(
        full_graph, seed_graph, seed_positions
    )
    full_payload = compact_graph(
        full_graph, full_positions, inherited_groups
    )

    write_json(args.output / "core-graph.json", core_payload)
    write_json(args.output / "full-graph.json", full_payload)
    print(
        json.dumps(
            {
                "core": {
                    "nodes": core_payload["meta"]["nodeCount"],
                    "edges": core_payload["meta"]["edgeCount"],
                },
                "full": {
                    "nodes": full_payload["meta"]["nodeCount"],
                    "edges": full_payload["meta"]["edgeCount"],
                },
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
