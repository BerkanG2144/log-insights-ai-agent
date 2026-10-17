"""MCP server exposing log analysis tools over SereneDB.

Tables and tool contracts are defined in docs/schema.md.
Run via Claude Code (stdio transport); never print to stdout.
"""

import itertools
import logging
import os
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from mcp.server import MCPServer
from psycopg.rows import dict_row

from roles import ENGINEER, MANAGER, SERVER_INSTRUCTIONS, TEAM_LEAD

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# stdout is reserved for the MCP protocol, so log to stderr only.
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("log-insights")

mcp = MCPServer("log-insights", instructions=SERVER_INSTRUCTIONS)

# ---------------------------------------------------------------------------
# Dataset configuration (must match docs/schema.md)
# ---------------------------------------------------------------------------

DATASETS = {
    "bgl": {
        "table": "bgl_logs",
        "columns": ["line_no", "ts", "level", "component", "node", "label", "message"],
        "group_by": ["component", "level", "team", "label", "node", "rack"],
    },
    "openstack": {
        "table": "openstack_logs",
        "columns": [
            "source_file", "line_no", "ts", "level", "component", "service",
            "instance_id", "request_id", "http_status", "latency_s", "message",
        ],
        "group_by": [
            "component", "level", "team", "service", "http_status",
            "instance_id", "source_file",
        ],
    },
}

BUCKETS = {"minute", "hour", "day"}
MAX_MESSAGE_CHARS = 500
MAX_BUCKETS = 1000

_query_ids = itertools.count(1)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def connect() -> psycopg.Connection:
    """Open a new connection to SereneDB using values from .env."""
    return psycopg.connect(
        host=os.getenv("SERENEDB_HOST", "127.0.0.1"),
        port=int(os.getenv("SERENEDB_PORT", "7890")),
        user=os.getenv("SERENEDB_USER", "postgres"),
        password=os.getenv("SERENEDB_PASSWORD", "hackathon"),
        dbname=os.getenv("SERENEDB_DB", "postgres"),
        row_factory=dict_row,
        autocommit=True,
    )


def run_query(sql: str, params: dict | None = None) -> list[dict]:
    """Run a parameterized query and return all rows as dicts."""
    with connect() as conn:
        return conn.execute(sql, params or {}).fetchall()


