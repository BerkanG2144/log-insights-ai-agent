"""Check the complete imported corpus and save the executed SQL and results."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from psycopg import sql
from psycopg.rows import dict_row

from .db import ROOT, connect


def json_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def write_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, default=json_value) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate(conn, manifest: dict | None = None, *, check_indexes: bool = False) -> dict:
    report = {"ok": True, "checked_at": datetime.now(timezone.utc).isoformat(), "checks": [], "queries": []}
    if manifest:
        report["prepared_at"] = manifest.get("prepared_at")
        report["sources"] = {table: dataset["sources"] for table, dataset in manifest["datasets"].items()}

    def query(statement, params=()):
        statement = statement.as_string(conn) if hasattr(statement, "as_string") else statement
        with conn.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(statement, params).fetchall()
        query_id = f"Q{len(report['queries']) + 1}"
        report["queries"].append({"query_id": query_id, "sql": statement, "params": params, "results": rows})
        return query_id, rows

    def check(name, actual, expected, query_id):
        passed = actual == expected
        report["checks"].append({
            "name": name, "actual": actual, "expected": expected,
            "passed": passed, "query_id": query_id,
        })
        report["ok"] &= passed

    _, version_rows = query("SELECT version() AS version")
    report["database_version"] = version_rows[0]["version"]

    qid, rows = query("""
        SELECT COUNT(*) AS rows, MIN(line_no) AS first_line, MAX(line_no) AS last_line,
            COUNT(*) FILTER (WHERE label = '-') AS normal,
            COUNT(*) FILTER (WHERE is_alert) AS alerts,
            COUNT(*) FILTER (WHERE label = 'APPREAD') AS appread,
            COUNT(*) FILTER (WHERE parse_status = 'variant_kill') AS variant_kill,
            COUNT(*) FILTER (WHERE parse_status = 'variant_other') AS variant_other,
            COUNT(*) FILTER (WHERE parse_status <> 'ok') AS variants,
            COUNT(*) FILTER (WHERE message IS NULL) AS missing_message,
            COUNT(*) FILTER (WHERE ts IS NULL OR component IS NULL OR level IS NULL
                OR label IS NULL OR ts_unix IS NULL OR raw_line IS NULL) AS missing_required,
            COUNT(*) FILTER (WHERE is_alert IS DISTINCT FROM (label <> '-')) AS incorrect_alert
        FROM bgl_logs
    """)
    for name, expected in {
        "rows": 4_747_963, "first_line": 1, "last_line": 4_747_963,
        "normal": 4_399_503, "alerts": 348_460, "appread": 5_983,
        "variant_kill": 306, "variant_other": 10, "variants": 316,
        "missing_message": 34_470, "missing_required": 0, "incorrect_alert": 0,
    }.items():
        check("bgl." + name, rows[0][name], expected, qid)

    qid, rows = query("SELECT level, COUNT(*) AS rows FROM bgl_logs GROUP BY level ORDER BY level")
    check("bgl.level_counts", {r["level"]: r["rows"] for r in rows}, {
        "INFO": 3_735_823, "FATAL": 855_501, "ERROR": 112_355,
        "WARNING": 23_357, "SEVERE": 19_213, "FAILURE": 1_714,
    }, qid)
    qid, rows = query("""
        SELECT COUNT(*) AS rows, COUNT(DISTINCT node) AS nodes,
            COUNT(*) FILTER (WHERE message LIKE %s) AS same_target
        FROM bgl_logs WHERE label = 'APPREAD' AND ts_unix >= %s AND ts_unix < %s
    """, ("%CioStream socket to 172.16.96.116:%", 1117869872, 1117869882))
    check("bgl.appread_window", rows[0], {"rows": 253, "nodes": 253, "same_target": 253}, qid)

    qid, rows = query("""
        SELECT COUNT(*) AS rows,
            COUNT(*) FILTER (WHERE http_status IS NOT NULL) AS http_status,
            COUNT(*) FILTER (WHERE latency_s IS NOT NULL) AS latency_s,
            COUNT(*) FILTER (WHERE request_id IS NOT NULL) AS request_id,
            COUNT(*) FILTER (WHERE instance_id IS NOT NULL) AS instance_id,
            COUNT(*) FILTER (WHERE level IS NULL) AS missing_level,
            COUNT(*) FILTER (WHERE parse_status = 'variant_level') AS variant_level,
            COUNT(*) FILTER (WHERE parse_status NOT IN ('ok', 'variant_level')) AS unexpected_status,
            COUNT(*) FILTER (WHERE ts IS NULL OR component IS NULL OR service IS NULL
                OR pid IS NULL OR raw_line IS NULL) AS missing_required
        FROM openstack_logs
    """)
    for name, expected in {
        "rows": 207_820, "http_status": 98_733, "latency_s": 98_733,
        "request_id": 192_174, "instance_id": 51_553,
        "missing_level": 0, "variant_level": 0, "unexpected_status": 0, "missing_required": 0,
    }.items():
        check("openstack." + name, rows[0][name], expected, qid)

    qid, rows = query("SELECT level, COUNT(*) AS rows FROM openstack_logs GROUP BY level ORDER BY level")
    check("openstack.level_counts", {r["level"] or "NULL": r["rows"] for r in rows}, {
        "INFO": 204_506, "WARNING": 3_118, "ERROR": 194, "CRITICAL": 2,
    }, qid)
    qid, rows = query("""
        SELECT source_file, COUNT(*) AS rows FROM openstack_logs
        WHERE message LIKE %s GROUP BY source_file ORDER BY source_file
    """, ("%Unknown base file:%",))
    check("openstack.cache_warning_counts", {r["source_file"]: r["rows"] for r in rows}, {
        "normal1": 838, "normal2": 1_951, "abnormal": 270,
    }, qid)

    qid, rows = query("""
        SELECT source_file, COUNT(*) AS rows, MIN(line_no) AS first_line, MAX(line_no) AS last_line
        FROM openstack_logs GROUP BY source_file ORDER BY source_file
    """)
    expected_sources = {"normal1": 52_312, "normal2": 137_074, "abnormal": 18_434}
    check("openstack.source_counts", {r["source_file"]: r["rows"] for r in rows}, expected_sources, qid)
    check("openstack.source_line_numbers", all(
        r["first_line"] == 1 and r["last_line"] == expected_sources.get(r["source_file"]) for r in rows
    ), True, qid)

    qid, rows = query("SELECT service, COUNT(*) AS rows FROM openstack_logs GROUP BY service ORDER BY service")
    check("openstack.service_counts", {r["service"]: r["rows"] for r in rows}, {
        "nova-api": 102_868, "nova-compute": 104_086, "nova-scheduler": 866,
    }, qid)

    qid, rows = query("""
        SELECT a.instance_id,
            COUNT(*) FILTER (WHERE l.source_file = 'abnormal') AS abnormal,
            COUNT(*) FILTER (WHERE l.source_file IN ('normal1', 'normal2')) AS normal
        FROM openstack_anomaly_vms a LEFT JOIN openstack_logs l ON a.instance_id = l.instance_id
        GROUP BY a.instance_id ORDER BY a.instance_id
    """)
    check("anomaly_vms.rows", len(rows), 4, qid)
    check("anomaly_vms.tagged_coverage", [(r["abnormal"], r["normal"]) for r in rows], [(25, 0)] * 4, qid)
    qid, rows = query("""
        SELECT a.instance_id,
            COUNT(*) FILTER (WHERE l.source_file = 'abnormal') AS abnormal,
            COUNT(*) FILTER (WHERE l.source_file IN ('normal1', 'normal2')) AS normal
        FROM openstack_anomaly_vms a LEFT JOIN openstack_logs l
            ON POSITION(a.instance_id IN l.raw_line) > 0
        GROUP BY a.instance_id ORDER BY a.instance_id
    """)
    check("anomaly_vms.raw_mentions", [(r["abnormal"], r["normal"]) for r in rows], [(28, 0)] * 4, qid)

    qid, rows = query("SELECT COUNT(*) AS rows FROM team_ownership")
    check("ownership.rows", rows[0]["rows"], 22, qid)
    qid, rows = query("""
        SELECT c.dataset, c.component
        FROM (
            SELECT DISTINCT 'bgl' AS dataset, component FROM bgl_logs
            UNION ALL SELECT DISTINCT 'openstack' AS dataset, component FROM openstack_logs
        ) c LEFT JOIN team_ownership t ON c.dataset = t.dataset AND c.component = t.component
        WHERE t.team IS NULL ORDER BY c.dataset, c.component
    """)
    check("ownership.unmapped_components", rows, [], qid)

    if manifest:
        for table, dataset in manifest["datasets"].items():
            qid, rows = query(sql.SQL("SELECT COUNT(*) AS rows FROM {}").format(sql.Identifier(table)))
            check(table + ".prepared_count", rows[0]["rows"], dataset["rows"], qid)
            for sample in dataset.get("samples", []):
                keys = ["line_no"] + (["source_file"] if table == "openstack_logs" else [])
                statement = sql.SQL("SELECT * FROM {} WHERE {}").format(
                    sql.Identifier(table), sql.SQL(" AND ").join(
                        sql.SQL("{} = %s").format(sql.Identifier(key)) for key in keys
                    ),
                )
                qid, rows = query(statement, tuple(sample[key] for key in keys))
                normalized = json.loads(json.dumps(rows, default=json_value))
                check(table + ".sample." + ".".join(str(sample[key]) for key in keys), normalized, [sample], qid)

    if check_indexes:
        for table, term, expected_rows in (("bgl_logs", "ciod", 4_747_963), ("openstack_logs", "Unknown", 207_820)):
            index = table + "_message_idx"
            qid, rows = query(sql.SQL("SELECT COUNT(*) AS rows FROM {}").format(sql.Identifier(index)))
            check(index + ".row_coverage", rows[0]["rows"], expected_rows, qid)
            qid, rows = query(sql.SQL("SELECT COUNT(*) AS rows FROM {} WHERE message @@ %s").format(
                sql.Identifier(index)
            ), (term,))
            indexed = rows[0]["rows"]
            # These exact words occur in the known corpus. This also checks refresh/readiness.
            check(index + ".searchable", indexed > 0, True, qid)

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--skip-indexes", action="store_true")
    args = parser.parse_args()
    processed = args.data_dir.resolve() / "processed"
    path = processed / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else None
    with connect() as conn:
        report = validate(conn, manifest, check_indexes=not args.skip_indexes)
    write_report(processed / "validation_report.json", report)
    failures = [c["name"] for c in report["checks"] if not c["passed"]]
    print(f"Validation: {len(report['checks']) - len(failures)}/{len(report['checks'])} checks passed")
    for name in failures:
        print("FAILED:", name)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
