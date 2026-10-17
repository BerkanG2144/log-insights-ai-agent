"""Prepare and bulk-import the complete BGL/OpenStack corpus, then verify it."""

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from psycopg import Error, sql

from . import bgl, openstack
from .common import TABLE_COLUMNS, csv_value, without_line_ending
from .db import ROOT, connect
from .validate import json_value, validate, write_report

HERE = Path(__file__).resolve().parent
INDEX_NAMES = ("bgl_logs_message_idx", "openstack_logs_message_idx")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_logs(table, sources, output, errors):
    columns = TABLE_COLUMNS[table]
    count = 0
    failures = 0
    statuses = Counter()
    inputs = []
    samples = []
    sampled = set()
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(columns)
        for source, source_file in sources:
            digest = hashlib.sha256()
            source_rows = 0
            with source.open("rb") as raw_stream:
                for line_no, encoded in enumerate(raw_stream, 1):
                    digest.update(encoded)
                    raw = encoded.decode("utf-8")  # Fail visibly on undecodable input.
                    try:
                        row = (bgl.parse_line(raw, line_no) if table == "bgl_logs" else
                               openstack.parse_line(raw, line_no, source_file))
                    except ValueError as exc:
                        row = dict.fromkeys(columns)
                        row.update(line_no=line_no, raw_line=without_line_ending(raw), parse_status="parse_error")
                        if table == "openstack_logs":
                            row["source_file"] = source_file
                        errors.write(json.dumps({
                            "table": table, "source": str(source), "line_no": line_no, "reason": str(exc),
                        }) + "\n")
                        failures += 1
                    writer.writerow([csv_value(row[column]) for column in columns])
                    count += 1
                    source_rows += 1
                    statuses[row["parse_status"]] += 1
                    sample_kind = (source_file, row["parse_status"], row["message"] is None)
                    if sample_kind not in sampled or line_no % 1_000_000 == 0:
                        samples.append(json.loads(json.dumps(row, default=json_value)))
                        sampled.add(sample_kind)
                    if count % 500_000 == 0:
                        print(f"{table}: prepared {count:,} rows", flush=True)
            inputs.append({"path": str(source.resolve()), "rows": source_rows, "sha256": digest.hexdigest()})
    return {
        "columns": columns, "rows": count, "parse_statuses": dict(statuses),
        "parse_errors": failures, "sources": inputs, "samples": samples,
    }


def prepare_small_tables(data_dir, output_dir):
    labels = data_dir / "full/OpenStack/anomaly_labels.txt"
    ids = []
    for line in labels.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value == "The following VM instances have injected anomalies as observed in openstack_abnormal.log.":
            continue
        if not re.fullmatch(openstack.UUID, value):
            raise ValueError("Unexpected content in anomaly_labels.txt: " + value)
        if value in ids:
            raise ValueError("Duplicate anomaly VM: " + value)
        ids.append(value)
    ownership = HERE / "team_ownership.csv"
    with ownership.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != TABLE_COLUMNS["team_ownership"]:
            raise ValueError("Unexpected ownership CSV columns")
        owners = list(reader)
    if any(not all(row.values()) or row["dataset"] not in ("bgl", "openstack") for row in owners):
        raise ValueError("Invalid ownership CSV row")
    if len({(r["dataset"], r["component"]) for r in owners}) != len(owners):
        raise ValueError("Duplicate ownership mapping")
    datasets = {}
    for table, rows, source in (
        ("openstack_anomaly_vms", [{"instance_id": value} for value in ids], labels),
        ("team_ownership", owners, ownership),
    ):
        columns = TABLE_COLUMNS[table]
        with (output_dir / (table + ".csv")).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        datasets[table] = {"columns": columns, "rows": len(rows), "parse_errors": 0,
                           "sources": [{"path": str(source.resolve()), "sha256": sha256(source)}]}
    return datasets


def prepare(data_dir: Path) -> dict:
    processed = data_dir / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    # Immutable generation paths also avoid stale file handles in Docker Desktop mounts.
    generation = "run-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".preparing-", dir=processed) as temporary:
        stage = Path(temporary)
        with (stage / "parse_errors.jsonl").open("w", encoding="utf-8") as errors:
            datasets = {
                "bgl_logs": prepare_logs("bgl_logs", [(data_dir / "full/BGL/BGL.log", None)],
                                         stage / "bgl_logs.csv", errors),
                "openstack_logs": prepare_logs("openstack_logs", [
                    (data_dir / f"full/OpenStack/openstack_{name}.log", name) for name in openstack.SOURCE_FILES
                ], stage / "openstack_logs.csv", errors),
            }
        datasets.update(prepare_small_tables(data_dir, stage))
        for table, info in datasets.items():
            info["csv"] = str(PurePosixPath(generation) / (table + ".csv"))
            info["csv_sha256"] = sha256(stage / (table + ".csv"))
        manifest = {"format_version": 1, "prepared_at": datetime.now(timezone.utc).isoformat(),
                    "datasets": datasets, "ok": not any(d["parse_errors"] for d in datasets.values())}
        write_report(stage / "manifest.json", manifest)
        stage.rename(processed / generation)
        # Publish the pointer last. Earlier exports remain immutable and inspectable.
        write_report(processed / "manifest.json", manifest)
        (processed / "parse_errors.jsonl").write_bytes((processed / generation / "parse_errors.jsonl").read_bytes())
    for table, info in datasets.items():
        print(f"{table}: {info['rows']:,} rows; {info.get('parse_statuses', {})}", flush=True)
    if not manifest["ok"]:
        raise ValueError(f"Unexpected parsing errors. Raw rows are preserved in CSV; see {processed / 'parse_errors.jsonl'}. Import refused.")
    return manifest