def to_json(value):
    """Convert database values into JSON-friendly values."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str) and len(value) > MAX_MESSAGE_CHARS:
        return value[:MAX_MESSAGE_CHARS] + " [...]"
    return value


def clean_rows(rows: list[dict]) -> list[dict]:
    return [{k: to_json(v) for k, v in row.items()} for row in rows]


# ---------------------------------------------------------------------------
# Evidence record (see docs/schema.md, "Evidence record")
# ---------------------------------------------------------------------------

def evidence(tool: str, dataset: str, params: dict, sql: str, scope: str,
             rows_matched: int, rows_returned: int, limit: int | None,
             truncated: bool) -> dict:
    return {
        "query_id": f"Q{next(_query_ids)}",
        "tool": tool,
        "dataset": dataset,
        "params": params,
        "sql": sql,
        "scope": scope,
        "rows_matched": rows_matched,
        "rows_returned": rows_returned,
        "limit": limit,
        "truncated": truncated,
        "status": "ok" if rows_matched > 0 else "empty",
    }


def not_checkable(tool: str, dataset: str, params: dict, reason: str,
                  sql: str | None = None) -> dict:
    return {
        "results": [],
        "evidence": {
            "query_id": f"Q{next(_query_ids)}",
            "tool": tool,
            "dataset": dataset,
            "params": params,
            "sql": sql,
            "scope": None,
            "rows_matched": None,
            "rows_returned": 0,
            "limit": params.get("limit"),
            "truncated": False,
            "status": "not_checkable",
            "reason": reason,
        },
    }


# ---------------------------------------------------------------------------
# Shared query building
# ---------------------------------------------------------------------------

def parse_ts(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO timestamp like '2005-06-03 15:42:50'") from exc


def base_from(dataset: str) -> str:
    """FROM clause with the ownership table joined, so `team` works everywhere."""
    table = DATASETS[dataset]["table"]
    return (
        f"FROM {table} t "
        "LEFT JOIN team_ownership o "
        "ON o.dataset = %(dataset)s AND o.component = t.component"
    )


def build_where(dataset: str, text=None, component=None, level=None, team=None,
                from_ts=None, to_ts=None, extra: dict | None = None) -> tuple[str, dict, str]:
    """Return (WHERE clause, params, human-readable scope)."""
    clauses, params, scope = [], {"dataset": dataset}, []

    if text:
        # Placeholder until the SereneDB full-text index is set up (schema.md, "Full-text index").
        # TODO: replace with the inverted-index match (@@) once the DDL is agreed.
        clauses.append("LOWER(t.message) LIKE %(text)s")
        params["text"] = f"%{text.lower()}%"
        scope.append(f"message contains '{text}'")
    if component:
        clauses.append("t.component = %(component)s")
        params["component"] = component
        scope.append(f"component = {component}")
    if level:
        clauses.append("t.level = %(level)s")
        params["level"] = level.upper()
        scope.append(f"level = {level.upper()}")
    if team:
        clauses.append("o.team = %(team)s")
        params["team"] = team
        scope.append(f"team = {team}")
    if from_ts:
        clauses.append("t.ts >= %(from_ts)s")
        params["from_ts"] = parse_ts(from_ts, "from_ts")
        scope.append(f"ts >= {from_ts}")
    if to_ts:
        clauses.append("t.ts <= %(to_ts)s")
        params["to_ts"] = parse_ts(to_ts, "to_ts")
        scope.append(f"ts <= {to_ts}")
    for column, value in (extra or {}).items():
        if value is not None:
            clauses.append(f"t.{column} = %({column})s")
            params[column] = value
            scope.append(f"{column} = {value}")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    table = DATASETS[dataset]["table"]
    scope_text = f"{table}, " + (", ".join(scope) if scope else "all rows")
    return where, params, scope_text


def check_dataset(dataset: str) -> str | None:
    if dataset not in DATASETS:
        return f"unknown dataset '{dataset}', use one of: {', '.join(DATASETS)}"
    return None


def clamp(value: int | None, default: int, maximum: int) -> int:
    if value is None or value < 1:
        return default
    return min(value, maximum)


def select_columns(dataset: str) -> str:
    return ", ".join(f"t.{c}" for c in DATASETS[dataset]["columns"])


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def ping() -> dict:
    """Check that the MCP server can reach SereneDB. Returns {"ok": true} on success."""
    sql = "SELECT 1 AS ok"
    try:
        rows = run_query(sql)
        return {"ok": rows[0]["ok"] == 1, "sql": sql}
    except Exception as exc:  # report the error to the agent instead of crashing
        log.exception("ping failed")
        return {"ok": False, "sql": sql, "error": str(exc)}


@mcp.tool()
def search_logs(dataset: str, text: str, component: str | None = None,
                level: str | None = None, team: str | None = None,
                from_ts: str | None = None, to_ts: str | None = None,
                limit: int = 20) -> dict:
    """Find log lines whose message contains `text`.

    Use this to locate concrete evidence: specific errors, IPs, VM ids, request ids.
    dataset: "bgl" (BlueGene/L supercomputer) or "openstack" (Nova cloud logs).
    Optional filters: component, level (e.g. FATAL, ERROR), team (from the ownership
    table), from_ts / to_ts (ISO timestamps). limit: default 20, max 100.
    Returns matching rows (oldest first) plus an evidence record with the exact SQL,
    the total number of matches and whether the list was truncated.
    """
    params = {"text": text, "component": component, "level": level, "team": team,
              "from_ts": from_ts, "to_ts": to_ts, "limit": limit}
    if (err := check_dataset(dataset)):
        return not_checkable("search_logs", dataset, params, err)
    limit = clamp(limit, 20, 100)
    params["limit"] = limit
    try:
        where, qp, scope = build_where(dataset, text, component, level, team, from_ts, to_ts)
        frm = base_from(dataset)
        count_sql = f"SELECT COUNT(*) AS n {frm} {where}"
        rows_sql = (f"SELECT {select_columns(dataset)}, o.team {frm} {where} "
                    f"ORDER BY t.ts LIMIT {limit}")
        matched = run_query(count_sql, qp)[0]["n"]
        rows = run_query(rows_sql, qp) if matched else []
    except Exception as exc:
        log.exception("search_logs failed")
        return not_checkable("search_logs", dataset, params, str(exc))
    return {
        "results": clean_rows(rows),
        "evidence": evidence("search_logs", dataset, params, rows_sql, scope,
                             matched, len(rows), limit, matched > len(rows)),
    }


@mcp.tool()
def nearby_events(dataset: str, line_no: int | None = None,
                  source_file: str | None = None, ts: str | None = None,
                  window_seconds: int = 60, node: str | None = None,
                  request_id: str | None = None, instance_id: str | None = None,
                  limit: int = 50) -> dict:
    """Show what happened around one moment: log lines within +/- window_seconds.

    Use this after search_logs to see the context of an interesting line
    (what came before and after it).
    Anchor: either line_no (for openstack also source_file: normal1/normal2/abnormal)
    or ts (ISO timestamp).
    Optional: restrict to the same node (bgl) or request_id / instance_id (openstack).
    window_seconds: default 60, max 3600. limit: default 50, max 200.
    Returns rows in time order with offset_s relative to the anchor, plus evidence.
    """
    params = {"line_no": line_no, "source_file": source_file, "ts": ts,
              "window_seconds": window_seconds, "node": node,
              "request_id": request_id, "instance_id": instance_id, "limit": limit}
    if (err := check_dataset(dataset)):
        return not_checkable("nearby_events", dataset, params, err)
    if node and dataset != "bgl":
        return not_checkable("nearby_events", dataset, params, "node exists only in bgl")
    if (request_id or instance_id) and dataset != "openstack":
        return not_checkable("nearby_events", dataset, params,
                             "request_id / instance_id exist only in openstack")
    window_seconds = clamp(window_seconds, 60, 3600)
    limit = clamp(limit, 50, 200)
    params.update(window_seconds=window_seconds, limit=limit)
    table = DATASETS[dataset]["table"]

    try:
        # 1) Find the anchor time.
        if line_no is not None:
            anchor_sql = f"SELECT ts FROM {table} WHERE line_no = %(line_no)s"
            anchor_params = {"line_no": line_no}
            if dataset == "openstack":
                if not source_file:
                    return not_checkable("nearby_events", dataset, params,
                                         "openstack needs source_file together with line_no")
                anchor_sql += " AND source_file = %(source_file)s"
                anchor_params["source_file"] = source_file
            found = run_query(anchor_sql, anchor_params)
            if not found or found[0]["ts"] is None:
                return not_checkable("nearby_events", dataset, params,
                                     "anchor line not found or has no timestamp", anchor_sql)
            anchor = found[0]["ts"]
        elif ts is not None:
            anchor = parse_ts(ts, "ts")
        else:
            return not_checkable("nearby_events", dataset, params, "give line_no or ts")

        # 2) Window around the anchor (bounds computed in Python, passed as parameters).
        delta = timedelta(seconds=window_seconds)
        extra = {"node": node, "request_id": request_id, "instance_id": instance_id}
        where, qp, scope = build_where(
            dataset, from_ts=(anchor - delta).isoformat(sep=" "),
            to_ts=(anchor + delta).isoformat(sep=" "), extra=extra)
        frm = base_from(dataset)
        count_sql = f"SELECT COUNT(*) AS n {frm} {where}"
        rows_sql = (f"SELECT {select_columns(dataset)}, o.team {frm} {where} "
                    f"ORDER BY t.ts LIMIT {limit}")
        matched = run_query(count_sql, qp)[0]["n"]
        rows = run_query(rows_sql, qp) if matched else []
    except Exception as exc:
        log.exception("nearby_events failed")
        return not_checkable("nearby_events", dataset, params, str(exc))

    for row in rows:
        if row.get("ts") is not None:
            row["offset_s"] = round((row["ts"] - anchor).total_seconds(), 3)
    result_evidence = evidence("nearby_events", dataset, params, rows_sql, scope,
                               matched, len(rows), limit, matched > len(rows))
    result_evidence["anchor_ts"] = to_json(anchor)
    return {"results": clean_rows(rows), "evidence": result_evidence}


@mcp.tool()
def count_by(dataset: str, group_by: str, text: str | None = None,
             component: str | None = None, level: str | None = None,
             team: str | None = None, from_ts: str | None = None,
             to_ts: str | None = None, limit: int = 20) -> dict:
    """Count log lines per group, largest groups first.

    Use this for overviews: which components, nodes, teams or levels produce the most
    lines or errors. Combine with filters (e.g. level="FATAL") to focus.
    group_by for bgl: component, level, team, label, node, rack.
    group_by for openstack: component, level, team, service, http_status,
    instance_id, source_file.
    limit: number of groups, default 20, max 100.
    Returns [{key, count}] plus evidence (rows_matched = all counted rows).
    """
    params = {"group_by": group_by, "text": text, "component": component,
              "level": level, "team": team, "from_ts": from_ts, "to_ts": to_ts,
              "limit": limit}
    if (err := check_dataset(dataset)):
        return not_checkable("count_by", dataset, params, err)
    allowed = DATASETS[dataset]["group_by"]
    if group_by not in allowed:
        return not_checkable("count_by", dataset, params,
                             f"group_by must be one of: {', '.join(allowed)}")
    limit = clamp(limit, 20, 100)
    params["limit"] = limit
    # group_by comes from the whitelist above, so it is safe to inline.
    key = "o.team" if group_by == "team" else f"t.{group_by}"
    try:
        where, qp, scope = build_where(dataset, text, component, level, team, from_ts, to_ts)
        frm = base_from(dataset)
        # COUNT(DISTINCT) ignores NULL, so add 1 if a NULL group exists.
        total_sql = (f"SELECT COUNT(*) AS n, COUNT(DISTINCT {key}) "
                     f"+ CASE WHEN COUNT(*) > COUNT({key}) THEN 1 ELSE 0 END AS groups "
                     f"{frm} {where}")
        rows_sql = (f"SELECT {key} AS key, COUNT(*) AS count {frm} {where} "
                    f"GROUP BY {key} ORDER BY count DESC LIMIT {limit}")
        totals = run_query(total_sql, qp)[0]
        rows = run_query(rows_sql, qp) if totals["n"] else []
    except Exception as exc:
        log.exception("count_by failed")
        return not_checkable("count_by", dataset, params, str(exc))
    # Truncated if the returned groups do not cover every counted row.
    covered = sum(row["count"] for row in rows)
    result_evidence = evidence("count_by", dataset, params, rows_sql, scope,
                               totals["n"], len(rows), limit, covered < totals["n"])
    result_evidence["groups_total"] = totals["groups"]
    return {"results": clean_rows(rows), "evidence": result_evidence}


@mcp.tool()
def trend(dataset: str, bucket: str = "hour", text: str | None = None,
          component: str | None = None, level: str | None = None,
          team: str | None = None, from_ts: str | None = None,
          to_ts: str | None = None) -> dict:
    """Count log lines per time bucket to see when something started, peaked or stopped.

    bucket: "minute", "hour" or "day". Use from_ts / to_ts to zoom in before using
    "minute". Same filters as search_logs (text, component, level, team).
    Returns [{bucket_start, count}] in time order (max 1000 buckets) plus evidence.
    Buckets with zero lines are not listed.
    """
    params = {"bucket": bucket, "text": text, "component": component, "level": level,
              "team": team, "from_ts": from_ts, "to_ts": to_ts}
    if (err := check_dataset(dataset)):
        return not_checkable("trend", dataset, params, err)
    if bucket not in BUCKETS:
        return not_checkable("trend", dataset, params,
                             f"bucket must be one of: {', '.join(sorted(BUCKETS))}")
    try:
        where, qp, scope = build_where(dataset, text, component, level, team, from_ts, to_ts)
        frm = base_from(dataset)
        # bucket comes from the whitelist above, so it is safe to inline.
        bucket_expr = f"date_trunc('{bucket}', t.ts)"
        # COUNT(DISTINCT) ignores NULL, so add 1 if lines without a timestamp exist.
        total_sql = (f"SELECT COUNT(*) AS n, COUNT(DISTINCT {bucket_expr}) "
                     f"+ CASE WHEN COUNT(*) > COUNT(t.ts) THEN 1 ELSE 0 END AS buckets "
                     f"{frm} {where}")
        rows_sql = (f"SELECT {bucket_expr} AS bucket_start, COUNT(*) AS count {frm} {where} "
                    f"GROUP BY {bucket_expr} ORDER BY bucket_start LIMIT {MAX_BUCKETS}")
        totals = run_query(total_sql, qp)[0]
        rows = run_query(rows_sql, qp) if totals["n"] else []
    except Exception as exc:
        log.exception("trend failed")
        return not_checkable("trend", dataset, params, str(exc))
    covered = sum(row["count"] for row in rows)
    result_evidence = evidence("trend", dataset, params, rows_sql, scope, totals["n"],
                               len(rows), MAX_BUCKETS, covered < totals["n"])
    result_evidence["buckets_total"] = totals["buckets"]
    return {"results": clean_rows(rows), "evidence": result_evidence}


# ---------------------------------------------------------------------------
# Role prompts (appear in Claude Code as /mcp__log-insights__<name>)
# ---------------------------------------------------------------------------

@mcp.prompt()
def engineer(question: str) -> str:
    """Engineer view: what failed, where, and what happened just before and after."""
    return ENGINEER.format(question=question)


@mcp.prompt()
def team_lead(question: str) -> str:
    """Team lead view: recurring problems, how often, which components and teams."""
    return TEAM_LEAD.format(question=question)


@mcp.prompt()
def manager(question: str) -> str:
    """Manager view: short, prioritised risks and actions based on measured frequency."""
    return MANAGER.format(question=question)


if __name__ == "__main__":
    mcp.run()
