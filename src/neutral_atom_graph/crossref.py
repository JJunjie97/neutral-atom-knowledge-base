from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .bibtex import normalize_doi
from .db import LiteratureDB


BASE_URL = "https://api.crossref.org/v1"


class CrossrefError(RuntimeError):
    pass


class CrossrefClient:
    def __init__(
        self,
        db: LiteratureDB,
        *,
        email: str | None = None,
        request_delay: float = 0.15,
        refresh: bool = False,
    ):
        self.db = db
        self.email = email or os.getenv("LITGRAPH_EMAIL")
        self.request_delay = max(0.0, request_delay)
        self.refresh = refresh

    def work(self, doi: str) -> dict[str, Any] | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        cache_key = f"crossref:work:{normalized}"
        cached = self.db.cache_get(cache_key)
        if cached and not self.refresh:
            status, body, _ = cached
            if status == 404:
                return None
            if status == 200:
                return json.loads(body)

        query = {"mailto": self.email} if self.email else {}
        url = (
            f"{BASE_URL}/works/{urllib.parse.quote(normalized, safe='')}"
            f"?{urllib.parse.urlencode(query)}"
        )
        headers = {
            "Accept": "application/json",
            "User-Agent": (
                "neutral-atom-knowledge-base/0.2 "
                f"(mailto:{self.email or 'unknown@example.invalid'})"
            ),
        }
        time.sleep(self.request_delay)
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=headers), timeout=60
            ) as response:
                body = response.read().decode("utf-8")
                self.db.cache_put(cache_key, "crossref", response.status, body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self.db.cache_put(cache_key, "crossref", exc.code, body)
            if exc.code == 404:
                return None
            raise CrossrefError(f"Crossref HTTP {exc.code}: {body[:300]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise CrossrefError(f"Crossref request failed: {exc}") from exc

        payload = json.loads(body)
        return payload.get("message") if isinstance(payload, dict) else None


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _year(payload: dict[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published", "issued"):
        parts = (payload.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and isinstance(parts[0][0], int):
            return int(parts[0][0])
    return None


def _authors(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for author in payload.get("author") or []:
        name = " ".join(
            value.strip()
            for value in (author.get("given"), author.get("family"))
            if isinstance(value, str) and value.strip()
        )
        if name:
            result.append(name)
    return result


def _plain_abstract(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(without_tags).split()) or None


def crossref_work_data(payload: dict[str, Any]) -> dict[str, Any]:
    title = _first(payload.get("title"))
    return {
        "title": title,
        "title_source": "crossref" if title else None,
        "metadata_status": "complete" if title else "no_title",
        "entity_kind": "scholarly_work",
        "year": _year(payload),
        "venue": _first(payload.get("container-title")),
        "work_type": payload.get("type"),
        "abstract": _plain_abstract(payload.get("abstract")),
        "url": payload.get("URL"),
        "authors_json": _authors(payload),
        "citation_count": payload.get("is-referenced-by-count"),
        "reference_count": len(payload.get("reference") or []),
    }


def repair_missing_doi_metadata(
    db: LiteratureDB,
    client: CrossrefClient,
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
    counts = {
        "requested": len(rows),
        "recovered": 0,
        "no_title": 0,
        "not_found": 0,
        "errors": 0,
    }
    for index, row in enumerate(rows, start=1):
        doi = row["doi"]
        print(f"[Crossref] missing-title DOI {index}/{len(rows)}: {doi}", flush=True)
        try:
            payload = client.work(doi)
            if payload is None:
                db.mark_fetch(
                    "crossref",
                    int(row["work_id"]),
                    "metadata",
                    "not_found",
                    "Crossref has no record for this DOI",
                )
                db.conn.commit()
                counts["not_found"] += 1
                continue
            data = crossref_work_data(payload)
            work_id = db.upsert_work(
                data,
                [("doi", doi)],
                preferred_work_id=int(row["work_id"]),
            )
            db.save_provider_record("crossref", doi, payload)
            if data.get("title"):
                db.mark_fetch("crossref", work_id, "metadata", "done")
                counts["recovered"] += 1
            else:
                db.mark_fetch(
                    "crossref",
                    work_id,
                    "metadata",
                    "no_title",
                    "Crossref record has no title",
                )
                counts["no_title"] += 1
            db.conn.commit()
        except Exception as exc:
            db.mark_fetch(
                "crossref",
                int(row["work_id"]),
                "metadata",
                "error",
                str(exc),
            )
            db.conn.commit()
            counts["errors"] += 1
    return counts
