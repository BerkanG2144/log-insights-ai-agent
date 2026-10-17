"""Parser boundaries and preservation tests. No database or full corpus required."""

import csv
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from loader import bgl, openstack
from loader.common import BGL_COLUMNS, OPENSTACK_COLUMNS, csv_value
from loader.load import check_manifest, prepare, prepare_logs, prepare_small_tables

BGL = "- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected"
OPENSTACK = "nova-api.log.2017-05-14_21:27:04 2017-05-14 19:39:01.445 25746 INFO nova.osapi_compute.wsgi.server [req-5a2050e7-b381-4ae9-92d2-8b08e9f9f4c0 user project - - -] 10.11.10.1 \"GET /servers/detail HTTP/1.1\" status: 200 len: 1583 time: 0.1919448"
VM = "3edec1e4-9678-4a3a-a21b-a145a4ee5e61"


class BGLTests(unittest.TestCase):
    def test_regular_header_timestamp_and_alert_are_independent(self):
        row = bgl.parse_line(BGL + "\n", 17)
        self.assertEqual(set(row), set(BGL_COLUMNS))
        self.assertEqual(row["line_no"], 17)
        self.assertEqual(row["raw_line"], BGL)
        self.assertEqual(row["ts"], datetime(2005, 6, 3, 15, 42, 50, 363779))
        self.assertEqual(row["rack"], "R02")
        self.assertFalse(row["is_alert"])
        self.assertEqual(row["parse_status"], "ok")
        row = bgl.parse_line(BGL.replace("- ", "APPREAD ", 1), 1)
        self.assertTrue(row["is_alert"])
        self.assertEqual(row["level"], "INFO")

    def test_null_type_is_an_ordinary_row(self):
        row = bgl.parse_line(BGL.replace("RAS KERNEL INFO", "NULL HARDWARE WARNING"), 1)
        self.assertEqual((row["component"], row["level"], row["parse_status"]), ("HARDWARE", "WARNING", "ok"))

    def test_absent_message_is_null_and_not_an_error(self):
        raw = BGL.split(" INFO ")[0] + " FATAL"
        row = bgl.parse_line(raw, 1)
        self.assertIsNone(row["message"])
        self.assertEqual(row["level"], "FATAL")
        self.assertEqual(row["parse_status"], "ok")

    def test_kill_variant_has_no_node(self):
        row = bgl.parse_line("- 1119415930 2005.06.21 - 2005-06-21-21.52.10.214285 RAS KERNEL FATAL Kill job 20251 timed out. Block freed.", 885024)
        self.assertIsNone(row["node"])
        self.assertIsNone(row["rack"])
        self.assertEqual(row["parse_status"], "variant_kill")
        self.assertTrue(row["message"].startswith("Kill job"))

    def test_text_in_location_does_not_shift_component_or_message(self):
        row = bgl.parse_line("- 1133447861 2005.12.01 - 2005-12-01-06.37.41.417709 time for a single instance of a correctable ddr. RAS KERNEL INFO 0 microseconds spent in the rbs signal handler", 4344697)
        self.assertEqual(row["parse_status"], "variant_other")
        self.assertEqual(row["component"], "KERNEL")
        self.assertIsNone(row["node"])
        self.assertEqual(row["message"], "0 microseconds spent in the rbs signal handler")

    def test_different_repeated_node_is_not_a_structural_variant(self):
        raw = BGL.replace("363779 R02-M1-N0-C:J12-U11", "363779 R03-M1-N0-C:J12-U11")
        row = bgl.parse_line(raw, 1)
        self.assertEqual(row["node"], "R02-M1-N0-C:J12-U11")
        self.assertEqual(row["parse_status"], "ok")

    def test_preserves_trailing_spaces_and_crlf_is_a_terminator(self):
        row = bgl.parse_line(BGL + "  \r\n", 1)
        self.assertEqual(row["raw_line"], BGL + "  ")
        self.assertTrue(row["message"].endswith("  "))

    def test_invalid_date_or_unknown_level_cannot_look_successful(self):
        for raw in (BGL.replace("2005-06-03-", "2005-99-03-"), BGL.replace(" INFO ", " UNKNOWN ")):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                bgl.parse_line(raw, 1)


