from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from neutral_atom_graph.bibtex import parse_bibtex
from neutral_atom_graph.db import LiteratureDB
from neutral_atom_graph.export import export_graph


class DatabaseTests(unittest.TestCase):
    def test_identifier_merge_preserves_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "test.sqlite"
            with LiteratureDB(db_path) as db:
                entries = parse_bibtex(
                    """
                    @article{seed, title={Seed}, year={2024},
                      doi={10.1234/seed}}
                    @article{cited, title={Cited}, year={2020},
                      doi={10.1234/cited}}
                    """
                )
                db.ingest_bib_entries(entries, {"seed": ["main.tex"]})
                seed = db.conn.execute(
                    "SELECT work_id FROM seed_entries WHERE bib_key='seed'"
                ).fetchone()[0]
                placeholder = db.upsert_work(
                    {"openalex_id": "W42"}, [("openalex", "W42")]
                )
                db.add_citation(seed, placeholder, "openalex")
                db.upsert_work(
                    {
                        "title": "Cited",
                        "doi": "10.1234/cited",
                        "openalex_id": "W42",
                    },
                    [("doi", "10.1234/cited"), ("openalex", "W42")],
                    preferred_work_id=placeholder,
                )
                db.conn.commit()
                self.assertEqual(db.stats()["works"], 2)
                self.assertEqual(db.stats()["citation_edges"], 1)

    def test_export_seed_subgraph(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with LiteratureDB(root / "test.sqlite") as db:
                entries = parse_bibtex(
                    """
                    @article{a, title={A}, year={2024}, doi={10.1234/a}}
                    @article{b, title={B}, year={2020}, doi={10.1234/b}}
                    """
                )
                db.ingest_bib_entries(entries, {"a": ["main.tex"], "b": ["main.tex"]})
                ids = {
                    row["bib_key"]: row["work_id"]
                    for row in db.conn.execute("SELECT bib_key,work_id FROM seed_entries")
                }
                db.add_citation(ids["a"], ids["b"], "test")
                db.conn.commit()
                report = export_graph(db, root / "out")
            graph = json.loads((root / "out" / "seed_graph.json").read_text("utf-8"))
            self.assertEqual(report["graph"]["seed_to_seed_edge_count"], 1)
            self.assertEqual(len(graph["nodes"]), 2)
            self.assertEqual(len(graph["edges"]), 1)


if __name__ == "__main__":
    unittest.main()