def check_manifest(data_dir: Path) -> dict:
    processed = data_dir / "processed"
    manifest = json.loads((processed / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or not manifest.get("ok"):
        raise ValueError("Prepared data is incomplete or contains parsing errors; prepare it again")
    if set(manifest["datasets"]) != set(TABLE_COLUMNS):
        raise ValueError("Prepared manifest does not contain the four agreed tables")
    for table, info in manifest["datasets"].items():
        csv_path = PurePosixPath(info["csv"])
        valid_path = (len(csv_path.parts) == 2 and
                      re.fullmatch(r"run-[0-9a-f]{32}", csv_path.parts[0]) and
                      csv_path.name == table + ".csv")
        if info["columns"] != list(TABLE_COLUMNS[table]) or not valid_path:
            raise ValueError("Prepared data does not match the agreed column order")
        if sha256(processed / info["csv"]) != info["csv_sha256"]:
            raise ValueError("Prepared CSV changed: " + info["csv"])
        for source in info["sources"]:
            if sha256(Path(source["path"])) != source["sha256"]:
                raise ValueError("Source changed since preparation: " + source["path"])
    return manifest


def existing_tables(conn):
    rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()").fetchall()
    return sorted({r[0] for r in rows} & set(TABLE_COLUMNS))


def execute_file(conn, name):
    for statement in (HERE / name).read_text(encoding="utf-8").split(";"):
        if statement.strip():
            conn.execute(statement)


def create_indexes(conn):
    with conn.transaction():
        execute_file(conn, "indexes.sql")
    # An index built in a transaction becomes searchable after commit and refresh.
    for table in ("bgl_logs", "openstack_logs"):
        print("Refreshing full-text index:", table, flush=True)
        conn.execute(sql.SQL("VACUUM (REFRESH_TABLE) {}").format(sql.Identifier(table)))


def copy_csv(conn, table, server_path):
    """Bulk-load a prepared file; its column order and CSV options are explicit."""
    conn.execute(sql.SQL(
        "COPY {} ({}) FROM {} (FORMAT CSV, HEADER true, DELIMITER ',', "
        "QUOTE '\"', ESCAPE '\"', NULL '', AUTO_DETECT false)"
    ).format(sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, TABLE_COLUMNS[table])),
             sql.Literal(server_path)))


def import_data(conn, data_dir, manifest, *, replace=False):
    conflicts = existing_tables(conn)
    if conflicts and not replace:
        raise ValueError("Existing loader tables: " + ", ".join(conflicts) + ". Use --replace explicitly to rebuild them.")
    with conn.transaction():
        if replace:
            for index in INDEX_NAMES:
                conn.execute(sql.SQL("DROP INDEX IF EXISTS {}").format(sql.Identifier(index)))
            for table in TABLE_COLUMNS:
                conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(table)))
            conn.execute("DROP TEXT SEARCH DICTIONARY IF EXISTS log_insights_words")
        execute_file(conn, "schema.sql")
        for table, info in manifest["datasets"].items():
            path = str(PurePosixPath("/data/processed") / info["csv"])
            print(f"Importing {table}: {info['rows']:,} rows from {path}", flush=True)
            copy_csv(conn, table, path)
        report = validate(conn, manifest)
        report["committed"] = False
        write_report(data_dir / "processed/import_report.json", report)
        if not report["ok"]:
            failures = [c["name"] for c in report["checks"] if not c["passed"]]
            raise ValueError("Import validation failed; transaction rolled back: " + ", ".join(failures))
    report["committed"] = True
    write_report(data_dir / "processed/import_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-only", action="store_true", help="Write CSVs and manifest, without connecting to SereneDB")
    mode.add_argument("--import-only", action="store_true", help="Verify and import already prepared CSVs")
    mode.add_argument("--indexes-only", action="store_true", help="Build missing full-text indexes after --skip-indexes")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="Host directory mounted as /data in SereneDB")
    parser.add_argument("--replace", action="store_true", help="Explicitly rebuild only the four loader tables and their indexes")
    parser.add_argument("--skip-indexes", action="store_true")
    args = parser.parse_args()
    if args.replace and (args.prepare_only or args.indexes_only):
        parser.error("--replace applies to data import only")
    if args.indexes_only and args.skip_indexes:
        parser.error("--indexes-only cannot be combined with --skip-indexes")
    data_dir = args.data_dir.resolve()
    try:
        if args.prepare_only:
            prepare(data_dir)
            return 0
        with connect() as conn:
            if not args.indexes_only:
                conflicts = existing_tables(conn)
                if conflicts and not args.replace:
                    raise ValueError("Existing loader tables: " + ", ".join(conflicts) + ". No data changed. Use --replace explicitly to rebuild.")
                if not args.import_only:
                    prepare(data_dir)
                manifest = check_manifest(data_dir)
                import_data(conn, data_dir, manifest, replace=args.replace)
            else:
                manifest_path = data_dir / "processed/manifest.json"
                manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
            if not args.skip_indexes:
                create_indexes(conn)
            report = validate(conn, manifest, check_indexes=not args.skip_indexes)
            write_report(data_dir / "processed/validation_report.json", report)
            failures = [c["name"] for c in report["checks"] if not c["passed"]]
            if failures:
                raise ValueError("Validation failed: " + ", ".join(failures))
            print(f"Success: {len(report['checks'])} SQL checks passed. Report: {data_dir / 'processed/validation_report.json'}")
        return 0
    except (OSError, ValueError, Error) as exc:
        print("Loader error:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
