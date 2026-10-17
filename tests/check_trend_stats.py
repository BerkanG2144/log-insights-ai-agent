"""Read-only check of the trend summary fields against the loaded full dataset.

Run from the repository root after loading the data:
    python tests/check_trend_stats.py
Exits with status 1 if any value differs from the expected reference.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import server  # noqa: E402

CHECKS = [
    ("APPSEV day", dict(dataset="bgl", bucket="day", label="APPSEV"),
     {"rows_matched": 49651, "active_buckets": 67, "peak_bucket": "2005-11-26",
      "peak_count": 3466, "peak_share": round(3466 / 49651, 6),
      "last_bucket": "2006-01-03", "null_timestamp_rows": 0}),
    ("KERNDTLB day", dict(dataset="bgl", bucket="day", label="KERNDTLB"),
     {"rows_matched": 152734, "active_buckets": 11, "peak_count": 152182,
      "peak_share": round(152182 / 152734, 6)}),
    ("BGL all day", dict(dataset="bgl", bucket="day"),
     {"rows_matched": 4747963, "last_bucket": "2006-01-04"}),
    ("BGL all minute (output limited to 1000 buckets)", dict(dataset="bgl", bucket="minute"),
     {"rows_matched": 4747963, "truncated": True, "last_bucket_prefix": "2006-01-04"}),
    ("OpenStack all day", dict(dataset="openstack", bucket="day"),
     {"rows_matched": 207820, "active_buckets": 3}),
]


def main() -> int:
    failed = 0
    for name, args, expected in CHECKS:
        ev = server.trend(**args)["evidence"]
        problems = []
        if ev.get("status") != "ok":
            problems.append(f"status={ev.get('status')} reason={ev.get('reason')}")
        for key, want in expected.items():
            if key == "last_bucket_prefix":
                got = str(ev.get("last_bucket"))
                if not got.startswith(want):
                    problems.append(f"last_bucket={got!r}, expected to start with {want!r}")
                continue
            got = ev.get(key)
            if isinstance(want, str):
                got = str(got)[:len(want)] if got is not None else None
            if got != want:
                problems.append(f"{key}={got!r}, expected {want!r}")
        if problems:
            failed += 1
            print(f"FAIL {name}: " + "; ".join(problems))
        else:
            print(f"ok   {name}")
    print("all checks passed" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
