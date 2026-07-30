from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .db import LiteratureDB


MANIFEST_NAME = "paper.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identifiers(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    values = manifest.get("identifiers") or {}
    return [
        (str(scheme), str(value))
        for scheme, raw in values.items()
        for value in (raw if isinstance(raw, list) else [raw])
        if value
    ]


def _document_id(paper_uid: str, kind: str, relative_path: str) -> str:
    source = f"{paper_uid}\0{kind}\0{relative_path}".encode("utf-8")
    return f"doc-{hashlib.sha256(source).hexdigest()[:20]}"


def sync_library(
    db: LiteratureDB,
    library_root: str | Path,
) -> dict[str, int]:
    root = Path(library_root).resolve()
    repo_root = root.parent
    manifests = sorted((root / "papers").glob(f"**/{MANIFEST_NAME}"))
    counts = {
        "manifests": len(manifests),
        "works": 0,
        "documents": 0,
        "available": 0,
        "planned": 0,
        "missing": 0,
    }
    with db.transaction():
        for manifest_path in manifests:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            identifiers = _identifiers(manifest)
            if not identifiers:
                raise ValueError(f"{manifest_path} has no identifiers")
            title = manifest.get("title")
            work_id = db.upsert_work(
                {
                    "title": title,
                    "title_source": "library_manifest" if title else None,
                    "metadata_status": "complete" if title else "incomplete",
                    "entity_kind": "scholarly_work",
                    "year": manifest.get("year"),
                },
                identifiers,
            )
            paper_uid = db.paper_uid(work_id)
            counts["works"] += 1
            paper_dir = manifest_path.parent.resolve()
            for entry in manifest.get("documents") or []:
                relative_to_paper = Path(str(entry["path"]))
                absolute = (paper_dir / relative_to_paper).resolve()
                if paper_dir not in absolute.parents and absolute != paper_dir:
                    raise ValueError(
                        f"document path escapes paper directory: {manifest_path}"
                    )
                repo_relative = absolute.relative_to(repo_root).as_posix()
                exists = absolute.is_file()
                planned = bool(entry.get("planned"))
                status = "available" if exists else ("planned" if planned else "missing")
                db.upsert_document(
                    {
                        "document_id": entry.get("document_id")
                        or _document_id(
                            paper_uid,
                            str(entry.get("kind") or "other"),
                            repo_relative,
                        ),
                        "work_id": work_id,
                        "kind": entry.get("kind") or "other",
                        "relative_path": repo_relative,
                        "media_type": entry.get("media_type"),
                        "language": entry.get("language") or manifest.get("language"),
                        "source_url": entry.get("source_url"),
                        "sha256": _sha256(absolute) if exists else None,
                        "byte_size": absolute.stat().st_size if exists else None,
                        "license": entry.get("license"),
                        "redistributable": bool(entry.get("redistributable")),
                        "status": status,
                        "metadata_json": entry,
                    }
                )
                counts["documents"] += 1
                counts[status] += 1
    return counts


def split_markdown(text: str, *, max_chars: int = 3500) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        content = "\n\n".join(part.strip() for part in buffer if part.strip()).strip()
        while len(content) > max_chars:
            boundary = content.rfind("\n\n", 0, max_chars)
            if boundary < max_chars // 2:
                boundary = max_chars
            chunks.append({"heading": heading, "content": content[:boundary].strip()})
            content = content[boundary:].strip()
        if content:
            chunks.append({"heading": heading, "content": content})
        buffer = []

    for block in re.split(r"\n\s*\n", text):
        stripped = block.strip()
        if not stripped:
            continue
        match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if match:
            flush()
            heading = match.group(2).strip()
            continue
        projected = sum(len(item) for item in buffer) + len(stripped)
        if buffer and projected > max_chars:
            flush()
        buffer.append(stripped)
    flush()
    return chunks


def index_markdown(
    db: LiteratureDB,
    library_root: str | Path,
) -> dict[str, int]:
    repo_root = Path(library_root).resolve().parent
    rows = db.conn.execute(
        """
        SELECT document_id,relative_path
        FROM documents
        WHERE kind='markdown' AND status='available'
        ORDER BY relative_path
        """
    ).fetchall()
    counts = {"documents": len(rows), "chunks": 0, "missing": 0}
    with db.transaction():
        for row in rows:
            path = (repo_root / row["relative_path"]).resolve()
            if repo_root not in path.parents or not path.is_file():
                counts["missing"] += 1
                continue
            chunks = split_markdown(path.read_text(encoding="utf-8"))
            db.replace_document_chunks(row["document_id"], chunks)
            counts["chunks"] += len(chunks)
    return counts


def search_library(
    db: LiteratureDB,
    query: str,
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    return [dict(row) for row in db.search_document_chunks(query, limit=limit)]
