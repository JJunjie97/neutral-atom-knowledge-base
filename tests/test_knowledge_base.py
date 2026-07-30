from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from neutral_atom_graph.bibtex import parse_bibtex
from neutral_atom_graph.crossref import (
    crossref_work_data,
    repair_missing_doi_metadata,
)
from neutral_atom_graph.db import LiteratureDB
from neutral_atom_graph.export import export_graph
from neutral_atom_graph.library import (
    index_markdown,
    search_library,
    split_markdown,
    sync_library,
)
from neutral_atom_graph.knowledge import (
    build_catalog,
    citation_neighbors,
    get_work,
)
from neutral_atom_graph.pipeline import repair_openalex_doi_titles


class PaperIdentityTests(unittest.TestCase):
    def test_paper_uid_survives_metadata_and_canonical_id_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "literature.sqlite"
            with LiteratureDB(path) as db:
                work_id = db.upsert_work(
                    {"openalex_id": "W42"},
                    [("openalex", "W42")],
                )
                original_uid = db.paper_uid(work_id)
                db.upsert_work(
                    {
                        "title": "A neutral-atom result",
                        "title_source": "openalex",
                        "metadata_status": "complete",
                        "doi": "10.1234/neutral.42",
                    },
                    [("openalex", "W42"), ("doi", "10.1234/neutral.42")],
                    preferred_work_id=work_id,
                )
                db.conn.commit()
                row = db.conn.execute(
                    "SELECT paper_uid,canonical_id FROM works WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["paper_uid"], original_uid)
                self.assertEqual(row["canonical_id"], "doi:10.1234/neutral.42")

            with LiteratureDB(path) as reopened:
                row = reopened.conn.execute(
                    "SELECT paper_uid FROM works WHERE work_id=?",
                    (work_id,),
                ).fetchone()
                self.assertEqual(row["paper_uid"], original_uid)

    def test_legacy_schema_migration_assigns_uid_and_classifies_private_note(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.sqlite"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE works (
                    work_id INTEGER PRIMARY KEY,
                    canonical_id TEXT NOT NULL UNIQUE,
                    title TEXT,
                    openalex_id TEXT
                );
                CREATE TABLE seed_entries (
                    bib_key TEXT PRIMARY KEY,
                    work_id INTEGER NOT NULL,
                    entry_type TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    cited_in_json TEXT NOT NULL DEFAULT '[]'
                );
                INSERT INTO works(work_id,canonical_id,title,openalex_id)
                VALUES
                  (7,'bib:private-note',NULL,NULL),
                  (11,'openalex:W11',NULL,'W11');
                INSERT INTO seed_entries(
                    bib_key,work_id,entry_type,raw_json,cited_in_json
                ) VALUES(
                    'private-note',7,'misc',
                    '{"note":"N. Maskara, private communication"}','[]'
                );
                """
            )
            connection.commit()
            connection.close()

            with LiteratureDB(path) as db:
                rows = db.conn.execute(
                    """
                    SELECT work_id,paper_uid,metadata_status,entity_kind
                    FROM works ORDER BY work_id
                    """
                ).fetchall()
                self.assertEqual(
                    [row["paper_uid"] for row in rows],
                    ["paper-00000007", "paper-00000011"],
                )
                self.assertEqual(rows[0]["entity_kind"], "private_communication")
                self.assertEqual(rows[0]["metadata_status"], "non_bibliographic")
                self.assertEqual(rows[1]["metadata_status"], "unresolved_reference")

            with LiteratureDB(path) as reopened:
                self.assertEqual(
                    reopened.conn.execute(
                        "SELECT COUNT(DISTINCT paper_uid) FROM works"
                    ).fetchone()[0],
                    2,
                )

    def test_new_private_communication_is_not_treated_as_a_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                db.ingest_bib_entries(
                    parse_bibtex(
                        """
                        @misc{private,
                          note={N. Maskara, private communication}
                        }
                        """
                    ),
                    {},
                )
                row = db.conn.execute(
                    """
                    SELECT w.metadata_status,w.entity_kind
                    FROM works w
                    JOIN seed_entries s ON s.work_id=w.work_id
                    WHERE s.bib_key='private'
                    """
                ).fetchone()
                self.assertEqual(row["entity_kind"], "private_communication")
                self.assertEqual(row["metadata_status"], "non_bibliographic")


class LibraryIndexTests(unittest.TestCase):
    @staticmethod
    def _create_library(repo: Path) -> tuple[Path, Path]:
        library = repo / "library"
        paper = library / "papers" / "doi" / "10.1234" / "neutral"
        (paper / "original").mkdir(parents=True)
        (paper / "markdown").mkdir()
        (paper / "original" / "paper.pdf").write_bytes(b"%PDF-test")
        markdown = paper / "markdown" / "paper.md"
        markdown.write_text(
            """
            # Introduction

            Rydberg blockade enables neutral atom quantum gates.

            ## Decoder

            The decoder uses erasure information from atom loss.
            """,
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "title": "Neutral-atom test paper",
            "year": 2026,
            "language": "en",
            "identifiers": {"doi": "10.1234/neutral"},
            "documents": [
                {
                    "kind": "pdf",
                    "path": "original/paper.pdf",
                    "media_type": "application/pdf",
                    "redistributable": False,
                },
                {
                    "kind": "markdown",
                    "path": "markdown/paper.md",
                    "media_type": "text/markdown",
                    "redistributable": True,
                },
                {
                    "kind": "source",
                    "path": "source/main.tex",
                    "media_type": "application/x-tex",
                    "planned": True,
                },
            ],
        }
        (paper / "paper.json").write_text(
            json.dumps(manifest, ensure_ascii=False),
            encoding="utf-8",
        )
        return library, markdown

    def test_manifest_sync_is_idempotent_and_tracks_file_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            library, _ = self._create_library(repo)
            with LiteratureDB(repo / "literature.sqlite") as db:
                first = sync_library(db, library)
                second = sync_library(db, library)
                rows = db.conn.execute(
                    """
                    SELECT kind,status,sha256,byte_size,relative_path
                    FROM documents ORDER BY kind
                    """
                ).fetchall()
                work = db.conn.execute(
                    """
                    SELECT paper_uid,title,title_source,metadata_status
                    FROM works
                    """
                ).fetchone()

                self.assertEqual(first["documents"], 3)
                self.assertEqual(first["available"], 2)
                self.assertEqual(first["planned"], 1)
                self.assertEqual(second, first)
                self.assertEqual(len(rows), 3)
                pdf = next(row for row in rows if row["kind"] == "pdf")
                self.assertEqual(len(pdf["sha256"]), 64)
                self.assertEqual(pdf["byte_size"], 9)
                self.assertTrue(pdf["relative_path"].startswith("library/papers/"))
                self.assertRegex(work["paper_uid"], r"^paper-\d{8}$")
                self.assertEqual(work["title_source"], "library_manifest")
                self.assertEqual(work["metadata_status"], "complete")

    def test_markdown_chunking_and_fts_reindex(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            library, markdown = self._create_library(repo)
            with LiteratureDB(repo / "literature.sqlite") as db:
                sync_library(db, library)
                indexed = index_markdown(db, library)
                results = search_library(db, "Rydberg")

                self.assertEqual(indexed["documents"], 1)
                self.assertEqual(indexed["chunks"], 2)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["heading"], "Introduction")
                self.assertEqual(results[0]["title"], "Neutral-atom test paper")
                self.assertRegex(results[0]["paper_uid"], r"^paper-\d{8}$")

                markdown.write_text(
                    "# Revised\n\nLogical qubits use transversal gates.",
                    encoding="utf-8",
                )
                index_markdown(db, library)
                self.assertEqual(search_library(db, "Rydberg"), [])
                revised = search_library(db, "transversal")
                self.assertEqual(len(revised), 1)
                self.assertEqual(revised[0]["heading"], "Revised")
                self.assertEqual(db.stats()["document_chunks"], 1)

    def test_split_markdown_respects_headings_and_size_bound(self) -> None:
        chunks = split_markdown(
            "# One\n\nalpha beta gamma delta\n\n# Two\n\nepsilon zeta",
            max_chars=12,
        )
        self.assertEqual(chunks[0]["heading"], "One")
        self.assertEqual(chunks[-1]["heading"], "Two")
        self.assertTrue(all(len(chunk["content"]) <= 12 for chunk in chunks))


class MetadataRepairTests(unittest.TestCase):
    def test_crossref_payload_is_normalized_without_html(self) -> None:
        data = crossref_work_data(
            {
                "title": ["Neutral Atom Computing"],
                "container-title": ["Physical Review A"],
                "published-online": {"date-parts": [[2025, 3, 4]]},
                "type": "journal-article",
                "abstract": "<jats:p>Rydberg &amp; cavity gates.</jats:p>",
                "URL": "https://doi.org/10.1234/test",
                "author": [
                    {"given": "Ada", "family": "Lovelace"},
                    {"family": "Einstein"},
                ],
                "is-referenced-by-count": 12,
                "reference": [{"key": "a"}, {"key": "b"}],
            }
        )
        self.assertEqual(data["title"], "Neutral Atom Computing")
        self.assertEqual(data["title_source"], "crossref")
        self.assertEqual(data["metadata_status"], "complete")
        self.assertEqual(data["year"], 2025)
        self.assertEqual(data["venue"], "Physical Review A")
        self.assertEqual(data["abstract"], "Rydberg & cavity gates.")
        self.assertEqual(data["authors_json"], ["Ada Lovelace", "Einstein"])
        self.assertEqual(data["citation_count"], 12)
        self.assertEqual(data["reference_count"], 2)

    def test_crossref_repair_recovers_title_and_records_provenance(self) -> None:
        class FakeCrossref:
            def work(self, doi: str) -> dict:
                self.requested = doi
                return {
                    "title": ["Recovered title"],
                    "issued": {"date-parts": [[2024]]},
                }

        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                work_id = db.upsert_work(
                    {"doi": "10.1234/missing"},
                    [("doi", "10.1234/missing")],
                )
                client = FakeCrossref()
                result = repair_missing_doi_metadata(db, client)
                row = db.conn.execute(
                    """
                    SELECT title,title_source,metadata_status
                    FROM works WHERE work_id=?
                    """,
                    (work_id,),
                ).fetchone()
                status = db.conn.execute(
                    """
                    SELECT status FROM fetch_status
                    WHERE provider='crossref' AND work_id=? AND operation='metadata'
                    """,
                    (work_id,),
                ).fetchone()

                self.assertEqual(result["recovered"], 1)
                self.assertEqual(client.requested, "10.1234/missing")
                self.assertEqual(row["title"], "Recovered title")
                self.assertEqual(row["title_source"], "crossref")
                self.assertEqual(row["metadata_status"], "complete")
                self.assertEqual(status["status"], "done")
                self.assertEqual(
                    db.conn.execute(
                        """
                        SELECT COUNT(*) FROM provider_records
                        WHERE provider='crossref' AND provider_id='10.1234/missing'
                        """
                    ).fetchone()[0],
                    1,
                )

    def test_openalex_doi_repair_keeps_alias_and_promotes_titled_record(
        self,
    ) -> None:
        class FakeOpenAlex:
            def works_by_dois(self, dois: list[str]) -> list[dict]:
                self.requested = dois
                return [
                    {
                        "id": "https://openalex.org/W222",
                        "doi": "https://doi.org/10.1234/alias",
                        "title": "Resolved through exact DOI",
                        "publication_year": 2023,
                    }
                ]

        with tempfile.TemporaryDirectory() as temp:
            with LiteratureDB(Path(temp) / "test.sqlite") as db:
                work_id = db.upsert_work(
                    {
                        "doi": "10.1234/alias",
                        "openalex_id": "W111",
                        "metadata_status": "unresolved_reference",
                    },
                    [("doi", "10.1234/alias"), ("openalex", "W111")],
                )
                db.conn.commit()
                uid = db.paper_uid(work_id)
                client = FakeOpenAlex()
                result = repair_openalex_doi_titles(db, client)
                row = db.conn.execute(
                    """
                    SELECT paper_uid,title,title_source,metadata_status,openalex_id
                    FROM works WHERE work_id=?
                    """,
                    (work_id,),
                ).fetchone()
                aliases = {
                    alias["value"]
                    for alias in db.conn.execute(
                        """
                        SELECT value FROM identifiers
                        WHERE work_id=? AND scheme='openalex'
                        """,
                        (work_id,),
                    )
                }

                self.assertEqual(result["requested"], 1)
                self.assertEqual(result["recovered"], 1)
                self.assertEqual(client.requested, ["10.1234/alias"])
                self.assertEqual(row["paper_uid"], uid)
                self.assertEqual(row["title"], "Resolved through exact DOI")
                self.assertEqual(row["title_source"], "openalex_doi")
                self.assertEqual(row["metadata_status"], "complete")
                self.assertEqual(row["openalex_id"], "W222")
                self.assertEqual(aliases, {"W111", "W222"})


class ExportContractTests(unittest.TestCase):
    def test_graph_json_contains_stable_identity_and_metadata_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with LiteratureDB(root / "literature.sqlite") as db:
                db.ingest_bib_entries(
                    parse_bibtex(
                        """
                        @article{seed,
                          title={A Seed Work},
                          year={2026},
                          doi={10.1234/seed}
                        }
                        """
                    ),
                    {"seed": ["main.tex"]},
                )
                export_graph(db, root / "export")

            graph = json.loads(
                (root / "export" / "graph.json").read_text(encoding="utf-8")
            )
            node = graph["nodes"][0]
            self.assertRegex(node["paper_uid"], r"^paper-\d{8}$")
            self.assertEqual(node["title_source"], "bibtex")
            self.assertEqual(node["metadata_status"], "complete")
            self.assertEqual(node["entity_kind"], "scholarly_work")


class AIQueryContractTests(unittest.TestCase):
    def test_catalog_and_identifier_queries_use_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with LiteratureDB(root / "literature.sqlite") as db:
                source = db.upsert_work(
                    {
                        "title": "Neutral atom source",
                        "metadata_status": "complete",
                        "doi": "10.1234/source",
                    },
                    [("doi", "10.1234/source")],
                    is_seed=True,
                )
                target = db.upsert_work(
                    {
                        "openalex_id": "W404",
                        "metadata_status": "unresolved_reference",
                    },
                    [("openalex", "W404")],
                )
                db.add_citation(source, target, "test")
                db.conn.commit()

                paper = get_work(db, "https://doi.org/10.1234/source")
                neighbors = citation_neighbors(
                    db, paper["paper_uid"], direction="outgoing"
                )
                report = build_catalog(db, root / "catalog")

            self.assertEqual(paper["title"], "Neutral atom source")
            self.assertEqual(neighbors["count"], 1)
            self.assertEqual(
                neighbors["neighbors"][0]["paper"]["display_title"],
                "Metadata unavailable - OpenAlex W404",
            )
            self.assertEqual(report["works"], 2)
            self.assertEqual(report["missing_titles"], 1)
            self.assertTrue((root / "catalog" / "papers.jsonl").is_file())
            self.assertTrue((root / "catalog" / "papers.csv").is_file())
            self.assertIn(
                paper["paper_uid"],
                (root / "catalog" / "seed-catalog.md").read_text(
                    encoding="utf-8"
                ),
            )


if __name__ == "__main__":
    unittest.main()