class OpenStackTests(unittest.TestCase):
    def test_http_fields_and_source_identity(self):
        row = openstack.parse_line(OPENSTACK + "\n", 3, "abnormal")
        self.assertEqual(set(row), set(OPENSTACK_COLUMNS))
        self.assertEqual(row["raw_line"], OPENSTACK)
        self.assertEqual(row["request_id"], "req-5a2050e7-b381-4ae9-92d2-8b08e9f9f4c0")
        self.assertEqual(row["http_status"], 200)
        self.assertEqual(row["latency_s"], 0.1919448)
        self.assertEqual((row["source_file"], row["line_no"]), ("abnormal", 3))
        self.assertEqual(row["ts"], datetime(2017, 5, 14, 19, 39, 1, 445000))

    def test_request_context_is_not_part_of_message_but_instance_tag_is(self):
        raw = "nova-compute.log.1 2017-05-14 19:39:02.007 2931 INFO nova.compute.manager [req-e285b551-587f-4c1d-8eba-dceb2673637f - - - - -] [instance: " + VM + "] Creating image"
        row = openstack.parse_line(raw, 2, "normal1")
        self.assertEqual(row["instance_id"], VM)
        self.assertEqual(row["message"], "[instance: " + VM + "] Creating image")
        self.assertIsNone(row["http_status"])
        self.assertIsNone(row["latency_s"])

    def test_empty_request_context_and_missing_vm_are_null(self):
        raw = "nova-scheduler.log.1 2017-05-14 19:39:02.007 2931 INFO nova.scheduler.host_manager [-] normal background work"
        row = openstack.parse_line(raw, 1, "normal2")
        self.assertIsNone(row["request_id"])
        self.assertIsNone(row["instance_id"])
        self.assertEqual(row["message"], "normal background work")

    def test_known_w_level_is_not_guessed(self):
        row = openstack.parse_line(OPENSTACK.replace(" INFO ", " w "), 27179, "normal1")
        self.assertIsNone(row["level"])
        self.assertEqual(row["parse_status"], "variant_level")

    def test_traceback_without_context_keeps_indentation_and_line_identity(self):
        raw = 'nova-compute.log.1 2017-05-16 03:19:45.356 2931 ERROR oslo_service.periodic_task   File "/usr/lib/python2.7/example.py", line 220'
        row = openstack.parse_line(raw, 27181, "normal1")
        self.assertEqual(row["message"], '  File "/usr/lib/python2.7/example.py", line 220')
        self.assertEqual(row["line_no"], 27181)
        self.assertEqual(row["level"], "ERROR")
        self.assertEqual(row["parse_status"], "ok")
        self.assertIsNone(row["request_id"])
        self.assertEqual(row["raw_line"], raw)

    def test_api_path_is_not_silently_treated_as_instance_tag(self):
        row = openstack.parse_line(OPENSTACK.replace("/servers/detail", "/servers/" + VM), 1, "abnormal")
        self.assertIsNone(row["instance_id"])

    def test_invalid_input_and_source_fail_visibly(self):
        for raw, source in ((OPENSTACK, "unknown"), (OPENSTACK.replace(" INFO ", " GARBAGE "), "normal1"), ("broken", "normal1")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                openstack.parse_line(raw, 1, source)


class PreparationTests(unittest.TestCase):
    def test_unrecognized_line_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "input.txt"
            source.write_text(BGL + "\nbroken, \"quoted\" \\N\n", encoding="utf-8")
            errors = io.StringIO()
            result = prepare_logs("bgl_logs", [(source, None)], root / "out.csv", errors)
            with (root / "out.csv").open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["parse_errors"], 1)
            self.assertEqual(rows[1]["raw_line"], 'broken, "quoted" \\N')
            self.assertEqual(rows[1]["parse_status"], "parse_error")
            self.assertEqual(rows[1]["line_no"], "2")
            self.assertIn('"line_no": 2', errors.getvalue())

    def test_labels_last_line_without_newline_and_duplicate_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            labels = root / "full/OpenStack/anomaly_labels.txt"
            labels.parent.mkdir(parents=True)
            labels.write_text("The following VM instances have injected anomalies as observed in openstack_abnormal.log.\n\n" + VM)
            result = prepare_small_tables(root, root)
            self.assertEqual(result["openstack_anomaly_vms"]["rows"], 1)
            self.assertEqual(result["team_ownership"]["rows"], 22)
            labels.write_text(VM + "\n" + VM)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                prepare_small_tables(root, root)

    def test_csv_conversion_uses_null_and_precise_timestamps(self):
        self.assertEqual(csv_value(None), "")
        self.assertEqual(csv_value(False), "false")
        self.assertEqual(csv_value(datetime(2005, 6, 3, 15, 42, 50, 1)), "2005-06-03 15:42:50.000001")

    def test_preparation_publishes_immutable_generations_and_checks_fingerprints(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "full/BGL").mkdir(parents=True)
            (root / "full/OpenStack").mkdir(parents=True)
            source = root / "full/BGL/BGL.log"
            source.write_text(BGL + "\n")
            for name in openstack.SOURCE_FILES:
                (root / f"full/OpenStack/openstack_{name}.log").write_text(OPENSTACK + "\n")
            (root / "full/OpenStack/anomaly_labels.txt").write_text(VM)
            first = prepare(root)
            old_path = root / "processed" / first["datasets"]["bgl_logs"]["csv"]
            original_export = old_path.read_bytes()
            source.write_text(BGL + " again\n")
            second = prepare(root)
            new_path = root / "processed" / second["datasets"]["bgl_logs"]["csv"]
            self.assertNotEqual(old_path, new_path)
            self.assertEqual(old_path.read_bytes(), original_export)
            self.assertEqual(check_manifest(root)["datasets"]["bgl_logs"]["rows"], 1)
            new_path.write_text("tampered")
            with self.assertRaisesRegex(ValueError, "CSV changed"):
                check_manifest(root)


if __name__ == "__main__":
    unittest.main()
