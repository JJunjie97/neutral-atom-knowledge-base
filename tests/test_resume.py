from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neutral_atom_graph.db import LiteratureDB


class ResumeTests(unittest.TestCase):
    def test_not_found_metadata_is_only_retried_on_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                source = db.upsert_work(
                    {"title": "Source", "openalex_id": "W1"},
                    [("openalex", "W1")],
                    is_seed=True,
                )
                target = db.upsert_work(
                    {"openalex_id": "W2"}, [("openalex", "W2")]
                )
                db.add_citation(source, target, "openalex")
                self.assertEqual(len(db.pending_reference_metadata("openalex")), 1)
                db.mark_fetch(
                    "openalex", target, "metadata", "not_found", "dangling id"
                )
                self.assertEqual(len(db.pending_reference_metadata("openalex")), 0)
                self.assertEqual(
                    len(
                        db.pending_reference_metadata(
                            "openalex", include_not_found=True
                        )
                    ),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
