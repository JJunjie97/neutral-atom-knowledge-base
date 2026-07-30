from __future__ import annotations

import hmac
import hashlib
import ipaddress
import json
import re
import secrets
import socket
import sqlite3
import threading
import uuid
from contextlib import suppress
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .bibtex import normalize_title


MAX_BODY_BYTES = 1_048_576
DEFAULT_ORIGINS = (
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://[::1]:3000",
)
PATCH_FIELDS = {
    "title",
    "abstract",
    "year",
    "publication_date",
    "authors",
    "venue",
    "work_type",
    "url",
    "oa_url",
    "metadata_status",
}
METADATA_STATUSES = {
    "complete",
    "incomplete",
    "unresolved_reference",
    "non_bibliographic",
    "needs_review",
    "no_title",
}


class AdminHTTPError(Exception):
    def __init__(self, status: int, message: str, code: str = "request_error"):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def admin_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _json_load(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _work_payload(row: sqlite3.Row, *, include_admin_version: bool = True) -> dict[str, Any]:
    work = dict(row)
    work["authors"] = _json_load(work.get("authors_json"), [])
    work["topics"] = _json_load(work.get("topics_json"), [])
    if include_admin_version:
        work["admin_version"] = _work_version(row)
    return work


def _work_version(row: sqlite3.Row) -> str:
    canonical = json.dumps(
        dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme != "http" or not parsed.hostname or not _is_loopback_host(parsed.hostname):
        raise ValueError(f"admin CORS origin must be loopback HTTP: {origin}")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid admin CORS origin: {origin}") from exc
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(f"invalid admin CORS origin: {origin}")
    return origin.rstrip("/")


class AdminService:
    def __init__(
        self,
        db_path: str | Path,
        *,
        token: str | None = None,
        backup_dir: str | Path = "data/backups",
        allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS,
    ):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError(
                f"database does not exist; run ingest first or pass --db: {self.db_path}"
            )
        self.backup_dir = Path(backup_dir).resolve()
        self.token = (token or secrets.token_urlsafe(32)).strip()
        if not self.token:
            raise ValueError("admin token cannot be empty")
        self.allowed_origins = frozenset(_validate_origin(item) for item in allowed_origins)
        self._backup_lock = threading.Lock()
        self._backup_path: Path | None = None
        conn = self.connect()
        try:
            conn.execute("SELECT work_id FROM works LIMIT 1").fetchone()
        except sqlite3.DatabaseError as exc:
            raise ValueError(f"not a compatible literature database: {self.db_path}") from exc
        finally:
            conn.close()

    @property
    def backup_path(self) -> Path | None:
        return self._backup_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def ensure_backup(self) -> Path:
        with self._backup_lock:
            if self._backup_path is not None:
                return self._backup_path
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            target_path = self.backup_dir / f"literature-before-admin-{stamp}.sqlite"
            print(f"[Admin] Creating consistent SQLite backup: {target_path}", flush=True)
            source: sqlite3.Connection | None = None
            target: sqlite3.Connection | None = None
            completed = False
            last_bucket = -1

            def progress(_status: int, remaining: int, total: int) -> None:
                nonlocal last_bucket
                percent = 100 if total <= 0 else int(100 * (total - remaining) / total)
                bucket = min(10, percent // 10)
                if bucket != last_bucket or remaining == 0:
                    last_bucket = bucket
                    print(f"[Admin] Backup progress: {percent}%", flush=True)

            try:
                source = self.connect()
                target = sqlite3.connect(target_path)
                source.backup(target, pages=2048, progress=progress, sleep=0.01)
                integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"backup integrity check failed: {integrity}")
                target.commit()
                completed = True
            finally:
                for connection in (target, source):
                    if connection is not None:
                        with suppress(Exception):
                            connection.close()
                if not completed:
                    for candidate in (
                        target_path,
                        Path(f"{target_path}-wal"),
                        Path(f"{target_path}-shm"),
                    ):
                        with suppress(OSError):
                            candidate.unlink()
            self._backup_path = target_path
            print("[Admin] Backup complete; writes are now enabled.", flush=True)
            return target_path

    def summary(self) -> dict[str, Any]:
        conn = self.connect()
        try:
            scalar = lambda sql: int(conn.execute(sql).fetchone()[0])
            return {
                "works": scalar("SELECT COUNT(*) FROM works"),
                "seed_works": scalar("SELECT COUNT(*) FROM works WHERE is_seed=1"),
                "citation_edges": scalar(
                    "SELECT COUNT(*) FROM (SELECT DISTINCT citing_work_id,cited_work_id FROM citations)"
                ),
                "unresolved_seeds": scalar(
                    "SELECT COUNT(*) FROM matches WHERE status IN ('needs_review','not_found')"
                ),
                "manual_classifications": scalar(
                    "SELECT COUNT(*) FROM work_classifications WHERE method='manual'"
                ),
                "database_path": str(self.db_path),
                "updated_at": conn.execute(
                    "SELECT MAX(updated_at) FROM works"
                ).fetchone()[0],
                "backup_created": self._backup_path is not None,
                "backup_path": str(self._backup_path) if self._backup_path else None,
            }
        finally:
            conn.close()

    def current_taxonomy(self) -> dict[str, Any]:
        conn = self.connect()
        try:
            row = conn.execute(
                """
                SELECT taxonomy_version,taxonomy_digest,definition_json,updated_at
                FROM taxonomy_definitions
                ORDER BY updated_at DESC,taxonomy_version DESC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return {"current_version": None, "current": None}
            definition = _json_load(row["definition_json"], {})
            current = {
                "version": row["taxonomy_version"],
                "digest": row["taxonomy_digest"],
                "dimensions": definition.get("dimensions", []),
            }
            return {"current_version": row["taxonomy_version"], "current": current}
        finally:
            conn.close()

    def list_works(
        self,
        *,
        query: str = "",
        metadata_status: str = "",
        seed: bool | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            pattern = f"%{query}%"
            clauses.append(
                """(
                  w.title LIKE ? OR w.paper_uid LIKE ? OR w.canonical_id LIKE ?
                  OR w.doi LIKE ? OR w.arxiv_id LIKE ? OR w.openalex_id LIKE ?
                  OR w.venue LIKE ? OR w.authors_json LIKE ? OR EXISTS(
                    SELECT 1 FROM identifiers i
                    WHERE i.work_id=w.work_id AND i.value LIKE ?
                  )
                )"""
            )
            params.extend([pattern] * 9)
        if metadata_status:
            clauses.append("w.metadata_status=?")
            params.append(metadata_status)
        if seed is not None:
            clauses.append("w.is_seed=?")
            params.append(1 if seed else 0)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        conn = self.connect()
        try:
            total = int(
                conn.execute(f"SELECT COUNT(*) FROM works w{where}", params).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                SELECT w.work_id,w.paper_uid,w.canonical_id,w.title,w.year,w.venue,
                       w.doi,w.arxiv_id,w.openalex_id,w.authors_json,
                       w.metadata_status,w.is_seed,w.updated_at
                FROM works w{where}
                ORDER BY CASE WHEN w.title IS NULL OR trim(w.title)='' THEN 0 ELSE 1 END,
                         w.is_seed DESC,w.year DESC,w.work_id
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()
            return {
                "items": [
                    _work_payload(row, include_admin_version=False) for row in rows
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()

    def work_detail(self, work_id: int, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        own_connection = conn is None
        conn = conn or self.connect()
        try:
            work_row = conn.execute(
                "SELECT * FROM works WHERE work_id=?", (work_id,)
            ).fetchone()
            if work_row is None:
                raise AdminHTTPError(404, "work not found", "not_found")
            identifiers = [
                dict(row)
                for row in conn.execute(
                    "SELECT scheme,value FROM identifiers WHERE work_id=? ORDER BY scheme,value",
                    (work_id,),
                )
            ]
            classifications = []
            for row in conn.execute(
                """
                SELECT rowid AS classification_id,* FROM work_classifications
                WHERE work_id=?
                ORDER BY method='manual' DESC,dimension_id,category_id,method
                """,
                (work_id,),
            ):
                item = dict(row)
                item["evidence"] = _json_load(item.get("evidence_json"), {})
                classifications.append(item)
            seeds = []
            for row in conn.execute(
                "SELECT * FROM seed_entries WHERE work_id=? ORDER BY bib_key", (work_id,)
            ):
                item = dict(row)
                item["raw"] = _json_load(item.get("raw_json"), {})
                item["cited_in"] = _json_load(item.get("cited_in_json"), [])
                seeds.append(item)
            documents = []
            for row in conn.execute(
                "SELECT * FROM documents WHERE work_id=? ORDER BY kind,document_id", (work_id,)
            ):
                item = dict(row)
                item["metadata"] = _json_load(item.get("metadata_json"), {})
                documents.append(item)
            citation_counts = {
                "references": int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT cited_work_id) FROM citations WHERE citing_work_id=?",
                        (work_id,),
                    ).fetchone()[0]
                ),
                "cited_by": int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT citing_work_id) FROM citations WHERE cited_work_id=?",
                        (work_id,),
                    ).fetchone()[0]
                ),
                "source_rows": int(
                    conn.execute(
                        "SELECT COUNT(*) FROM citations WHERE citing_work_id=? OR cited_work_id=?",
                        (work_id, work_id),
                    ).fetchone()[0]
                ),
            }
            return {
                "work": _work_payload(work_row),
                "identifiers": identifiers,
                "classifications": classifications,
                "seed_entries": seeds,
                "documents": documents,
                "citation_counts": citation_counts,
            }
        finally:
            if own_connection:
                conn.close()

    def _validate_patch(self, changes: Any) -> dict[str, Any]:
        if not isinstance(changes, dict) or not changes:
            raise AdminHTTPError(400, "changes must be a non-empty object", "invalid_changes")
        unknown = sorted(set(changes) - PATCH_FIELDS)
        if unknown:
            raise AdminHTTPError(
                400,
                f"fields are read-only or unknown: {', '.join(unknown)}",
                "read_only_field",
            )
        values: dict[str, Any] = {}

        def nullable_text(name: str, max_length: int) -> None:
            value = changes[name]
            if value is None:
                values[name] = None
                return
            if not isinstance(value, str):
                raise AdminHTTPError(400, f"{name} must be a string or null")
            value = value.strip()
            if len(value) > max_length:
                raise AdminHTTPError(400, f"{name} is too long")
            values[name] = value or None

        for field, maximum in (
            ("title", 2_000),
            ("abstract", 900_000),
            ("venue", 2_000),
            ("work_type", 500),
            ("url", 4_096),
            ("oa_url", 4_096),
        ):
            if field in changes:
                nullable_text(field, maximum)
        if "year" in changes:
            value = changes["year"]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1600
                or value > 2200
            ):
                raise AdminHTTPError(400, "year must be an integer from 1600 to 2200 or null")
            values["year"] = value
        if "publication_date" in changes:
            value = changes["publication_date"]
            if value is not None:
                if not isinstance(value, str):
                    raise AdminHTTPError(400, "publication_date must be YYYY-MM-DD or null")
                value = value.strip()
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
                    raise AdminHTTPError(400, "publication_date must be a valid YYYY-MM-DD date")
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise AdminHTTPError(
                        400, "publication_date must be a valid YYYY-MM-DD date"
                    ) from exc
            values["publication_date"] = value or None if isinstance(value, str) else value
        if "authors" in changes:
            authors = changes["authors"]
            if not isinstance(authors, list) or len(authors) > 200:
                raise AdminHTTPError(400, "authors must be an array with at most 200 names")
            normalized_authors: list[str] = []
            for author in authors:
                if not isinstance(author, str) or not author.strip() or len(author.strip()) > 500:
                    raise AdminHTTPError(400, "each author must be a non-empty string")
                normalized_authors.append(author.strip())
            values["authors_json"] = json.dumps(
                normalized_authors, ensure_ascii=False, separators=(",", ":")
            )
        for field in ("url", "oa_url"):
            value = values.get(field)
            if value is not None:
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise AdminHTTPError(400, f"{field} must be an HTTP(S) URL or null")
        if "metadata_status" in changes:
            value = changes["metadata_status"]
            if value not in METADATA_STATUSES:
                raise AdminHTTPError(400, "invalid metadata_status")
            values["metadata_status"] = value
        return values

    @staticmethod
    def _check_expected(row: sqlite3.Row, expected: Any) -> str:
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise AdminHTTPError(400, "expected_updated_at is required", "missing_version")
        if not hmac.compare_digest(_work_version(row), expected):
            raise AdminHTTPError(
                409,
                "work changed since it was loaded; reload before saving",
                "version_conflict",
            )
        return str(row["updated_at"])

    @staticmethod
    def _ensure_admin_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                changes_json TEXT NOT NULL DEFAULT '{}',
                actor TEXT NOT NULL DEFAULT 'local_admin',
                request_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_admin_audit_entity
            ON admin_audit_log(entity_type,entity_id,audit_id DESC)
            """
        )

    @staticmethod
    def _write_audit(
        conn: sqlite3.Connection,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        before: Any,
        after: Any,
        request_id: str,
        created_at: str,
    ) -> None:
        AdminService._ensure_admin_schema(conn)
        conn.execute(
            """
            INSERT INTO admin_audit_log(
              action,entity_type,entity_id,changes_json,actor,request_id,created_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                action,
                entity_type,
                entity_id,
                json.dumps(
                    {"before": before, "after": after},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "local_admin",
                request_id,
                created_at,
            ),
        )

    def patch_work(self, work_id: int, payload: Any, request_id: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AdminHTTPError(400, "JSON body must be an object")
        expected = payload.get("expected_updated_at")
        submitted = self._validate_patch(payload.get("changes"))
        probe = self.connect()
        try:
            row = probe.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if row is None:
                raise AdminHTTPError(404, "work not found", "not_found")
            self._check_expected(row, expected)
            values = self._changed_patch_values(row, submitted)
            if not values:
                return self.work_detail(work_id, probe)
        finally:
            probe.close()
        self.ensure_backup()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if row is None:
                raise AdminHTTPError(404, "work not found", "not_found")
            expected = self._check_expected(row, expected)
            values = self._changed_patch_values(row, submitted)
            if not values:
                detail = self.work_detail(work_id, conn)
                conn.commit()
                return detail
            before = {field: row[field] for field in values}
            new_time = admin_now()
            assignments = ",".join(f"{field}=?" for field in values)
            cursor = conn.execute(
                f"UPDATE works SET {assignments},updated_at=? WHERE work_id=? AND updated_at=?",
                [*values.values(), new_time, work_id, expected],
            )
            if cursor.rowcount != 1:
                raise AdminHTTPError(409, "work changed during save", "version_conflict")
            after_row = conn.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            after = {field: after_row[field] for field in values}
            self._write_audit(
                conn,
                action="work.patch",
                entity_type="work",
                entity_id=str(work_id),
                before=before,
                after=after,
                request_id=request_id,
                created_at=new_time,
            )
            detail = self.work_detail(work_id, conn)
            conn.commit()
            return detail
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _changed_patch_values(
        row: sqlite3.Row, submitted: dict[str, Any]
    ) -> dict[str, Any]:
        values = dict(submitted)
        if "title" in values and values["title"] != row["title"]:
            values["title_normalized"] = (
                normalize_title(values["title"]) if values["title"] else None
            )
            values["title_source"] = "manual" if values["title"] else None
        return {field: value for field, value in values.items() if row[field] != value}

    def _current_taxonomy_row(self, conn: sqlite3.Connection) -> tuple[sqlite3.Row, dict[str, Any]]:
        row = conn.execute(
            """
            SELECT taxonomy_version,taxonomy_digest,definition_json
            FROM taxonomy_definitions
            ORDER BY updated_at DESC,taxonomy_version DESC LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise AdminHTTPError(409, "no active taxonomy is registered", "taxonomy_missing")
        definition = _json_load(row["definition_json"], {})
        return row, definition

    @staticmethod
    def _validate_classification(
        payload: Any, taxonomy_row: sqlite3.Row, definition: dict[str, Any]
    ) -> tuple[str, str, float]:
        if not isinstance(payload, dict):
            raise AdminHTTPError(400, "JSON body must be an object")
        if payload.get("method", "manual") != "manual":
            raise AdminHTTPError(400, "only method=manual can be changed")
        if payload.get("taxonomy_version") != taxonomy_row["taxonomy_version"]:
            raise AdminHTTPError(409, "taxonomy changed; reload the editor", "taxonomy_conflict")
        dimension_id = payload.get("dimension_id")
        category_id = payload.get("category_id")
        if not isinstance(dimension_id, str) or not isinstance(category_id, str):
            raise AdminHTTPError(400, "dimension_id and category_id are required")
        dimensions = {
            item.get("id"): item
            for item in definition.get("dimensions", [])
            if isinstance(item, dict)
        }
        dimension = dimensions.get(dimension_id)
        categories = {
            item.get("id")
            for item in (dimension or {}).get("categories", [])
            if isinstance(item, dict)
        }
        if dimension is None or category_id not in categories:
            raise AdminHTTPError(400, "classification is not defined by the active taxonomy")
        confidence = payload.get("confidence", 1.0)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise AdminHTTPError(400, "confidence must be a number from 0 to 1")
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise AdminHTTPError(400, "confidence must be a number from 0 to 1")
        return dimension_id, category_id, confidence

    def upsert_manual_classification(
        self, work_id: int, payload: Any, request_id: str
    ) -> dict[str, Any]:
        probe = self.connect()
        try:
            work = probe.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if work is None:
                raise AdminHTTPError(404, "work not found", "not_found")
            expected = payload.get("expected_updated_at") if isinstance(payload, dict) else None
            self._check_expected(work, expected)
            taxonomy, definition = self._current_taxonomy_row(probe)
            self._validate_classification(payload, taxonomy, definition)
        finally:
            probe.close()
        self.ensure_backup()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            work = conn.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if work is None:
                raise AdminHTTPError(404, "work not found", "not_found")
            expected = payload.get("expected_updated_at") if isinstance(payload, dict) else None
            self._check_expected(work, expected)
            taxonomy, definition = self._current_taxonomy_row(conn)
            dimension_id, category_id, confidence = self._validate_classification(
                payload, taxonomy, definition
            )
            before_row = conn.execute(
                """
                SELECT rowid AS classification_id,* FROM work_classifications
                WHERE work_id=? AND taxonomy_version=? AND dimension_id=?
                  AND category_id=? AND method='manual'
                """,
                (work_id, taxonomy["taxonomy_version"], dimension_id, category_id),
            ).fetchone()
            now = admin_now()
            evidence = json.dumps(
                {"source": "local_admin", "request_id": request_id},
                ensure_ascii=False,
                sort_keys=True,
            )
            conn.execute(
                """
                INSERT INTO work_classifications(
                  work_id,taxonomy_version,taxonomy_digest,dimension_id,category_id,
                  method,confidence,evidence_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,'manual',?,?,?,?)
                ON CONFLICT(work_id,taxonomy_version,dimension_id,category_id,method)
                DO UPDATE SET confidence=excluded.confidence,
                              evidence_json=excluded.evidence_json,
                              updated_at=excluded.updated_at
                """,
                (
                    work_id,
                    taxonomy["taxonomy_version"],
                    taxonomy["taxonomy_digest"],
                    dimension_id,
                    category_id,
                    confidence,
                    evidence,
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE works SET updated_at=? WHERE work_id=?", (now, work_id))
            after_row = conn.execute(
                """
                SELECT rowid AS classification_id,* FROM work_classifications
                WHERE work_id=? AND taxonomy_version=? AND dimension_id=?
                  AND category_id=? AND method='manual'
                """,
                (work_id, taxonomy["taxonomy_version"], dimension_id, category_id),
            ).fetchone()
            entity_id = (
                f"{work_id}:{taxonomy['taxonomy_version']}:{dimension_id}:{category_id}:manual"
            )
            self._write_audit(
                conn,
                action="classification.upsert",
                entity_type="work_classification",
                entity_id=entity_id,
                before=_row_dict(before_row),
                after=_row_dict(after_row),
                request_id=request_id,
                created_at=now,
            )
            detail = self.work_detail(work_id, conn)
            conn.commit()
            return detail
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_manual_classification(
        self,
        work_id: int,
        payload: Any,
        request_id: str,
        *,
        classification_id: int | None = None,
        dimension_id: str | None = None,
        category_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AdminHTTPError(400, "JSON body must be an object")
        probe = self.connect()
        try:
            work = probe.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if work is None:
                raise AdminHTTPError(404, "work not found", "not_found")
            self._check_expected(work, payload.get("expected_updated_at"))
            row = self._find_manual_classification(
                probe,
                work_id,
                classification_id=classification_id,
                dimension_id=dimension_id,
                category_id=category_id,
            )
            if row is None:
                raise AdminHTTPError(404, "manual classification not found", "not_found")
        finally:
            probe.close()
        self.ensure_backup()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            work = conn.execute("SELECT * FROM works WHERE work_id=?", (work_id,)).fetchone()
            if work is None:
                raise AdminHTTPError(404, "work not found", "not_found")
            self._check_expected(work, payload.get("expected_updated_at"))
            row = self._find_manual_classification(
                conn,
                work_id,
                classification_id=classification_id,
                dimension_id=dimension_id,
                category_id=category_id,
            )
            if row is None:
                raise AdminHTTPError(404, "manual classification not found", "not_found")
            conn.execute("DELETE FROM work_classifications WHERE rowid=?", (row["classification_id"],))
            now = admin_now()
            conn.execute("UPDATE works SET updated_at=? WHERE work_id=?", (now, work_id))
            self._write_audit(
                conn,
                action="classification.delete",
                entity_type="work_classification",
                entity_id=(
                    f"{work_id}:{row['taxonomy_version']}:{row['dimension_id']}:"
                    f"{row['category_id']}:manual"
                ),
                before=dict(row),
                after=None,
                request_id=request_id,
                created_at=now,
            )
            detail = self.work_detail(work_id, conn)
            conn.commit()
            return detail
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _find_manual_classification(
        conn: sqlite3.Connection,
        work_id: int,
        *,
        classification_id: int | None,
        dimension_id: str | None,
        category_id: str | None,
    ) -> sqlite3.Row | None:
        if classification_id is not None:
            return conn.execute(
                """
                SELECT rowid AS classification_id,* FROM work_classifications
                WHERE rowid=? AND work_id=? AND method='manual'
                """,
                (classification_id, work_id),
            ).fetchone()
        return conn.execute(
            """
            SELECT rowid AS classification_id,* FROM work_classifications
            WHERE work_id=? AND dimension_id=? AND category_id=? AND method='manual'
            ORDER BY updated_at DESC LIMIT 1
            """,
            (work_id, dimension_id, category_id),
        ).fetchone()


class AdminRequestHandler(BaseHTTPRequestHandler):
    server_version = "NeutralAtomAdmin/0.1"

    @property
    def service(self) -> AdminService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[Admin] {self.address_string()} - {fmt % args}", flush=True)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") in self.service.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin.rstrip("/"))
            self.send_header("Vary", "Origin")
        super().end_headers()

    def _send_json(self, status: int, payload: Any, *, request_id: str) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", request_id)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as exc:
            print(f"[Admin] Client disconnected ({request_id}): {exc}", flush=True)

    def _check_origin(self) -> None:
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") not in self.service.allowed_origins:
            raise AdminHTTPError(403, "origin is not allowed", "cors_denied")

    def _check_auth(self) -> None:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        candidate = header[len(prefix) :] if header.startswith(prefix) else ""
        if not candidate or not hmac.compare_digest(
            candidate.encode("utf-8"), self.service.token.encode("utf-8")
        ):
            raise AdminHTTPError(401, "missing or invalid bearer token", "unauthorized")

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise AdminHTTPError(411, "Content-Length is required", "length_required")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise AdminHTTPError(400, "invalid Content-Length") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise AdminHTTPError(413, "request body is too large", "body_too_large")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdminHTTPError(400, "request body must be valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise AdminHTTPError(400, "JSON body must be an object")
        return payload

    @staticmethod
    def _int_query(values: dict[str, list[str]], name: str, default: int) -> int:
        raw = values.get(name, [str(default)])[0]
        try:
            return int(raw)
        except ValueError as exc:
            raise AdminHTTPError(400, f"{name} must be an integer") from exc

    @staticmethod
    def _work_id(value: str) -> int:
        try:
            parsed = int(unquote(value))
        except ValueError as exc:
            raise AdminHTTPError(400, "work id must be an integer") from exc
        if parsed <= 0:
            raise AdminHTTPError(400, "work id must be positive")
        return parsed

    def _dispatch(self, request_id: str) -> tuple[int, Any]:
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query, keep_blank_values=True)
        if path == "/api/health" and self.command == "GET":
            return 200, {
                "status": "ok",
                "service": "neutral-atom-local-admin",
                "database_exists": self.service.db_path.is_file(),
                "write_scope": "loopback-only",
            }
        self._check_auth()
        if path == "/api/admin/summary" and self.command == "GET":
            return 200, self.service.summary()
        if path == "/api/admin/taxonomies" and self.command == "GET":
            return 200, self.service.current_taxonomy()
        if path == "/api/works" and self.command == "GET":
            limit = self._int_query(query, "limit", 25)
            offset = self._int_query(query, "offset", 0)
            if not 1 <= limit <= 100 or not 0 <= offset <= 10_000_000:
                raise AdminHTTPError(400, "limit must be 1-100 and offset must be non-negative")
            raw_seed = query.get("seed", [""])[0].strip().lower()
            seed: bool | None
            if raw_seed in {"", "all"}:
                seed = None
            elif raw_seed in {"1", "true", "yes"}:
                seed = True
            elif raw_seed in {"0", "false", "no"}:
                seed = False
            else:
                raise AdminHTTPError(400, "seed must be true, false, or omitted")
            search = query.get("q", [""])[0].strip()
            status = query.get("metadata_status", [""])[0].strip()
            if len(search) > 300 or len(status) > 100:
                raise AdminHTTPError(400, "query is too long")
            return 200, self.service.list_works(
                query=search,
                metadata_status=status,
                seed=seed,
                limit=limit,
                offset=offset,
            )
        work_match = re.fullmatch(r"/api/works/([^/]+)", path)
        if work_match:
            work_id = self._work_id(work_match.group(1))
            if self.command == "GET":
                return 200, self.service.work_detail(work_id)
            if self.command == "PATCH":
                return 200, self.service.patch_work(work_id, self._read_json(), request_id)
            raise AdminHTTPError(405, "method not allowed", "method_not_allowed")
        classification_match = re.fullmatch(
            r"/api/works/([^/]+)/classifications(?:/([^/]+))?", path
        )
        if classification_match:
            work_id = self._work_id(classification_match.group(1))
            classification_id = classification_match.group(2)
            if self.command == "POST" and classification_id is None:
                return 200, self.service.upsert_manual_classification(
                    work_id, self._read_json(), request_id
                )
            if self.command == "DELETE":
                parsed_id: int | None = None
                if classification_id is not None:
                    try:
                        parsed_id = int(unquote(classification_id))
                    except ValueError as exc:
                        raise AdminHTTPError(400, "classification id must be an integer") from exc
                return 200, self.service.delete_manual_classification(
                    work_id,
                    self._read_json(),
                    request_id,
                    classification_id=parsed_id,
                    dimension_id=query.get("dimension", [None])[0],
                    category_id=query.get("category", [None])[0],
                )
            raise AdminHTTPError(405, "method not allowed", "method_not_allowed")
        raise AdminHTTPError(404, "endpoint not found", "not_found")

    def _handle(self) -> None:
        request_id = str(uuid.uuid4())
        try:
            self._check_origin()
            status, payload = self._dispatch(request_id)
            self._send_json(status, payload, request_id=request_id)
        except AdminHTTPError as exc:
            self._send_json(
                exc.status,
                {
                    "error": exc.code,
                    "message": exc.message,
                    "request_id": request_id,
                },
                request_id=request_id,
            )
        except sqlite3.OperationalError as exc:
            sqlite_code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
            busy = sqlite_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
            self._send_json(
                503 if busy else 500,
                {
                    "error": "database_busy" if busy else "database_error",
                    "message": (
                        "database is busy; retry after the current job finishes"
                        if busy
                        else "database operation failed; see the server terminal"
                    ),
                    "request_id": request_id,
                },
                request_id=request_id,
            )
            print(f"[Admin] SQLite error ({request_id}): {exc}", flush=True)
        except (BrokenPipeError, ConnectionResetError) as exc:
            print(f"[Admin] Client disconnected ({request_id}): {exc}", flush=True)
        except Exception as exc:
            self._send_json(
                500,
                {
                    "error": "internal_error",
                    "message": "local admin request failed; see the server terminal",
                    "request_id": request_id,
                },
                request_id=request_id,
            )
            print(f"[Admin] Request failed ({request_id}): {exc!r}", flush=True)

    def do_OPTIONS(self) -> None:
        request_id = str(uuid.uuid4())
        try:
            self._check_origin()
        except AdminHTTPError as exc:
            self._send_json(
                exc.status,
                {"error": exc.code, "message": exc.message, "request_id": request_id},
                request_id=request_id,
            )
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, PATCH, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("X-Request-ID", request_id)
        self.end_headers()

    def do_GET(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()


class AdminHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], service: AdminService):
        self.service = service
        super().__init__(address, AdminRequestHandler)


class AdminIPv6HTTPServer(AdminHTTPServer):
    address_family = socket.AF_INET6


def create_admin_server(
    service: AdminService, host: str = "127.0.0.1", port: int = 8765
) -> AdminHTTPServer:
    if not _is_loopback_host(host):
        raise ValueError("admin server may only bind to a loopback address")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    server_class = AdminIPv6HTTPServer if ":" in host else AdminHTTPServer
    return server_class((host, port), service)


def serve_admin(
    db_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    backup_dir: str | Path = "data/backups",
    allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS,
) -> None:
    service = AdminService(
        db_path,
        token=token,
        backup_dir=backup_dir,
        allowed_origins=allowed_origins,
    )
    server = create_admin_server(service, host, port)
    bound_host, bound_port = server.server_address[:2]
    display_host = f"[{bound_host}]" if ":" in str(bound_host) else bound_host
    print(f"[Admin] Local API: http://{display_host}:{bound_port}", flush=True)
    print(f"[Admin] Session token: {service.token}", flush=True)
    print(f"[Admin] Database: {service.db_path}", flush=True)
    print(f"[Admin] First-write backups: {service.backup_dir}", flush=True)
    print("[Admin] Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\n[Admin] Stopping local admin API.", flush=True)
    finally:
        server.server_close()
