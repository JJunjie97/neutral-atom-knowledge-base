from __future__ import annotations

import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from neutral_atom_graph.admin_server import AdminService, create_admin_server
from neutral_atom_graph.db import LiteratureDB, utc_now


class AdminServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "literature.sqlite"
        with LiteratureDB(self.db_path) as db:
            self.work_id = db.upsert_work(
                {
                    "title": "Old neutral-atom paper",
                    "title_source": "openalex",
                    "metadata_status": "complete",
                    "year": 2020,
                    "authors_json": ["Alice"],
                    "doi": "10.1000/admin-test",
                },
                [("doi", "10.1000/admin-test")],
                is_seed=True,
            )
            taxonomy = {
                "version": "test-v1",
                "dimensions": [
                    {
                        "id": "atomic_species",
                        "label_en": "Atomic species",
                        "label_zh": "Atomic species",
                        "categories": [
                            {
                                "id": "rubidium",
                                "label_en": "Rubidium",
                                "label_zh": "Rubidium",
                            }
                        ],
                    }
                ],
            }
            now = utc_now()
            db.conn.execute(
                """
                INSERT INTO taxonomy_definitions(
                  taxonomy_version,taxonomy_digest,definition_json,created_at,updated_at
                ) VALUES(?,?,?,?,?)
                """,
                ("test-v1", "digest-v1", json.dumps(taxonomy), now, now),
            )
            db.conn.commit()
        self.service = AdminService(
            self.db_path,
            token="test-token",
            backup_dir=self.root / "backups",
        )
        self.server = create_admin_server(self.service, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.cleanup()

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        token: bool = True,
        origin: str | None = "http://localhost:3000",
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = "Bearer test-token"
        if origin:
            headers["Origin"] = origin
        raw_body = None
        if body is not None:
            raw_body = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(raw_body))
        if extra_headers:
            headers.update(extra_headers)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=raw_body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        result_headers = {key.lower(): value for key, value in response.getheaders()}
        conn.close()
        return response.status, payload, result_headers

    def test_loopback_auth_cors_and_paged_list(self) -> None:
        status, payload, headers = self.request(
            "GET", "/api/health", token=False
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(headers["access-control-allow-origin"], "http://localhost:3000")

        status, payload, _ = self.request(
            "GET", "/api/admin/summary", token=False
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "unauthorized")

        status, payload, _ = self.request(
            "GET",
            "/api/admin/summary",
            extra_headers={"Authorization": "Bearer \u00e9"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "unauthorized")

        status, payload, _ = self.request(
            "GET", "/api/health", token=False, origin="https://example.com"
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "cors_denied")

        status, _, headers = self.request(
            "OPTIONS",
            "/api/works",
            token=False,
            extra_headers={
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        self.assertEqual(status, 204)
        self.assertIn("Authorization", headers["access-control-allow-headers"])

        status, payload, _ = self.request(
            "GET", "/api/works?q=admin-test&limit=10&offset=0"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["work_id"], self.work_id)
        self.assertEqual(payload["items"][0]["authors"], ["Alice"])
        self.assertNotIn("admin_version", payload["items"][0])

        status, payload, _ = self.request(
            "GET", "/api/works?q=Alice&limit=10&offset=0"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)

        with self.assertRaisesRegex(ValueError, "loopback"):
            create_admin_server(self.service, "0.0.0.0", 0)

        with self.assertRaises(FileNotFoundError):
            AdminService(self.root / "missing.sqlite", token="test-token")
        with self.assertRaisesRegex(ValueError, "origin"):
            AdminService(
                self.db_path,
                token="test-token",
                allowed_origins=("http://localhost:3000/path",),
            )

    def test_metadata_patch_creates_one_backup_audit_and_conflict(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute("DROP INDEX IF EXISTS idx_admin_audit_entity")
            conn.execute("DROP TABLE IF EXISTS admin_audit_log")
            conn.commit()
        status, detail, _ = self.request("GET", f"/api/works/{self.work_id}")
        self.assertEqual(status, 200)
        old_version = detail["work"]["admin_version"]
        changes = {
            "title": "Curated neutral-atom paper",
            "abstract": "A manually reviewed abstract.",
            "year": 2024,
            "publication_date": "2024-05-06",
            "authors": ["Alice", "Bob"],
            "venue": "Test Journal",
            "work_type": "article",
            "url": "https://example.org/paper",
            "oa_url": None,
            "metadata_status": "complete",
        }
        status, updated, _ = self.request(
            "PATCH",
            f"/api/works/{self.work_id}",
            {"changes": changes, "expected_updated_at": old_version},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["work"]["title"], "Curated neutral-atom paper")
        self.assertEqual(updated["work"]["title_source"], "manual")
        self.assertEqual(updated["work"]["authors"], ["Alice", "Bob"])
        self.assertNotEqual(updated["work"]["admin_version"], old_version)
        backups = list((self.root / "backups").glob("*.sqlite"))
        self.assertEqual(len(backups), 1)
        with closing(
            sqlite3.connect(f"file:{backups[0].as_posix()}?mode=ro", uri=True)
        ) as backup:
            title = backup.execute(
                "SELECT title FROM works WHERE work_id=?", (self.work_id,)
            ).fetchone()[0]
            self.assertEqual(title, "Old neutral-atom paper")

        status, payload, _ = self.request(
            "PATCH",
            f"/api/works/{self.work_id}",
            {"changes": {"title": "Stale overwrite"}, "expected_updated_at": old_version},
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "version_conflict")
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite"))), 1)
        with LiteratureDB(self.db_path) as db:
            audits = db.conn.execute(
                "SELECT action,changes_json FROM admin_audit_log ORDER BY audit_id"
            ).fetchall()
        self.assertEqual([row["action"] for row in audits], ["work.patch"])
        self.assertNotIn("test-token", audits[0]["changes_json"])

    def test_admin_startup_does_not_reclassify_incomplete_records(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE works SET metadata_status='incomplete' WHERE work_id=?",
                (self.work_id,),
            )
            conn.commit()
        second = AdminService(
            self.db_path,
            token="second-token",
            backup_dir=self.root / "second-backups",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            status = conn.execute(
                "SELECT metadata_status FROM works WHERE work_id=?", (self.work_id,)
            ).fetchone()[0]
        self.assertEqual(status, "incomplete")
        self.assertIsNone(second.backup_path)
        self.assertFalse((self.root / "second-backups").exists())

    def test_row_digest_detects_same_timestamp_external_change(self) -> None:
        status, detail, _ = self.request("GET", f"/api/works/{self.work_id}")
        self.assertEqual(status, 200)
        version = detail["work"]["admin_version"]
        original_timestamp = detail["work"]["updated_at"]
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.execute(
                "UPDATE works SET venue=?,updated_at=? WHERE work_id=?",
                ("External update", original_timestamp, self.work_id),
            )
            conn.commit()
        status, payload, _ = self.request(
            "PATCH",
            f"/api/works/{self.work_id}",
            {
                "changes": {"abstract": "Would overwrite a stale form"},
                "expected_updated_at": version,
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "version_conflict")
        self.assertIsNone(self.service.backup_path)
        self.assertFalse((self.root / "backups").exists())

    def test_noop_patch_does_not_create_backup_or_audit(self) -> None:
        status, detail, _ = self.request("GET", f"/api/works/{self.work_id}")
        self.assertEqual(status, 200)
        status, unchanged, _ = self.request(
            "PATCH",
            f"/api/works/{self.work_id}",
            {
                "changes": {"title": detail["work"]["title"]},
                "expected_updated_at": detail["work"]["admin_version"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(unchanged["work"]["admin_version"], detail["work"]["admin_version"])
        self.assertIsNone(self.service.backup_path)
        with LiteratureDB(self.db_path) as db:
            count = db.conn.execute("SELECT COUNT(*) FROM admin_audit_log").fetchone()[0]
        self.assertEqual(count, 0)

    def test_invalid_date_is_rejected_before_backup(self) -> None:
        status, detail, _ = self.request("GET", f"/api/works/{self.work_id}")
        self.assertEqual(status, 200)
        status, payload, _ = self.request(
            "PATCH",
            f"/api/works/{self.work_id}",
            {
                "changes": {"publication_date": "2024-W01-1"},
                "expected_updated_at": detail["work"]["admin_version"],
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("YYYY-MM-DD", payload["message"])
        self.assertIsNone(self.service.backup_path)

    def test_manual_entity_kind_override_survives_database_reopen(self) -> None:
        with LiteratureDB(self.db_path) as db:
            db.conn.execute(
                """
                INSERT OR REPLACE INTO seed_entries(
                  bib_key,work_id,entry_type,raw_json,cited_in_json
                ) VALUES(?,?,?,?,?)
                """,
                (
                    "private-note",
                    self.work_id,
                    "misc",
                    json.dumps({"note": "private communication"}),
                    "[]",
                ),
            )
            db.conn.execute(
                """
                UPDATE works SET entity_kind='scholarly_work',metadata_status='complete'
                WHERE work_id=?
                """,
                (self.work_id,),
            )
            db.conn.commit()
        with LiteratureDB(self.db_path) as reopened:
            row = reopened.conn.execute(
                "SELECT entity_kind,metadata_status FROM works WHERE work_id=?",
                (self.work_id,),
            ).fetchone()
        self.assertEqual(row["entity_kind"], "scholarly_work")
        self.assertEqual(row["metadata_status"], "complete")

    def test_taxonomy_manual_classification_add_and_delete(self) -> None:
        status, taxonomy, _ = self.request("GET", "/api/admin/taxonomies")
        self.assertEqual(status, 200)
        self.assertEqual(taxonomy["current_version"], "test-v1")
        status, detail, _ = self.request("GET", f"/api/works/{self.work_id}")
        version = detail["work"]["admin_version"]
        status, detail, _ = self.request(
            "POST",
            f"/api/works/{self.work_id}/classifications",
            {
                "taxonomy_version": "test-v1",
                "dimension_id": "atomic_species",
                "category_id": "rubidium",
                "confidence": 0.95,
                "method": "manual",
                "expected_updated_at": version,
            },
        )
        self.assertEqual(status, 200)
        manual = [item for item in detail["classifications"] if item["method"] == "manual"]
        self.assertEqual(len(manual), 1)
        classification_id = manual[0]["classification_id"]
        version = detail["work"]["admin_version"]
        status, detail, _ = self.request(
            "DELETE",
            f"/api/works/{self.work_id}/classifications/{classification_id}",
            {"expected_updated_at": version},
        )
        self.assertEqual(status, 200)
        self.assertFalse([item for item in detail["classifications"] if item["method"] == "manual"])
        with LiteratureDB(self.db_path) as db:
            actions = [
                row[0]
                for row in db.conn.execute(
                    "SELECT action FROM admin_audit_log ORDER BY audit_id"
                )
            ]
        self.assertEqual(actions, ["classification.upsert", "classification.delete"])
        self.assertEqual(len(list((self.root / "backups").glob("*.sqlite"))), 1)


if __name__ == "__main__":
    unittest.main()
