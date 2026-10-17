"""Shared column order and lossless line handling for the import files."""

from datetime import datetime

CORE_COLUMNS = ("line_no", "raw_line", "ts", "component", "level", "message", "parse_status")
BGL_COLUMNS = CORE_COLUMNS + ("ts_unix", "node", "rack", "label", "is_alert")
OPENSTACK_COLUMNS = CORE_COLUMNS + (
    "source_file", "pid", "service", "request_id", "instance_id", "http_status", "latency_s",
)
TABLE_COLUMNS = {
    "bgl_logs": BGL_COLUMNS,
    "openstack_logs": OPENSTACK_COLUMNS,
    "openstack_anomaly_vms": ("instance_id",),
    "team_ownership": ("dataset", "component", "team"),
}


def without_line_ending(line: str) -> str:
    """Remove the record terminator only; preserve whitespace inside the log."""
    if line.endswith("\n"):
        line = line[:-1]
        if line.endswith("\r"):
            line = line[:-1]
    return line


def csv_value(value):
    """An unquoted empty CSV field represents SQL NULL, never a sentinel string."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, bool):
        return "true" if value else "false"
    return value
