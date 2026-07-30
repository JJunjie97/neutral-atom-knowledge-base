from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .crossref import CrossrefClient, repair_missing_doi_metadata
from .db import LiteratureDB
from .export import export_graph
from .knowledge import build_catalog, citation_neighbors, get_work
from .library import index_markdown, search_library, sync_library
from .openalex import OpenAlexClient
from .pipeline import (
    crawl_openalex,
    fetch_openalex_abstracts,
    ingest,
    repair_openalex_doi_titles,
)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _load_local_env(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _add_db(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        default="data/database/literature.sqlite",
        help="SQLite database path (default: data/database/literature.sqlite)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neutral-atom-graph",
        description="Build a reproducible citation graph from bibliography.bib.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser("ingest", help="Parse BibTeX and TeX citations.")
    _add_db(ingest_parser)
    ingest_parser.add_argument(
        "--bib",
        default="library/papers/arxiv/2607/2607.21554/source/bibliography.bib",
    )
    ingest_parser.add_argument(
        "--tex-dir",
        default="library/papers/arxiv/2607/2607.21554/source",
    )

    crawl = sub.add_parser(
        "crawl-openalex", help="Resolve seeds and collect their reference lists."
    )
    _add_db(crawl)
    crawl.add_argument("--limit-seeds", type=int)
    crawl.add_argument("--limit-reference-records", type=int)
    crawl.add_argument("--no-title-search", action="store_true")
    crawl.add_argument("--refresh", action="store_true")
    crawl.add_argument("--request-delay", type=float, default=0.12)
    crawl.add_argument("--api-key", help="Prefer OPENALEX_API_KEY instead.")
    crawl.add_argument("--email", help="Prefer LITGRAPH_EMAIL instead.")

    abstracts = sub.add_parser(
        "fetch-openalex-abstracts",
        help="Backfill English abstracts for OpenAlex-resolved works.",
    )
    _add_db(abstracts)
    abstracts.add_argument("--limit-records", type=int)
    abstracts.add_argument("--refresh", action="store_true")
    abstracts.add_argument("--request-delay", type=float, default=0.12)
    abstracts.add_argument("--api-key", help="Prefer OPENALEX_API_KEY instead.")
    abstracts.add_argument("--email", help="Prefer LITGRAPH_EMAIL instead.")

    repair = sub.add_parser(
        "repair-metadata",
        help="Recover missing titles from exact DOI matches and Crossref.",
    )
    _add_db(repair)
    repair.add_argument("--limit-records", type=int)
    repair.add_argument("--refresh", action="store_true")
    repair.add_argument("--request-delay", type=float, default=0.15)
    repair.add_argument("--api-key", help="Prefer OPENALEX_API_KEY instead.")
    repair.add_argument("--email", help="Prefer LITGRAPH_EMAIL instead.")

    sync = sub.add_parser(
        "sync-library", help="Register paper.json manifests and local files."
    )
    _add_db(sync)
    sync.add_argument("--library", default="library")

    index = sub.add_parser(
        "index-markdown", help="Build the local SQLite FTS5 Markdown index."
    )
    _add_db(index)
    index.add_argument("--library", default="library")

    search = sub.add_parser(
        "search-library", help="Search indexed Markdown chunks."
    )
    _add_db(search)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)

    catalog = sub.add_parser(
        "build-catalog",
        help="Build JSONL, CSV and Markdown master catalogs for AI tools.",
    )
    _add_db(catalog)
    catalog.add_argument("--out", default="data/catalog")

    get_paper = sub.add_parser(
        "get-work", help="Return one paper and its local document records."
    )
    _add_db(get_paper)
    get_paper.add_argument("identifier", help="paper_uid, DOI, arXiv or OpenAlex ID")

    neighbors = sub.add_parser(
        "neighbors", help="Return one-hop incoming/outgoing citation neighbors."
    )
    _add_db(neighbors)
    neighbors.add_argument("identifier", help="paper_uid, DOI, arXiv or OpenAlex ID")
    neighbors.add_argument(
        "--direction", choices=("incoming", "outgoing", "both"), default="both"
    )
    neighbors.add_argument("--limit", type=int, default=100)

    export_parser = sub.add_parser("export", help="Export JSON, CSV and GraphML.")
    _add_db(export_parser)
    export_parser.add_argument("--out", default="data/exports")

    stats = sub.add_parser("stats", help="Show database coverage.")
    _add_db(stats)

    all_parser = sub.add_parser("all", help="Ingest, crawl and export.")
    _add_db(all_parser)
    all_parser.add_argument(
        "--bib",
        default="library/papers/arxiv/2607/2607.21554/source/bibliography.bib",
    )
    all_parser.add_argument(
        "--tex-dir",
        default="library/papers/arxiv/2607/2607.21554/source",
    )
    all_parser.add_argument("--out", default="data/exports")
    all_parser.add_argument("--limit-seeds", type=int)
    all_parser.add_argument("--limit-reference-records", type=int)
    all_parser.add_argument("--no-title-search", action="store_true")
    all_parser.add_argument("--refresh", action="store_true")
    all_parser.add_argument("--request-delay", type=float, default=0.12)
    all_parser.add_argument("--api-key")
    all_parser.add_argument("--email")
    return parser


def _client(args: argparse.Namespace, db: LiteratureDB) -> OpenAlexClient:
    api_key = args.api_key or os.getenv("OPENALEX_API_KEY")
    limit = getattr(args, "limit_seeds", None)
    if args.command in {"fetch-openalex-abstracts", "repair-metadata"}:
        limit = args.limit_records
    if not api_key and limit is None:
        print(
            "Warning: full OpenAlex crawling without OPENALEX_API_KEY has a much "
            "smaller daily allowance. A free key is strongly recommended."
        )
    return OpenAlexClient(
        db,
        api_key=api_key,
        email=args.email or os.getenv("LITGRAPH_EMAIL"),
        request_delay=args.request_delay,
        refresh=args.refresh,
    )


def main(argv: list[str] | None = None) -> None:
    _load_local_env()
    args = build_parser().parse_args(argv)
    db_path = Path(args.db)
    with LiteratureDB(db_path) as db:
        if args.command == "ingest":
            _print(ingest(db, args.bib, args.tex_dir))
        elif args.command == "crawl-openalex":
            _print(
                crawl_openalex(
                    db,
                    _client(args, db),
                    limit_seeds=args.limit_seeds,
                    limit_reference_records=args.limit_reference_records,
                    title_search=not args.no_title_search,
                )
            )
        elif args.command == "fetch-openalex-abstracts":
            _print(
                fetch_openalex_abstracts(
                    db,
                    _client(args, db),
                    limit=args.limit_records,
                )
            )
        elif args.command == "repair-metadata":
            openalex_result = repair_openalex_doi_titles(
                db,
                _client(args, db),
                limit=args.limit_records,
            )
            crossref_result = repair_missing_doi_metadata(
                db,
                CrossrefClient(
                    db,
                    email=args.email or os.getenv("LITGRAPH_EMAIL"),
                    request_delay=args.request_delay,
                    refresh=args.refresh,
                ),
                limit=args.limit_records,
            )
            _print(
                {
                    "openalex_exact_doi": openalex_result,
                    "crossref": crossref_result,
                    "database": db.stats(),
                }
            )
        elif args.command == "sync-library":
            _print(sync_library(db, args.library))
        elif args.command == "index-markdown":
            _print(
                {
                    "sync": sync_library(db, args.library),
                    "index": index_markdown(db, args.library),
                }
            )
        elif args.command == "search-library":
            _print(search_library(db, args.query, limit=args.limit))
        elif args.command == "build-catalog":
            _print(build_catalog(db, args.out))
        elif args.command == "get-work":
            _print(get_work(db, args.identifier))
        elif args.command == "neighbors":
            _print(
                citation_neighbors(
                    db,
                    args.identifier,
                    direction=args.direction,
                    limit=args.limit,
                )
            )
        elif args.command == "export":
            _print(export_graph(db, args.out))
        elif args.command == "stats":
            _print(db.stats())
        elif args.command == "all":
            result = {
                "ingest": ingest(db, args.bib, args.tex_dir),
                "crawl": crawl_openalex(
                    db,
                    _client(args, db),
                    limit_seeds=args.limit_seeds,
                    limit_reference_records=args.limit_reference_records,
                    title_search=not args.no_title_search,
                ),
                "export": export_graph(db, args.out),
            }
            _print(result)
