"""Parse BGL's regular rows and the documented structural variants."""

import re
from datetime import datetime

from .common import without_line_ending

# Some regular rows use NULL instead of RAS; a message may be absent entirely.
LINE = re.compile(
    r"^(?P<label>\S+) (?P<ts_unix>\d+) (?P<date>\S+) (?P<node>\S+) "
    r"(?P<ts>\S+) (?:(?P<location>.*?) )?(?:RAS|NULL) "
    r"(?P<component>\S+) (?P<level>\S+)(?: (?P<message>.*))?$"
)
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}\.\d{2}\.\d{2}\.\d{6}")
RACK = re.compile(r"^(R\d{2})-")
LEVELS = {"INFO", "WARNING", "ERROR", "FATAL", "SEVERE", "FAILURE"}


def parse_line(line: str, line_no: int) -> dict:
    raw = without_line_ending(line)
    match = LINE.fullmatch(raw)
    if not match:
        raise ValueError("BGL header does not match a supported structure")
    fields = match.groupdict()
    stamp = fields["ts"]
    if not TIMESTAMP.fullmatch(stamp):
        raise ValueError("Invalid BGL precise timestamp")
    ts = datetime.fromisoformat(stamp[:10] + "T" + stamp[11:19].replace(".", ":") + stamp[19:])
    if fields["level"] not in LEVELS:
        raise ValueError("Unknown BGL level: " + fields["level"])
    unix = int(fields["ts_unix"])
    if unix > 2**63 - 1:
        raise ValueError("BGL Unix timestamp exceeds BIGINT")
    node = None if fields["node"] == "-" else fields["node"]
    location = fields["location"]
    if location is None:
        if node is not None:
            raise ValueError("Missing repeated location without the known '-' node variant")
        status = "variant_kill"
    elif len(location.split()) > 1:
        status = "variant_other"
    else:
        status = "ok"
    rack = RACK.match(node) if node else None
    return {
        "line_no": line_no, "raw_line": raw, "ts": ts,
        "component": fields["component"], "level": fields["level"],
        "message": fields["message"] or None, "parse_status": status,
        "ts_unix": unix, "node": node, "rack": rack[1] if rack else None,
        "label": fields["label"], "is_alert": fields["label"] != "-",
    }
