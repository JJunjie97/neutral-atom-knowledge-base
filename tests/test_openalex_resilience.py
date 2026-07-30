from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neutral_atom_graph.bibtex import parse_bibtex
from neutral_atom_graph.db import LiteratureDB
from neutral_atom_graph.openalex import OpenAlexClient, OpenAlexError
from neutral_atom_graph.pipeline import resolve_openalex_seeds


class _FailingSearchClient:
    def works_by_dois(self, dois: list[str]) -> list[dict]:
        return []

    def search_work(self, title: str, year: int | None) -> list[dict]:
        raise OpenAlexError("HTTP 400 test error")


class OpenAlexResilienceTests(unittest.TestCase):
    def test_literal_title_search_removes_reserved_punctuation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                client = OpenAlexClient(db)
                captured: dict = {}

                def fake_get(path: str, **params: object) -> dict:
                    captured.update(params)
                    return {"results": []}

                client.get = fake_get  # type: ignore[method-assign]
                client.search_work("Can *TCOs* transform |Cavity-QED?", 2025)

        query = str(captured["search"])
        for reserved in "*|?":
            self.assertNotIn(reserved, query)
        self.assertEqual(query, "can tcos transform cavity qed")

    def test_one_bad_title_does_not_abort_remaining_crawl(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                db.ingest_bib_entries(
                    parse_bibtex(
                        "@article{bad, title={Can TCOs Transform Cavity-QED?}, "
                        "year={2025}}"
                    ),
                    {},
                )
                result = resolve_openalex_seeds(
                    db, _FailingSearchClient(), title_search=True
                )
                match = db.conn.execute(
                    "SELECT status FROM matches WHERE bib_key='bad'"
                ).fetchone()

        self.assertEqual(result["errors"], 1)
        self.assertEqual(match["status"], "error")


if __name__ == "__main__":
    unittest.main()
