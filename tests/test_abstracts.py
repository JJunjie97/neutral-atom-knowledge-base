from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neutral_atom_graph.db import LiteratureDB
from neutral_atom_graph.pipeline import (
    _abstract,
    fetch_openalex_abstracts,
    upsert_openalex_payload,
)


class OpenAlexAbstractTests(unittest.TestCase):
    def test_reconstructs_inverted_abstract_in_word_order(self) -> None:
        payload = {
            "abstract_inverted_index": {
                "atoms": [2],
                "Neutral": [0],
                "enable": [3],
                "quantum": [1, 4],
                "computing.": [5],
            }
        }
        self.assertEqual(
            _abstract(payload),
            "Neutral quantum atoms enable quantum computing.",
        )

    def test_openalex_upsert_persists_abstract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                work_id = upsert_openalex_payload(
                    db,
                    {
                        "id": "https://openalex.org/W42",
                        "title": "Neutral atoms",
                        "abstract_inverted_index": {
                            "A": [0],
                            "short": [1],
                            "abstract.": [2],
                        },
                    },
                )
                row = db.conn.execute(
                    "SELECT abstract FROM works WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["abstract"], "A short abstract.")


    def test_backfill_records_abstract_and_skips_empty_on_resume(self) -> None:
        class FakeClient:
            refresh = False

            def works_by_ids(self, ids: list[str]) -> list[dict]:
                payloads = {
                    "W1": {
                        "id": "https://openalex.org/W1",
                        "abstract_inverted_index": {"Stored.": [0]},
                    },
                    "W2": {
                        "id": "https://openalex.org/W2",
                        "abstract_inverted_index": None,
                    },
                }
                return [payloads[item] for item in ids]

        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                for openalex_id in ("W1", "W2"):
                    db.upsert_work(
                        {"openalex_id": openalex_id},
                        [("openalex", openalex_id)],
                    )
                db.conn.commit()
                result = fetch_openalex_abstracts(db, FakeClient())
                self.assertEqual(result["fetched"], 1)
                self.assertEqual(result["without_abstract"], 1)
                self.assertEqual(db.pending_abstract_metadata("openalex"), [])

if __name__ == "__main__":
    unittest.main()
