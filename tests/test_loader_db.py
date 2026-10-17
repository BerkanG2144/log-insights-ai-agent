"""Opt-in SereneDB integration checks in a uniquely named, disposable schema."""

import csv
import os
import tempfile
import unittest
import uuid
from pathlib import Path, PurePosixPath
from unittest.mock import patch

import psycopg
from psycopg import sql

from loader import bgl, openstack
from loader.common import TABLE_COLUMNS, csv_value
from loader.db import ROOT, connect
from loader.load import copy_csv, create_indexes, execute_file, import_data
from loader.validate import validate
from test_loader import BGL, OPENSTACK


@unittest.skipUnless(os.getenv("LOADER_DB_TESTS") == "1", "Set LOADER_DB_TESTS=1 for the local SereneDB integration tests")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect()
        self.schema = "loader_test_" + uuid.uuid4().hex
        self.conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup_database)
        self.conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self.schema)))
        execute_file(self.conn, "schema.sql")
        processed = ROOT / "data/processed"
        processed.mkdir(parents=True, exist_ok=True)
        self.files = tempfile.TemporaryDirectory(prefix="integration-", dir=processed)
        self.addCleanup(self.files.cleanup)
        self.directory = Path(self.files.name)

    def cleanup_database(self):
        try:
            self.conn.execute("SET search_path TO public")
            self.conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))
        finally:
            self.conn.close()

    def fixture(self, table, rows):
        path = self.directory / (table + ".csv")
        columns = TABLE_COLUMNS[table]
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(columns)
            for row in rows:
                writer.writerow([csv_value(row[column]) for column in columns])
        return str(PurePosixPath("/data/processed") / self.directory.name / path.name)

    def test_csv_roundtrip_and_full_text_refresh(self):
        rows = [
            bgl.parse_line(BGL, 1),
            bgl.parse_line(BGL.replace("RAS", "NULL"), 2),
            bgl.parse_line(BGL.split(" INFO ")[0] + " FATAL", 3),
            bgl.parse_line(BGL.split(" INFO ")[0] + ' INFO quote "hello", literal \\N  ', 4),
        ]
        copy_csv(self.conn, "bgl_logs", self.fixture("bgl_logs", rows))
        result = self.conn.execute("SELECT line_no, raw_line, ts, message, is_alert FROM bgl_logs ORDER BY line_no").fetchall()
        self.assertEqual(result, [(r["line_no"], r["raw_line"], r["ts"], r["message"], r["is_alert"]) for r in rows])
        open_rows = [openstack.parse_line(OPENSTACK, 1, "normal1"),
                     openstack.parse_line(OPENSTACK.replace(" INFO ", " w "), 1, "normal2")]
        copy_csv(self.conn, "openstack_logs", self.fixture("openstack_logs", open_rows))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM openstack_logs").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT level, parse_status FROM openstack_logs WHERE source_file = 'normal2'").fetchone(), (None, "variant_level"))
        create_indexes(self.conn)
        result = self.conn.execute("SELECT line_no FROM bgl_logs_message_idx WHERE message @@ 'ERROR' ORDER BY line_no").fetchall()
        self.assertEqual(result, [(1,), (2,)])
        score = self.conn.execute("SELECT BM25(bgl_logs_message_idx.tableoid) FROM bgl_logs_message_idx WHERE message @@ 'error' LIMIT 1").fetchone()
        self.assertIsNotNone(score)
        self.assertGreater(score[0], 0)

    def test_existing_tables_are_refused_before_any_change(self):
        with self.assertRaisesRegex(ValueError, "Existing loader tables"):
            import_data(self.conn, self.directory, {"datasets": {}})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM team_ownership").fetchone()[0], 0)

    def test_full_reference_queries_reject_an_empty_corpus_without_sql_errors(self):
        report = validate(self.conn)
        self.assertFalse(report["ok"])
        self.assertTrue(any(c["name"] == "bgl.appread_window" for c in report["checks"]))
        self.assertFalse(next(c for c in report["checks"] if c["name"] == "bgl.rows")["passed"])

    def test_failed_replacement_rolls_back_original_tables(self):
        self.conn.execute("INSERT INTO team_ownership VALUES ('bgl', 'KEEP', 'Existing team')")
        datasets = {}
        for table, rows in (("bgl_logs", [bgl.parse_line(BGL, 1)]),
                            ("openstack_logs", [openstack.parse_line(OPENSTACK, 1, "normal1")]),
                            ("openstack_anomaly_vms", []), ("team_ownership", [])):
            server_path = self.fixture(table, rows)
            datasets[table] = {"csv": str(PurePosixPath(server_path).relative_to("/data/processed")), "rows": len(rows)}
        failed_report = {"ok": False, "checks": [{"name": "deliberate_failure", "passed": False}]}
        with patch("loader.load.validate", return_value=failed_report):
            with self.assertRaisesRegex(ValueError, "transaction rolled back"):
                import_data(self.conn, self.directory, {"datasets": datasets}, replace=True)
        self.assertEqual(self.conn.execute("SELECT * FROM team_ownership").fetchall(), [("bgl", "KEEP", "Existing team")])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM bgl_logs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
