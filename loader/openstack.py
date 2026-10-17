"""Parse OpenStack headers and optional request/VM/HTTP fields."""

import re
from datetime import datetime

from .common import without_line_ending

UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
LINE = re.compile(
    r"^(?P<file>\S+) (?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}\.\d{3}) (?P<pid>\d+) "
    r"(?P<level>\S+) (?P<component>\S+)"
    r"(?: \[(?P<context>req-[^\]]*|-)\])?(?: (?P<message>.*))?$"
)
REQUEST = re.compile(r"\[(req-" + UUID + r")(?=\s|\])")
INSTANCE = re.compile(r"\[instance: (" + UUID + r")\]")
HTTP_STATUS = re.compile(r"\bstatus: (\d{3})(?=\s|$)")
LATENCY = re.compile(r"\btime: (\d+(?:\.\d+)?)(?=\s|$)")
SERVICES = {"nova-api", "nova-compute", "nova-scheduler"}
LEVELS = {"INFO", "WARNING", "ERROR", "CRITICAL"}
SOURCE_FILES = ("normal1", "normal2", "abnormal")


def parse_line(line: str, line_no: int, source_file: str) -> dict:
    if source_file not in SOURCE_FILES:
        raise ValueError("Unknown OpenStack source_file: " + source_file)
    raw = without_line_ending(line)
    match = LINE.fullmatch(raw)
    if not match:
        raise ValueError("OpenStack header does not match a supported structure")
    fields = match.groupdict()
    service, separator, _ = fields["file"].partition(".log")
    if not separator or service not in SERVICES:
        raise ValueError("Unknown OpenStack service: " + fields["file"])
    level = fields["level"]
    if level not in LEVELS and level != "w":
        raise ValueError("Unknown OpenStack level: " + level)
    pid = int(fields["pid"])
    if pid > 2**31 - 1:
        raise ValueError("OpenStack PID exceeds INTEGER")
    message = fields["message"] or None
    request = REQUEST.search("[" + fields["context"] + "]") if fields["context"] else None
    instance = INSTANCE.search(message or "")
    http = HTTP_STATUS.search(message or "")
    latency = LATENCY.search(message or "")
    return {
        "line_no": line_no, "raw_line": raw,
        "ts": datetime.fromisoformat(fields["date"] + "T" + fields["time"]),
        "component": fields["component"], "level": None if level == "w" else level,
        "message": message, "parse_status": "variant_level" if level == "w" else "ok",
        "source_file": source_file, "pid": pid, "service": service,
        "request_id": request[1] if request else None,
        "instance_id": instance[1] if instance else None,
        "http_status": int(http[1]) if http else None,
        "latency_s": float(latency[1]) if latency else None,
    }
