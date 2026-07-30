from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .bibtex import (
    BibEntry,
    clean_latex_text,
    extract_arxiv_id,
    extract_doi,
    iter_author_names,
    normalize_arxiv_id,
    normalize_doi,
    normalize_title,
    parse_year,
)


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS works (
    work_id INTEGER PRIMARY KEY,
    paper_uid TEXT UNIQUE,
    canonical_id TEXT NOT NULL UNIQUE,
    title TEXT,
    title_normalized TEXT,
    title_source TEXT,
    metadata_status TEXT NOT NULL DEFAULT 'incomplete',
    entity_kind TEXT NOT NULL DEFAULT 'scholarly_work',
    year INTEGER,
    publication_date TEXT,
    venue TEXT,
    work_type TEXT,
    abstract TEXT,
    url TEXT,
    oa_url TEXT,
    doi TEXT,
    arxiv_id TEXT,
    openalex_id TEXT,
    s2_id TEXT,
    authors_json TEXT NOT NULL DEFAULT '[]',
    topics_json TEXT NOT NULL DEFAULT '[]',
    citation_count INTEGER,
    reference_count INTEGER,
    is_seed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS identifiers (
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    PRIMARY KEY (scheme, value)
);
CREATE INDEX IF NOT EXISTS idx_identifiers_work ON identifiers(work_id);

CREATE TABLE IF NOT EXISTS seed_entries (
    bib_key TEXT PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    cited_in_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_seed_entries_work ON seed_entries(work_id);

CREATE TABLE IF NOT EXISTS citations (
    citing_work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    cited_work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    PRIMARY KEY (citing_work_id, cited_work_id, provider)
);
CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_work_id);

CREATE TABLE IF NOT EXISTS provider_records (
    provider TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (provider, provider_id)
);

CREATE TABLE IF NOT EXISTS fetch_status (
    provider TEXT NOT NULL,
    work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (provider, work_id, operation)
);

CREATE TABLE IF NOT EXISTS matches (
    bib_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_id TEXT,
    method TEXT NOT NULL,
    score REAL,
    status TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (bib_key, provider)
);

CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    body TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    media_type TEXT,
    language TEXT,
    source_url TEXT,
    sha256 TEXT,
    byte_size INTEGER,
    license TEXT,
    redistributable INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'available',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_work ON documents(work_id);
CREATE INDEX IF NOT EXISTS idx_documents_kind_status ON documents(kind,status);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    heading TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(document_id,chunk_index)
);

CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    document_id UNINDEXED,
    heading,
    content,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS metadata_candidates (
    candidate_id INTEGER PRIMARY KEY,
    work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT,
    confidence REAL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metadata_candidates_work
    ON metadata_candidates(work_id,status);

CREATE TABLE IF NOT EXISTS taxonomy_definitions (
    taxonomy_version TEXT PRIMARY KEY,
    taxonomy_digest TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_mentions (
    mention_id TEXT PRIMARY KEY,
    review_id TEXT NOT NULL,
    work_id INTEGER REFERENCES works(work_id) ON DELETE SET NULL,
    bib_key TEXT NOT NULL,
    source_file TEXT NOT NULL,
    section_path_json TEXT NOT NULL DEFAULT '[]',
    context_text TEXT NOT NULL,
    citation_command TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(review_id,source_file,char_start,bib_key)
);
CREATE INDEX IF NOT EXISTS idx_review_mentions_work
    ON review_mentions(work_id);
CREATE INDEX IF NOT EXISTS idx_review_mentions_review
    ON review_mentions(review_id,bib_key);

CREATE TABLE IF NOT EXISTS work_classifications (
    work_id INTEGER NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
    taxonomy_version TEXT NOT NULL,
    taxonomy_digest TEXT NOT NULL,
    dimension_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    method TEXT NOT NULL,
    confidence REAL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (
      work_id,taxonomy_version,dimension_id,category_id,method
    )
);
CREATE INDEX IF NOT EXISTS idx_work_classifications_facet
    ON work_classifications(taxonomy_version,dimension_id,category_id);
CREATE INDEX IF NOT EXISTS idx_work_classifications_work
    ON work_classifications(work_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normal_identifier(scheme: str, value: str) -> tuple[str, str]:
    scheme = scheme.lower().strip()
    value = value.strip()
    if scheme == "doi":
        value = normalize_doi(value) or value.lower()
    elif scheme == "arxiv":
        value = normalize_arxiv_id(value) or value.lower()
    elif scheme == "openalex":
        value = value.rsplit("/", 1)[-1].upper()
    elif scheme == "s2":
        value = value.lower()
    return scheme, value


def _best_canonical(identifiers: Iterable[tuple[str, str]]) -> str:
    priority = {"doi": 0, "arxiv": 1, "openalex": 2, "s2": 3, "bib": 4}
    values = [_normal_identifier(s, v) for s, v in identifiers if v]
    if not values:
        raise ValueError("at least one identifier is required")
    scheme, value = min(values, key=lambda item: (priority.get(item[0], 99), item))
    return f"{scheme}:{value}"


class LiteratureDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(works)")
        }
        additions = {
            "paper_uid": "TEXT",
            "title_source": "TEXT",
            "metadata_status": "TEXT NOT NULL DEFAULT 'incomplete'",
            "entity_kind": "TEXT NOT NULL DEFAULT 'scholarly_work'",
        }
        for column, declaration in additions.items():
            if column not in columns:
                self.conn.execute(
                    f"ALTER TABLE works ADD COLUMN {column} {declaration}"
                )
        self.conn.execute(
            """
            UPDATE works
            SET paper_uid=printf('paper-%08d',work_id)
            WHERE paper_uid IS NULL OR paper_uid=''
            """
        )
        self.conn.execute(
            """
            UPDATE works
            SET metadata_status=CASE
                WHEN title IS NOT NULL AND trim(title)<>'' THEN 'complete'
                WHEN openalex_id IS NOT NULL THEN 'unresolved_reference'
                ELSE 'incomplete'
            END
            WHERE metadata_status IS NULL
               OR metadata_status=''
               OR metadata_status='incomplete'
            """
        )
        self.conn.execute(
            "UPDATE works SET title_source='legacy' "
            "WHERE title IS NOT NULL AND trim(title)<>'' AND title_source IS NULL"
        )
        for row in self.conn.execute(
            "SELECT work_id,raw_json FROM seed_entries"
        ).fetchall():
            fields = json.loads(row["raw_json"] or "{}")
            note = str(fields.get("note") or "").casefold()
            if "private communication" in note:
                self.conn.execute(
                    """
                    UPDATE works
                    SET entity_kind='private_communication',
                        metadata_status='non_bibliographic'
                    WHERE work_id=?
                    """,
                    (int(row["work_id"]),),
                )
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_works_paper_uid "
            "ON works(paper_uid)"
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "LiteratureDB":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            self.conn.execute("BEGIN")
            yield
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _candidate_ids(
        self, identifiers: Iterable[tuple[str, str]], preferred_work_id: int | None
    ) -> list[int]:
        candidates = {preferred_work_id} if preferred_work_id else set()
        for scheme, value in identifiers:
            scheme, value = _normal_identifier(scheme, value)
            row = self.conn.execute(
                "SELECT work_id FROM identifiers WHERE scheme=? AND value=?",
                (scheme, value),
            ).fetchone()
            if row:
                candidates.add(int(row["work_id"]))
        return sorted(
            candidates,
            key=lambda work_id: (
                -int(
                    self.conn.execute(
                        "SELECT is_seed FROM works WHERE work_id=?", (work_id,)
                    ).fetchone()["is_seed"]
                ),
                work_id,
            ),
        )

    def _merge_works(self, keep_id: int, remove_id: int) -> int:
        if keep_id == remove_id:
            return keep_id
        keep = self.conn.execute(
            "SELECT * FROM works WHERE work_id=?", (keep_id,)
        ).fetchone()
        remove = self.conn.execute(
            "SELECT * FROM works WHERE work_id=?", (remove_id,)
        ).fetchone()
        if not keep or not remove:
            return keep_id

        edges = self.conn.execute(
            """
            SELECT citing_work_id, cited_work_id, provider, discovered_at
            FROM citations
            WHERE citing_work_id=? OR cited_work_id=?
            """,
            (remove_id, remove_id),
        ).fetchall()
        self.conn.execute(
            "DELETE FROM citations WHERE citing_work_id=? OR cited_work_id=?",
            (remove_id, remove_id),
        )
        for edge in edges:
            citing = keep_id if edge["citing_work_id"] == remove_id else edge["citing_work_id"]
            cited = keep_id if edge["cited_work_id"] == remove_id else edge["cited_work_id"]
            if citing != cited:
                self.conn.execute(
                    "INSERT OR IGNORE INTO citations VALUES (?, ?, ?, ?)",
                    (citing, cited, edge["provider"], edge["discovered_at"]),
                )

        aliases = self.conn.execute(
            "SELECT scheme, value FROM identifiers WHERE work_id=?", (remove_id,)
        ).fetchall()
        self.conn.execute("DELETE FROM identifiers WHERE work_id=?", (remove_id,))
        for alias in aliases:
            self.conn.execute(
                "INSERT OR IGNORE INTO identifiers(scheme,value,work_id) VALUES(?,?,?)",
                (alias["scheme"], alias["value"], keep_id),
            )
        self.conn.execute(
            "UPDATE seed_entries SET work_id=? WHERE work_id=?", (keep_id, remove_id)
        )
        self.conn.execute(
            "UPDATE documents SET work_id=? WHERE work_id=?", (keep_id, remove_id)
        )
        self.conn.execute(
            "UPDATE review_mentions SET work_id=? WHERE work_id=?",
            (keep_id, remove_id),
        )
        self.conn.execute(
            """
            INSERT OR IGNORE INTO work_classifications(
              work_id,taxonomy_version,taxonomy_digest,dimension_id,
              category_id,method,confidence,evidence_json,created_at,updated_at
            )
            SELECT ?,taxonomy_version,taxonomy_digest,dimension_id,
                   category_id,method,confidence,evidence_json,created_at,updated_at
            FROM work_classifications WHERE work_id=?
            """,
            (keep_id, remove_id),
        )
        self.conn.execute(
            "DELETE FROM work_classifications WHERE work_id=?", (remove_id,)
        )
        statuses = self.conn.execute(
            "SELECT * FROM fetch_status WHERE work_id=?", (remove_id,)
        ).fetchall()
        self.conn.execute("DELETE FROM fetch_status WHERE work_id=?", (remove_id,))
        for status in statuses:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO fetch_status
                (provider,work_id,operation,status,attempts,last_error,updated_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    status["provider"],
                    keep_id,
                    status["operation"],
                    status["status"],
                    status["attempts"],
                    status["last_error"],
                    status["updated_at"],
                ),
            )

        merge_columns = [
            "title",
            "title_normalized",
            "title_source",
            "metadata_status",
            "entity_kind",
            "year",
            "publication_date",
            "venue",
            "work_type",
            "abstract",
            "url",
            "oa_url",
            "doi",
            "arxiv_id",
            "openalex_id",
            "s2_id",
            "citation_count",
            "reference_count",
        ]
        updates = {
            column: keep[column] if keep[column] is not None else remove[column]
            for column in merge_columns
        }
        for json_column in ("authors_json", "topics_json"):
            keep_value = json.loads(keep[json_column] or "[]")
            remove_value = json.loads(remove[json_column] or "[]")
            updates[json_column] = json.dumps(
                keep_value or remove_value, ensure_ascii=False
            )
        updates["is_seed"] = int(bool(keep["is_seed"] or remove["is_seed"]))
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{column}=?" for column in updates)
        self.conn.execute(
            f"UPDATE works SET {assignments} WHERE work_id=?",
            (*updates.values(), keep_id),
        )
        self.conn.execute("DELETE FROM works WHERE work_id=?", (remove_id,))
        return keep_id

    def upsert_work(
        self,
        data: dict[str, Any],
        identifiers: Iterable[tuple[str, str]],
        *,
        is_seed: bool = False,
        preferred_work_id: int | None = None,
    ) -> int:
        identifiers = list(
            dict.fromkeys(_normal_identifier(s, v) for s, v in identifiers if v)
        )
        if not identifiers:
            raise ValueError("work needs at least one identifier")
        candidates = self._candidate_ids(identifiers, preferred_work_id)
        now = utc_now()
        if candidates:
            work_id = candidates[0]
            for remove_id in candidates[1:]:
                work_id = self._merge_works(work_id, remove_id)
        else:
            canonical = _best_canonical(identifiers)
            cursor = self.conn.execute(
                """
                INSERT INTO works(canonical_id,created_at,updated_at,is_seed)
                VALUES(?,?,?,?)
                """,
                (canonical, now, now, int(is_seed)),
            )
            work_id = int(cursor.lastrowid)
            self.conn.execute(
                "UPDATE works SET paper_uid=? WHERE work_id=?",
                (f"paper-{work_id:08d}", work_id),
            )

        row = self.conn.execute(
            "SELECT * FROM works WHERE work_id=?", (work_id,)
        ).fetchone()
        scalar_columns = [
            "title",
            "title_source",
            "metadata_status",
            "entity_kind",
            "year",
            "publication_date",
            "venue",
            "work_type",
            "abstract",
            "url",
            "oa_url",
            "doi",
            "arxiv_id",
            "openalex_id",
            "s2_id",
            "citation_count",
            "reference_count",
        ]
        updates: dict[str, Any] = {}
        metadata_status_rank = {
            None: -1,
            "": -1,
            "incomplete": 0,
            "unresolved_reference": 1,
            "no_title": 1,
            "complete": 2,
            "non_bibliographic": 3,
        }
        entity_kind_rank = {
            None: -1,
            "": -1,
            "scholarly_work": 0,
            "private_communication": 1,
        }
        for column in scalar_columns:
            incoming = data.get(column)
            current = row[column]
            if column == "metadata_status":
                updates[column] = (
                    incoming
                    if metadata_status_rank.get(incoming, 1)
                    > metadata_status_rank.get(current, 1)
                    else current
                )
            elif column == "entity_kind":
                updates[column] = (
                    incoming
                    if entity_kind_rank.get(incoming, 1)
                    > entity_kind_rank.get(current, 1)
                    else current
                )
            else:
                updates[column] = current if current not in (None, "") else incoming
        title = updates["title"]
        updates["title_normalized"] = normalize_title(title) if title else row["title_normalized"]
        for json_column in ("authors_json", "topics_json"):
            incoming = data.get(json_column)
            if incoming is not None and not isinstance(incoming, str):
                incoming = json.dumps(incoming, ensure_ascii=False)
            updates[json_column] = (
                row[json_column]
                if row[json_column] not in (None, "", "[]")
                else (incoming or "[]")
            )
        updates["is_seed"] = int(bool(row["is_seed"] or is_seed))
        updates["updated_at"] = now
        assignments = ", ".join(f"{column}=?" for column in updates)
        self.conn.execute(
            f"UPDATE works SET {assignments} WHERE work_id=?",
            (*updates.values(), work_id),
        )

        for scheme, value in identifiers:
            conflict = self.conn.execute(
                "SELECT work_id FROM identifiers WHERE scheme=? AND value=?",
                (scheme, value),
            ).fetchone()
            if conflict and int(conflict["work_id"]) != work_id:
                other = int(conflict["work_id"])
                keep, remove = sorted(
                    (work_id, other),
                    key=lambda item: (
                        -int(
                            self.conn.execute(
                                "SELECT is_seed FROM works WHERE work_id=?", (item,)
                            ).fetchone()["is_seed"]
                        ),
                        item,
                    ),
                )
                work_id = self._merge_works(keep, remove)
            self.conn.execute(
                "INSERT OR IGNORE INTO identifiers VALUES(?,?,?)",
                (scheme, value, work_id),
            )

        all_ids = self.conn.execute(
            "SELECT scheme,value FROM identifiers WHERE work_id=?", (work_id,)
        ).fetchall()
        canonical = _best_canonical((row["scheme"], row["value"]) for row in all_ids)
        conflict = self.conn.execute(
            "SELECT work_id FROM works WHERE canonical_id=? AND work_id<>?",
            (canonical, work_id),
        ).fetchone()
        if conflict:
            work_id = self._merge_works(work_id, int(conflict["work_id"]))
        else:
            self.conn.execute(
                "UPDATE works SET canonical_id=? WHERE work_id=?", (canonical, work_id)
            )
        return work_id

    def ingest_bib_entries(
        self, entries: Iterable[BibEntry], citation_map: dict[str, list[str]]
    ) -> dict[str, int]:
        counts = {"entries": 0, "doi": 0, "arxiv": 0, "cited": 0}
        with self.transaction():
            for entry in entries:
                doi = extract_doi(entry)
                arxiv_id = extract_arxiv_id(entry)
                identifiers = [("bib", entry.key)]
                if doi:
                    identifiers.append(("doi", doi))
                    counts["doi"] += 1
                if arxiv_id:
                    identifiers.append(("arxiv", arxiv_id))
                    counts["arxiv"] += 1
                authors = list(iter_author_names(entry.fields.get("author")))
                title = clean_latex_text(entry.fields.get("title"))
                note = clean_latex_text(entry.fields.get("note")) or ""
                private_communication = "private communication" in note.casefold()
                data = {
                    "title": title,
                    "title_source": "bibtex" if title else None,
                    "metadata_status": (
                        "complete"
                        if title
                        else ("non_bibliographic" if private_communication else "incomplete")
                    ),
                    "entity_kind": (
                        "private_communication"
                        if private_communication
                        else "scholarly_work"
                    ),
                    "year": parse_year(entry.fields.get("year")),
                    "venue": clean_latex_text(
                        entry.fields.get("journal") or entry.fields.get("booktitle")
                    ),
                    "work_type": entry.entry_type,
                    "url": entry.fields.get("url"),
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "authors_json": authors,
                }
                work_id = self.upsert_work(data, identifiers, is_seed=True)
                cited_in = citation_map.get(entry.key, [])
                self.conn.execute(
                    """
                    INSERT INTO seed_entries
                    (bib_key,work_id,entry_type,raw_json,cited_in_json)
                    VALUES(?,?,?,?,?)
                    ON CONFLICT(bib_key) DO UPDATE SET
                        work_id=excluded.work_id,
                        entry_type=excluded.entry_type,
                        raw_json=excluded.raw_json,
                        cited_in_json=excluded.cited_in_json
                    """,
                    (
                        entry.key,
                        work_id,
                        entry.entry_type,
                        json.dumps(entry.fields, ensure_ascii=False),
                        json.dumps(cited_in, ensure_ascii=False),
                    ),
                )
                counts["entries"] += 1
                counts["cited"] += int(bool(cited_in))
        return counts

    def paper_uid(self, work_id: int) -> str:
        row = self.conn.execute(
            "SELECT paper_uid FROM works WHERE work_id=?", (work_id,)
        ).fetchone()
        if not row:
            raise KeyError(f"unknown work_id: {work_id}")
        return str(row["paper_uid"])

    def upsert_document(self, data: dict[str, Any]) -> str:
        now = utc_now()
        metadata = data.get("metadata_json") or {}
        if not isinstance(metadata, str):
            metadata = json.dumps(metadata, ensure_ascii=False)
        values = (
            data["document_id"],
            int(data["work_id"]),
            data["kind"],
            data["relative_path"],
            data.get("media_type"),
            data.get("language"),
            data.get("source_url"),
            data.get("sha256"),
            data.get("byte_size"),
            data.get("license"),
            int(bool(data.get("redistributable"))),
            data.get("status") or "available",
            metadata,
            now,
            now,
        )
        self.conn.execute(
            """
            INSERT INTO documents(
              document_id,work_id,kind,relative_path,media_type,language,
              source_url,sha256,byte_size,license,redistributable,status,
              metadata_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(relative_path) DO UPDATE SET
              work_id=excluded.work_id,
              kind=excluded.kind,
              media_type=excluded.media_type,
              language=excluded.language,
              source_url=excluded.source_url,
              sha256=excluded.sha256,
              byte_size=excluded.byte_size,
              license=excluded.license,
              redistributable=excluded.redistributable,
              status=excluded.status,
              metadata_json=excluded.metadata_json,
              updated_at=excluded.updated_at
            """,
            values,
        )
        row = self.conn.execute(
            "SELECT document_id FROM documents WHERE relative_path=?",
            (data["relative_path"],),
        ).fetchone()
        return str(row["document_id"])

    def replace_document_chunks(
        self, document_id: str, chunks: list[dict[str, Any]]
    ) -> None:
        self.conn.execute(
            "DELETE FROM document_chunks_fts WHERE document_id=?", (document_id,)
        )
        self.conn.execute(
            "DELETE FROM document_chunks WHERE document_id=?", (document_id,)
        )
        for index, chunk in enumerate(chunks):
            cursor = self.conn.execute(
                """
                INSERT INTO document_chunks(
                  document_id,chunk_index,heading,content,created_at
                ) VALUES(?,?,?,?,?)
                """,
                (
                    document_id,
                    index,
                    chunk.get("heading"),
                    chunk["content"],
                    utc_now(),
                ),
            )
            chunk_id = int(cursor.lastrowid)
            self.conn.execute(
                """
                INSERT INTO document_chunks_fts(
                  chunk_id,document_id,heading,content
                ) VALUES(?,?,?,?)
                """,
                (
                    chunk_id,
                    document_id,
                    chunk.get("heading"),
                    chunk["content"],
                ),
            )

    def search_document_chunks(
        self, query: str, *, limit: int = 10
    ) -> list[sqlite3.Row]:
        try:
            return self.conn.execute(
                """
                SELECT w.paper_uid,w.canonical_id,w.title,
                       d.document_id,d.relative_path,
                       c.chunk_index,c.heading,
                       snippet(document_chunks_fts,3,'[',']',' … ',24) AS excerpt,
                       bm25(document_chunks_fts) AS rank
                FROM document_chunks_fts
                JOIN document_chunks c
                  ON c.chunk_id=document_chunks_fts.chunk_id
                JOIN documents d ON d.document_id=c.document_id
                JOIN works w ON w.work_id=d.work_id
                WHERE document_chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, max(1, min(int(limit), 100))),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise ValueError(f"invalid FTS query: {query}") from exc

    def add_citation(self, citing_id: int, cited_id: int, provider: str) -> None:
        if citing_id == cited_id:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO citations VALUES(?,?,?,?)",
            (citing_id, cited_id, provider, utc_now()),
        )

    def save_provider_record(
        self, provider: str, provider_id: str, payload: dict[str, Any]
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO provider_records VALUES(?,?,?,?)
            ON CONFLICT(provider,provider_id) DO UPDATE SET
              payload_json=excluded.payload_json,
              fetched_at=excluded.fetched_at
            """,
            (
                provider,
                provider_id,
                json.dumps(payload, ensure_ascii=False),
                utc_now(),
            ),
        )

    def get_provider_record(
        self, provider: str, provider_id: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT payload_json FROM provider_records WHERE provider=? AND provider_id=?",
            (provider, provider_id),
        ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def mark_fetch(
        self,
        provider: str,
        work_id: int,
        operation: str,
        status: str,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO fetch_status
            (provider,work_id,operation,status,attempts,last_error,updated_at)
            VALUES(?,?,?,?,1,?,?)
            ON CONFLICT(provider,work_id,operation) DO UPDATE SET
                status=excluded.status,
                attempts=fetch_status.attempts+1,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (provider, work_id, operation, status, error, utc_now()),
        )

    def record_match(
        self,
        bib_key: str,
        provider: str,
        provider_id: str | None,
        method: str,
        score: float | None,
        status: str,
        evidence: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO matches VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(bib_key,provider) DO UPDATE SET
                provider_id=excluded.provider_id,
                method=excluded.method,
                score=excluded.score,
                status=excluded.status,
                evidence_json=excluded.evidence_json,
                updated_at=excluded.updated_at
            """,
            (
                bib_key,
                provider,
                provider_id,
                method,
                score,
                status,
                json.dumps(evidence, ensure_ascii=False),
                utc_now(),
            ),
        )

    def seed_rows(self, unresolved_provider: str | None = None) -> list[sqlite3.Row]:
        where = ""
        params: tuple[Any, ...] = ()
        if unresolved_provider == "openalex":
            where = "WHERE w.openalex_id IS NULL"
        return self.conn.execute(
            f"""
            SELECT w.*, s.bib_key, s.entry_type, s.raw_json, s.cited_in_json
            FROM seed_entries s JOIN works w ON w.work_id=s.work_id
            {where}
            ORDER BY s.bib_key
            """,
            params,
        ).fetchall()

    def resolved_seed_rows(self, provider: str) -> list[sqlite3.Row]:
        column = {"openalex": "openalex_id", "s2": "s2_id"}[provider]
        return self.conn.execute(
            f"""
            SELECT w.*, s.bib_key, s.raw_json
            FROM seed_entries s JOIN works w ON w.work_id=s.work_id
            WHERE w.{column} IS NOT NULL
            ORDER BY s.bib_key
            """
        ).fetchall()

    def pending_reference_metadata(
        self, provider: str, *, include_not_found: bool = False
    ) -> list[sqlite3.Row]:
        column = {"openalex": "openalex_id", "s2": "s2_id"}[provider]
        status_filter = "" if include_not_found else (
            "AND (f.status IS NULL OR f.status NOT IN ('not_found','done'))"
        )
        return self.conn.execute(
            f"""
            SELECT DISTINCT w.*
            FROM works w
            JOIN citations c ON c.cited_work_id=w.work_id
            LEFT JOIN provider_records p
              ON p.provider=? AND p.provider_id=w.{column}
            LEFT JOIN fetch_status f
              ON f.provider=? AND f.work_id=w.work_id AND f.operation='metadata'
            WHERE w.{column} IS NOT NULL AND p.provider_id IS NULL
              {status_filter}
            ORDER BY w.work_id
            """,
            (provider, provider),
        ).fetchall()

    def pending_abstract_metadata(
        self, provider: str, *, include_processed: bool = False
    ) -> list[sqlite3.Row]:
        column = {"openalex": "openalex_id", "s2": "s2_id"}[provider]
        status_filter = (
            ""
            if include_processed
            else "AND (f.status IS NULL OR f.status='error')"
        )
        return self.conn.execute(
            f"""
            SELECT w.*
            FROM works w
            LEFT JOIN fetch_status f
              ON f.provider=? AND f.work_id=w.work_id AND f.operation='abstract'
            WHERE w.{column} IS NOT NULL AND w.abstract IS NULL
              {status_filter}
            ORDER BY w.work_id
            """,
            (provider,),
        ).fetchall()

    def cache_get(self, key: str) -> tuple[int, str, str] | None:
        row = self.conn.execute(
            "SELECT status_code,body,fetched_at FROM api_cache WHERE cache_key=?",
            (key,),
        ).fetchone()
        return (
            (int(row["status_code"]), row["body"], row["fetched_at"]) if row else None
        )

    def cache_put(self, key: str, provider: str, status: int, body: str) -> None:
        self.conn.execute(
            """
            INSERT INTO api_cache VALUES(?,?,?,?,?)
            ON CONFLICT(cache_key) DO UPDATE SET
              status_code=excluded.status_code,
              body=excluded.body,
              fetched_at=excluded.fetched_at
            """,
            (key, provider, status, body, utc_now()),
        )
        self.conn.commit()

    def stats(self) -> dict[str, Any]:
        scalar = {}
        queries = {
            "works": "SELECT COUNT(*) FROM works",
            "seed_entries": "SELECT COUNT(*) FROM seed_entries",
            "seed_works": "SELECT COUNT(*) FROM works WHERE is_seed=1",
            "citation_edges_with_sources": "SELECT COUNT(*) FROM citations",
            "citation_edges": "SELECT COUNT(*) FROM (SELECT DISTINCT citing_work_id,cited_work_id FROM citations)",
            "seed_to_seed_edges": """
                SELECT COUNT(*) FROM (
                  SELECT DISTINCT c.citing_work_id,c.cited_work_id
                  FROM citations c JOIN works a ON a.work_id=c.citing_work_id
                  JOIN works b ON b.work_id=c.cited_work_id
                  WHERE a.is_seed=1 AND b.is_seed=1
                )
            """,
            "openalex_resolved_seeds": "SELECT COUNT(*) FROM works WHERE is_seed=1 AND openalex_id IS NOT NULL",
            "doi_seeds": "SELECT COUNT(*) FROM works WHERE is_seed=1 AND doi IS NOT NULL",
            "arxiv_seeds": "SELECT COUNT(*) FROM works WHERE is_seed=1 AND arxiv_id IS NOT NULL",
            "missing_titles": "SELECT COUNT(*) FROM works WHERE title IS NULL OR trim(title)=''",
            "documents": "SELECT COUNT(*) FROM documents",
            "available_markdown_documents": (
                "SELECT COUNT(*) FROM documents "
                "WHERE kind='markdown' AND status='available'"
            ),
            "document_chunks": "SELECT COUNT(*) FROM document_chunks",
            "review_mentions": "SELECT COUNT(*) FROM review_mentions",
            "work_classifications": "SELECT COUNT(*) FROM work_classifications",
            "classified_works": (
                "SELECT COUNT(DISTINCT work_id) FROM work_classifications"
            ),
            "taxonomy_versions": "SELECT COUNT(*) FROM taxonomy_definitions",
        }
        for name, query in queries.items():
            scalar[name] = int(self.conn.execute(query).fetchone()[0])
        scalar["merged_seed_aliases"] = scalar["seed_entries"] - scalar["seed_works"]
        scalar["matches"] = {
            row["status"]: int(row["count"])
            for row in self.conn.execute(
                "SELECT status,COUNT(*) AS count FROM matches GROUP BY status"
            )
        }
        return scalar
