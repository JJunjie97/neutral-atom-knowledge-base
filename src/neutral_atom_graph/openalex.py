from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from .bibtex import normalize_doi
from .db import LiteratureDB


BASE_URL = "https://api.openalex.org"
WORK_FIELDS = ",".join(
    [
        "id",
        "doi",
        "title",
        "display_name",
        "publication_year",
        "publication_date",
        "authorships",
        "primary_location",
        "best_oa_location",
        "open_access",
        "referenced_works",
        "referenced_works_count",
        "cited_by_count",
        "abstract_inverted_index",
        "type",
        "primary_topic",
        "topics",
    ]
)


class OpenAlexError(RuntimeError):
    pass


def short_openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.rstrip("/").rsplit("/", 1)[-1].upper()
    return value if value.startswith("W") and value[1:].isdigit() else None


def chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class OpenAlexClient:
    def __init__(
        self,
        db: LiteratureDB,
        *,
        api_key: str | None = None,
        email: str | None = None,
        request_delay: float = 0.12,
        cache_days: int = 30,
        refresh: bool = False,
        max_retries: int = 5,
    ):
        self.db = db
        self.api_key = api_key or os.getenv("OPENALEX_API_KEY")
        self.email = email or os.getenv("LITGRAPH_EMAIL")
        self.request_delay = max(request_delay, 0.0)
        self.cache_days = cache_days
        self.refresh = refresh
        self.max_retries = max_retries
        self._last_request = 0.0

    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        clean = {key: value for key, value in params.items() if key != "api_key"}
        encoded = urllib.parse.urlencode(sorted(clean.items()), doseq=True)
        digest = hashlib.sha256(f"{path}?{encoded}".encode()).hexdigest()
        return f"openalex:{digest}"

    def _cached(self, key: str) -> Any | None:
        if self.refresh:
            return None
        cached = self.db.cache_get(key)
        if not cached:
            return None
        status, body, fetched_at = cached
        fetched = datetime.fromisoformat(fetched_at)
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched > timedelta(days=self.cache_days):
            return None
        if status == 200:
            return json.loads(body)
        return None

    def get(self, path: str, **params: Any) -> Any:
        params = {key: value for key, value in params.items() if value is not None}
        key = self._cache_key(path, params)
        cached = self._cached(key)
        if cached is not None:
            return cached
        request_params = dict(params)
        if self.api_key:
            request_params["api_key"] = self.api_key
        query = urllib.parse.urlencode(request_params, doseq=True)
        url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
        headers = {
            "Accept": "application/json",
            "User-Agent": "neutral-atom-literature-graph/0.1",
        }
        if self.email:
            headers["User-Agent"] += f" (mailto:{self.email})"

        for attempt in range(self.max_retries + 1):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self.request_delay:
                time.sleep(self.request_delay - elapsed)
            try:
                self._last_request = time.monotonic()
                with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=60
                ) as response:
                    body = response.read().decode("utf-8")
                    status = int(response.status)
                self.db.cache_put(key, "openalex", status, body)
                if status != 200:
                    raise OpenAlexError(f"OpenAlex HTTP {status}")
                return json.loads(body)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                self.db.cache_put(key, "openalex", int(exc.code), body)
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt >= self.max_retries:
                    raise OpenAlexError(
                        f"OpenAlex HTTP {exc.code}: {body[:300]}"
                    ) from exc
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else min(2**attempt, 30)
                time.sleep(min(delay, 60))
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt >= self.max_retries:
                    raise OpenAlexError(f"OpenAlex request failed: {exc}") from exc
                time.sleep(min(2**attempt, 30))
        raise AssertionError("unreachable")

    def works_by_dois(self, dois: list[str]) -> list[dict[str, Any]]:
        normalized = [normalize_doi(doi) for doi in dois]
        values = [f"https://doi.org/{doi}" for doi in normalized if doi]
        if not values:
            return []
        response = self.get(
            "/works",
            include_xpac="true",
            filter=f"doi:{'|'.join(values)}",
            per_page=min(len(values), 100),
            select=WORK_FIELDS,
        )
        return list(response.get("results", []))

    def works_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        values = [value for item in ids if (value := short_openalex_id(item))]
        if not values:
            return []
        response = self.get(
            "/works",
            include_xpac="true",
            filter=f"openalex_id:{'|'.join(values)}",
            per_page=min(len(values), 100),
            select=WORK_FIELDS,
        )
        return list(response.get("results", []))

    def work(self, openalex_id: str) -> dict[str, Any]:
        work_id = short_openalex_id(openalex_id)
        if not work_id:
            raise ValueError(f"invalid OpenAlex work id: {openalex_id}")
        return self.get(f"/works/{work_id}", select=WORK_FIELDS)

    def search_work(
        self, title: str, year: int | None, *, per_page: int = 5
    ) -> list[dict[str, Any]]:
        # Submit literal title words, not OpenAlex/Lucene query syntax.
        query = " ".join(re.sub(r"[\W_]+", " ", title).casefold().split())
        params: dict[str, Any] = {
            "search": query,
            "per_page": per_page,
            "select": WORK_FIELDS,
        }
        if year:
            params["filter"] = f"publication_year:{year - 1}-{year + 1}"
        response = self.get("/works", **params)
        return list(response.get("results", []))
