from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from neutral_atom_graph.bibtex import parse_bibtex
from neutral_atom_graph.classification import (
    extract_review_mentions,
    load_taxonomy,
    sync_review_mentions,
)
from neutral_atom_graph.db import LiteratureDB, utc_now
from neutral_atom_graph.export import export_graph
from neutral_atom_graph.facets import classify_facets


def _write_taxonomy(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "field_weights": {
                    "title": 0.8,
                    "review_context": 0.9,
                    "topics": 0.6,
                },
                "dimensions": [
                    {
                        "id": "atomic_species",
                        "label_en": "Atomic species",
                        "label_zh": "原子元素",
                        "description_en": "Species explicitly mentioned.",
                        "categories": [
                            {
                                "id": "rubidium",
                                "label_en": "Rubidium",
                                "label_zh": "铷",
                                "rules": [
                                    {
                                        "id": "species.rubidium",
                                        "fields": [
                                            "title",
                                            "topics",
                                            "review_context",
                                        ],
                                        "keywords": ["rubidium"],
                                        "confidence": 0.99,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class ReviewMentionTests(unittest.TestCase):
    def test_include_inherits_heading_and_ignores_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "main.tex").write_text(
                "\\section{Hardware}\n\\input{child}\n"
                "% ignored \\cite{ghost}\n",
                encoding="utf-8",
            )
            (root / "child.tex").write_text(
                "\\subsection{Arrays}\nRubidium arrays~\\cite{paper}.\n",
                encoding="utf-8",
            )
            mentions = extract_review_mentions(root, review_id="review:test")
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0]["bib_key"], "paper")
        self.assertEqual(mentions[0]["section_path"], ["Hardware", "Arrays"])
        self.assertEqual(mentions[0]["source_file"], "child.tex")


class ClassificationPipelineTests(unittest.TestCase):
    def test_rule_derived_facets_cache_backfill_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            taxonomy_path = root / "taxonomy.json"
            _write_taxonomy(taxonomy_path)
            tex = root / "tex"
            tex.mkdir()
            (tex / "main.tex").write_text(
                "\\section{Neutral Atom Quantum Processor Hardware}\n"
                "\\input{hardware}\n",
                encoding="utf-8",
            )
            (tex / "hardware.tex").write_text(
                "\\subsection{Qubit encoding}\n"
                "Rubidium arrays are controlled optically~\\cite{rbpaper}.\n",
                encoding="utf-8",
            )

            out = root / "out"
            with LiteratureDB(root / "test.sqlite") as db:
                db.ingest_bib_entries(
                    parse_bibtex(
                        """
                        @article{rbpaper,
                          title={Neutral atom processor},
                          journal={Physical Review Letters},
                          doi={10.1234/rb}
                        }
                        """
                    ),
                    {"rbpaper": ["main.tex"]},
                )
                work_id = int(
                    db.conn.execute(
                        "SELECT work_id FROM seed_entries WHERE bib_key='rbpaper'"
                    ).fetchone()[0]
                )
                db.upsert_work(
                    {"openalex_id": "W123"},
                    [("doi", "10.1234/rb"), ("openalex", "W123")],
                    preferred_work_id=work_id,
                )
                db.save_provider_record(
                    "openalex",
                    "W123",
                    {
                        "topics": [
                            {
                                "id": "https://openalex.org/T42",
                                "display_name": "Neutral Atom Quantum Computing",
                                "score": 0.99,
                                "field": {
                                    "display_name": "Physics",
                                },
                            }
                        ],
                        "primary_topic": {
                            "id": "https://openalex.org/T42",
                            "display_name": "Neutral Atom Quantum Computing",
                        },
                    },
                )
                db.conn.commit()

                mention_stats = sync_review_mentions(
                    db, tex, review_id="review:test"
                )
                taxonomy = load_taxonomy(taxonomy_path)
                first = classify_facets(db, taxonomy)
                self.assertEqual(mention_stats["resolved"], 1)
                self.assertEqual(first["cached_openalex_topics"]["updated"], 1)

                topics = json.loads(
                    db.conn.execute(
                        "SELECT topics_json FROM works WHERE work_id=?", (work_id,)
                    ).fetchone()[0]
                )
                self.assertEqual(topics[0]["id"], "T42")
                self.assertEqual(topics[0]["field"], "Physics")

                rule_row = db.conn.execute(
                    """
                    SELECT confidence,evidence_json
                    FROM work_classifications
                    WHERE work_id=? AND dimension_id='atomic_species'
                      AND category_id='rubidium'
                      AND method='deterministic_rule'
                    """,
                    (work_id,),
                ).fetchone()
                self.assertIsNotNone(rule_row)
                self.assertEqual(rule_row["confidence"], 0.9)
                self.assertIn("review_context", rule_row["evidence_json"])

                dimensions = {
                    row["dimension_id"]
                    for row in db.conn.execute(
                        "SELECT dimension_id FROM work_classifications"
                    )
                }
                self.assertTrue(
                    {"atomic_species", "review_section", "review_topic", "venue"}
                    <= dimensions
                )

                db.conn.execute(
                    """
                    INSERT INTO work_classifications(
                      work_id,taxonomy_version,taxonomy_digest,dimension_id,
                      category_id,method,confidence,evidence_json,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        work_id,
                        taxonomy.version,
                        taxonomy.digest,
                        "curation",
                        "verified",
                        "manual",
                        1.0,
                        "{}",
                        utc_now(),
                        utc_now(),
                    ),
                )
                db.conn.commit()
                classify_facets(db, taxonomy)
                self.assertEqual(
                    db.conn.execute(
                        """
                        SELECT COUNT(*) FROM work_classifications
                        WHERE method='manual'
                        """
                    ).fetchone()[0],
                    1,
                )

                report = export_graph(db, out)
                self.assertEqual(report["graph"]["classified_work_count"], 1)
                self.assertGreaterEqual(report["graph"]["tag_count"], 4)

            graph = json.loads((out / "graph.json").read_text(encoding="utf-8"))
            self.assertEqual(graph["taxonomy"]["version"], "test-v1")
            node = graph["nodes"][0]
            self.assertEqual(node["facets"]["atomic_species"], ["rubidium"])
            self.assertIn("review_section", node["facets"])
            evidence_text = json.dumps(
                node["classification_evidence"], ensure_ascii=False
            )
            self.assertIn("hardware.tex", evidence_text)
            self.assertNotIn("Rubidium arrays are controlled optically", evidence_text)


if __name__ == "__main__":
    unittest.main()
