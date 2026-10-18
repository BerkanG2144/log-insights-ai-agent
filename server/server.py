"""MCP server exposing log analysis tools over SereneDB.

Tables and tool contracts are defined in docs/schema.md.
Run via Claude Code (stdio transport); never print to stdout.
"""

import difflib
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
from mcp.types import ToolAnnotations
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

# Filters with a small set of valid values: checked against the data and listed by
# describe_dataset. node, rack, instance_id etc. have too many values for that.
VALUE_FILTERS = {
    "bgl": ["level", "component", "team", "label"],
    "openstack": ["level", "component", "team"],
}

# Documented facts (docs/schema.md, README), kept apart from measured values.
TEAM_NOTE = ("team comes from the team_ownership table, a fictional mapping made for this "
             "project; it does not describe real organisational responsibility.")
TEXT_NOTE = ("text: search_logs matches words via the full-text index (phrase=true: adjacent "
             "ordered tokens); count_by and trend match a case-insensitive substring.")
NOTES = {
    "bgl": {
        "source": "BlueGene/L supercomputer logs (Loghub), complete file BGL.log.",
        "label": "Alert category from the first field of each line; '-' means a line "
                 "without an alert label. Only bgl has labels.",
        "level": "Severity as written in the log.",
        "team": TEAM_NOTE,
        "text": TEXT_NOTE,
        "not_listed": "node and rack have too many values to list; use count_by "
                      "group_by='node' or 'rack'. node also works in nearby_events.",
    },
    "openstack": {
        "source": "OpenStack Nova logs (Loghub), complete files normal1, normal2 and "
                  "abnormal; the three files are separate recordings (source_file).",
        "label": "Not available for openstack.",
        "level": "Severity as written in the log.",
        "team": TEAM_NOTE,
        "text": TEXT_NOTE,
        "not_listed": "service, http_status, instance_id and source_file are available "
                      "via count_by; request_id and instance_id also in nearby_events.",
    },
}

# Every tool only reads. Idempotence describes side effects, not result equality.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                            idempotent_hint=True, open_world_hint=False)

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


def add_normalized(result_evidence: dict, normalized: dict) -> None:
    """Show filter values whose spelling was corrected (params keep the input)."""
    if normalized:
        result_evidence["normalized_filters"] = normalized


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
        # Aggregation tools filter the base table by substring; search_logs uses the
        # full-text index instead. The scope text states which one was used.
        clauses.append("LOWER(t.message) LIKE %(text)s")
        params["text"] = f"%{text.lower()}%"
        scope.append(f"message contains '{text}' (substring)")
    if component:
        clauses.append("t.component = %(component)s")
        params["component"] = component
        scope.append(f"component = {component}")
    if level:
        clauses.append("t.level = %(level)s")
        params["level"] = level
        scope.append(f"level = {level}")
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


def check_label(dataset: str, label: str | None) -> str | None:
    if label and dataset != "bgl":
        return "label exists only in bgl"
    return None


class FilterError(ValueError):
    """A filter value that does not occur in the dataset."""


def known_values(dataset: str, name: str) -> list[str]:
    """All stored values of one filter in VALUE_FILTERS (NULL excluded)."""
    if name == "team":
        sql = "SELECT DISTINCT team AS v FROM team_ownership WHERE dataset = %(dataset)s"
        rows = run_query(sql, {"dataset": dataset})
    else:
        # name comes from VALUE_FILTERS, so it is safe to inline.
        table = DATASETS[dataset]["table"]
        rows = run_query(f"SELECT DISTINCT {name} AS v FROM {table} WHERE {name} IS NOT NULL")
    return sorted(row["v"] for row in rows if row["v"] is not None)


def resolve_filters(dataset: str, **filters) -> tuple[dict, dict]:
    """Map filter values to their stored spelling.

    Returns (resolved values, normalized) where normalized records every value that
    was changed (e.g. label 'appread' -> 'APPREAD'). A value that matches nothing,
    even ignoring case, raises FilterError with suggestions instead of returning an
    empty result that looks like "zero lines".
    """
    resolved, normalized = {}, {}
    for name, value in filters.items():
        resolved[name] = value
        if not value:
            continue
        values = known_values(dataset, name)
        if value in values:
            continue
        same = [v for v in values if v.lower() == value.lower()]
        if len(same) == 1:
            resolved[name] = same[0]
            normalized[name] = f"{value} -> {same[0]}"
            continue
        by_lower = {v.lower(): v for v in values}
        close = difflib.get_close_matches(value.lower(), list(by_lower), n=3, cutoff=0.6)
        hint = (f"did you mean: {', '.join(by_lower[c] for c in close)}" if close
                else f"valid values: {', '.join(values)}")
        raise FilterError(f"unknown {name} '{value}' in {dataset}; {hint} "
                          "(describe_dataset lists all values)")
    return resolved, normalized


def clamp(value: int | None, default: int, maximum: int) -> int:
    if value is None or value < 1:
        return default
    return min(value, maximum)


def select_columns(dataset: str) -> str:
    return ", ".join(f"t.{c}" for c in DATASETS[dataset]["columns"])


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(title="Check database connection", annotations=READ_ONLY)
def ping() -> dict:
    """Check that the MCP server can reach SereneDB. Returns {"ok": true} on success."""
    sql = "SELECT 1 AS ok"
    try:
        rows = run_query(sql)
        return {"ok": rows[0]["ok"] == 1, "sql": sql}
    except Exception as exc:  # report the error to the agent instead of crashing
        log.exception("ping failed")
        return {"ok": False, "sql": sql, "error": str(exc)}


@mcp.tool(title="Describe a dataset", annotations=READ_ONLY)
def describe_dataset(dataset: str) -> dict:
    """Overview of one dataset: size, time range and the valid filter values.

    Call this first when you are unsure which filter values exist or how they are
    spelled. dataset: "bgl" or "openstack".
    Returns in results (measured in the database): rows, first_ts, last_ts,
    null_timestamp_rows, the values of level, component, team and (bgl only) label
    with their line counts. metadata holds the configured group_by options of
    count_by; these are capabilities, not database measurements.
    notes holds documented explanations (meaning of fields, fictional teams); they
    are project documentation, not measurements.
    Use the other tools for the actual investigation.
    """
    params = {}
    if (err := check_dataset(dataset)):
        return not_checkable("describe_dataset", dataset, params, err)
    table = DATASETS[dataset]["table"]
    frm = base_from(dataset)
    qp = {"dataset": dataset}
    total_sql = (f"SELECT COUNT(*) AS n, MIN(t.ts) AS first_ts, MAX(t.ts) AS last_ts, "
                 f"COUNT(*) - COUNT(t.ts) AS null_ts {frm}")
    # Filter names come from VALUE_FILTERS, so they are safe to inline.
    value_sqls = {
        name: (f"SELECT {'o.team' if name == 'team' else 't.' + name} AS value, "
               f"COUNT(*) AS count {frm} GROUP BY 1 ORDER BY count DESC, value")
        for name in VALUE_FILTERS[dataset]
    }
    try:
        totals = run_query(total_sql, qp)[0]
        values = {name: run_query(sql, qp) for name, sql in value_sqls.items()}
    except Exception as exc:
        log.exception("describe_dataset failed")
        return not_checkable("describe_dataset", dataset, params, str(exc))
    results = {
        "rows": totals["n"],
        "first_ts": to_json(totals["first_ts"]),
        "last_ts": to_json(totals["last_ts"]),
        "null_timestamp_rows": totals["null_ts"],
        "values": {name: clean_rows(rows) for name, rows in values.items()},
    }
    sql = "; ".join([total_sql, *value_sqls.values()])
    returned = sum(len(rows) for rows in values.values())
    result_evidence = evidence("describe_dataset", dataset, params, sql,
                               f"{table}, all rows", totals["n"], returned, None, False)
    return {"results": results,
            "metadata": {"count_by_group_by": list(DATASETS[dataset]["group_by"])},
            "notes": NOTES[dataset], "evidence": result_evidence}


@mcp.tool(title="Search log messages", annotations=READ_ONLY)
def search_logs(dataset: str, text: str, component: str | None = None,
                level: str | None = None, team: str | None = None,
                from_ts: str | None = None, to_ts: str | None = None,
                label: str | None = None, limit: int = 20,
                phrase: bool = False) -> dict:
    """Full-text search over the log message, ranked by relevance (BM25).

    Use this to locate concrete evidence: specific errors, IPs, VM ids, request ids.
    dataset: "bgl" (BlueGene/L supercomputer) or "openstack" (Nova cloud logs).
    text: words to search for in the message (case-insensitive word match).
    phrase: default false (existing word search); true requires adjacent tokens in
    the given order via phraseto_tsquery. Token matching, not an exact substring.
    Use phrase=true for a known multi-word error message.
    Optional filters: component, level (e.g. FATAL, ERROR), team (from the ownership
    table), from_ts / to_ts (ISO timestamps), label (bgl only: alert category such as
    APPREAD or KERNDTLB, "-" = no alert). limit: default 20, max 100.
    component, level, team and label are matched ignoring case; an unknown value
    returns not_checkable with suggestions (describe_dataset lists all values).
    Returns the most relevant matching rows plus an evidence record with the exact SQL,
    the total number of matches and whether the list was truncated.
    """
    params = {"text": text, "component": component, "level": level, "team": team,
              "from_ts": from_ts, "to_ts": to_ts, "label": label, "limit": limit,
              "phrase": phrase}
    if (err := check_dataset(dataset) or check_label(dataset, label)):
        return not_checkable("search_logs", dataset, params, err)
    limit = clamp(limit, 20, 100)
    params["limit"] = limit
    # The inverted index is queried by its own name (see loader/indexes.sql).
    idx = DATASETS[dataset]["table"] + "_message_idx"
    try:
        filters, normalized = resolve_filters(dataset, component=component, level=level,
                                              team=team, label=label)
        component, level = filters["component"], filters["level"]
        team, label = filters["team"], filters["label"]
        query_text = "phraseto_tsquery(%(text)s)" if phrase else "%(text)s"
        clauses = [f"{idx}.message @@ {query_text}"]
        qp: dict = {"text": text, "dataset": dataset}
        mode = "full-text phrase, adjacent ordered tokens" if phrase else "full-text"
        scope = [f"message matches '{text}' ({mode})"]
        if component:
            clauses.append(f"{idx}.component = %(component)s")
            qp["component"] = component
            scope.append(f"component = {component}")
        if level:
            clauses.append(f"{idx}.level = %(level)s")
            qp["level"] = level
            scope.append(f"level = {level}")
        if team:
            clauses.append(f"{idx}.component IN (SELECT component FROM team_ownership "
                           "WHERE dataset = %(dataset)s AND team = %(team)s)")
            qp["team"] = team
            scope.append(f"team = {team}")
        if label:
            clauses.append(f"{idx}.label = %(label)s")
            qp["label"] = label
            scope.append(f"label = {label}")
        if from_ts:
            clauses.append(f"{idx}.ts >= %(from_ts)s")
            qp["from_ts"] = parse_ts(from_ts, "from_ts")
            scope.append(f"ts >= {from_ts}")
        if to_ts:
            clauses.append(f"{idx}.ts <= %(to_ts)s")
            qp["to_ts"] = parse_ts(to_ts, "to_ts")
            scope.append(f"ts <= {to_ts}")
        where = "WHERE " + " AND ".join(clauses)
        columns = ", ".join(f"{idx}.{c}" for c in DATASETS[dataset]["columns"])
        count_sql = f"SELECT COUNT(*) AS n FROM {idx} {where}"
        # Tie-breaker on the line position keeps results identical between runs.
        tie = (f"{idx}.source_file, {idx}.line_no" if dataset == "openstack"
               else f"{idx}.line_no")
        rows_sql = (f"SELECT {columns}, BM25({idx}.tableoid) AS score FROM {idx} {where} "
                    f"ORDER BY score DESC, {tie} LIMIT {limit}")
        matched = run_query(count_sql, qp)[0]["n"]
        rows = run_query(rows_sql, qp) if matched else []
        if rows:
            owners = run_query("SELECT component, team FROM team_ownership "
                               "WHERE dataset = %(dataset)s", {"dataset": dataset})
            team_of = {o["component"]: o["team"] for o in owners}
            for row in rows:
                row["team"] = team_of.get(row.get("component"))
        scope = f"{idx} ({DATASETS[dataset]['table']}), " + ", ".join(scope)
    except FilterError as exc:
        return not_checkable("search_logs", dataset, params, str(exc))
    except Exception as exc:
        log.exception("search_logs failed")
        return not_checkable("search_logs", dataset, params, str(exc))
    result_evidence = evidence("search_logs", dataset, params, rows_sql, scope,
                               matched, len(rows), limit, matched > len(rows))
    add_normalized(result_evidence, normalized)
    return {"results": clean_rows(rows), "evidence": result_evidence}


@mcp.tool(title="Show events around a line", annotations=READ_ONLY)
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
    If the window holds more lines than limit, the lines closest to the anchor are
    returned (half before, half after) and truncated is true.
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
        if dataset == "openstack" and line_no is not None:
            # The three OpenStack files are separate recordings: stay in the anchor's file.
            extra["source_file"] = source_file
        where, qp, scope = build_where(
            dataset, from_ts=(anchor - delta).isoformat(sep=" "),
            to_ts=(anchor + delta).isoformat(sep=" "), extra=extra)
        frm = base_from(dataset)
        count_sql = f"SELECT COUNT(*) AS n {frm} {where}"
        # Keep the anchor in the middle: the lines closest before it and closest after it,
        # instead of only the earliest lines of the window.
        qp["anchor"] = anchor
        half = limit // 2
        if line_no is not None:
            # Lines with the same timestamp (e.g. a traceback) are split by line_no,
            # so lines written after the anchor count as "after".
            qp["anchor_line"] = line_no
            before_cond = ("(t.ts < %(anchor)s OR "
                           "(t.ts = %(anchor)s AND t.line_no <= %(anchor_line)s))")
            after_cond = ("(t.ts > %(anchor)s OR "
                          "(t.ts = %(anchor)s AND t.line_no > %(anchor_line)s))")
        else:
            before_cond, after_cond = "t.ts <= %(anchor)s", "t.ts > %(anchor)s"
        before_sql = (f"SELECT {select_columns(dataset)}, o.team {frm} {where} "
                      f"AND {before_cond} ORDER BY t.ts DESC, t.line_no DESC LIMIT {half}")
        after_sql = (f"SELECT {select_columns(dataset)}, o.team {frm} {where} "
                     f"AND {after_cond} ORDER BY t.ts, t.line_no LIMIT {limit - half}")
        rows_sql = before_sql + "; " + after_sql
        matched = run_query(count_sql, qp)[0]["n"]
        rows = []
        if matched:
            rows = run_query(before_sql, qp)[::-1] + run_query(after_sql, qp)
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


@mcp.tool(title="Count log lines per group", annotations=READ_ONLY)
def count_by(dataset: str, group_by: str, text: str | None = None,
             component: str | None = None, level: str | None = None,
             team: str | None = None, from_ts: str | None = None,
             to_ts: str | None = None, label: str | None = None,
             limit: int = 20) -> dict:
    """Count log lines per group, largest groups first.

    Use this for overviews: which components, nodes, teams or levels produce the most
    lines or errors. Combine with filters (e.g. level="FATAL") to focus.
    group_by for bgl: component, level, team, label, node, rack.
    group_by for openstack: component, level, team, service, http_status,
    instance_id, source_file.
    Filters: text (substring of the message), component, level, team, from_ts, to_ts,
    label (bgl only: alert category such as APPREAD, "-" = no alert).
    component, level, team and label are matched ignoring case; an unknown value
    returns not_checkable with suggestions (describe_dataset lists all values).
    limit: number of groups, default 20, max 100.
    Returns [{key, count}] plus evidence (rows_matched = all counted rows).
    """
    params = {"group_by": group_by, "text": text, "component": component,
              "level": level, "team": team, "from_ts": from_ts, "to_ts": to_ts,
              "label": label, "limit": limit}
    if (err := check_dataset(dataset) or check_label(dataset, label)):
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
        filters, normalized = resolve_filters(dataset, component=component, level=level,
                                              team=team, label=label)
        label = filters.pop("label")
        where, qp, scope = build_where(dataset, text, from_ts=from_ts, to_ts=to_ts,
                                       extra={"label": label}, **filters)
        frm = base_from(dataset)
        # COUNT(DISTINCT) ignores NULL, so add 1 if a NULL group exists.
        total_sql = (f"SELECT COUNT(*) AS n, COUNT(DISTINCT {key}) "
                     f"+ CASE WHEN COUNT(*) > COUNT({key}) THEN 1 ELSE 0 END AS groups "
                     f"{frm} {where}")
        rows_sql = (f"SELECT {key} AS key, COUNT(*) AS count {frm} {where} "
                    f"GROUP BY {key} ORDER BY count DESC LIMIT {limit}")
        totals = run_query(total_sql, qp)[0]
        rows = run_query(rows_sql, qp) if totals["n"] else []
    except FilterError as exc:
        return not_checkable("count_by", dataset, params, str(exc))
    except Exception as exc:
        log.exception("count_by failed")
        return not_checkable("count_by", dataset, params, str(exc))
    # Truncated if the returned groups do not cover every counted row.
    covered = sum(row["count"] for row in rows)
    result_evidence = evidence("count_by", dataset, params, rows_sql, scope,
                               totals["n"], len(rows), limit, covered < totals["n"])
    result_evidence["groups_total"] = totals["groups"]
    add_normalized(result_evidence, normalized)
    return {"results": clean_rows(rows), "evidence": result_evidence}


@mcp.tool(title="Count log lines over time", annotations=READ_ONLY)
def trend(dataset: str, bucket: str = "hour", text: str | None = None,
          component: str | None = None, level: str | None = None,
          team: str | None = None, from_ts: str | None = None,
          to_ts: str | None = None, label: str | None = None) -> dict:
    """Count log lines per time bucket to see when something started, peaked or stopped.

    bucket: "minute", "hour" or "day". Use from_ts / to_ts to zoom in before using
    "minute". Filters: text (substring of the message), component, level, team, label
    (bgl only: alert category such as APPREAD, "-" = no alert).
    component, level, team and label are matched ignoring case; an unknown value
    returns not_checkable with suggestions (describe_dataset lists all values).
    Returns [{bucket_start, count}] in time order (max 1000 buckets) plus evidence.
    Buckets with zero lines are not listed.
    The evidence also holds summary fields computed in the database over ALL filtered
    lines (not only the returned buckets): active_buckets (buckets with lines; active
    days when bucket="day"), first_bucket, last_bucket, peak_bucket (earliest on ties),
    peak_count, peak_share (= peak_count / rows_matched) and null_timestamp_rows.
    Use these fields instead of computing them yourself.
    """
    params = {"bucket": bucket, "text": text, "component": component, "level": level,
              "team": team, "from_ts": from_ts, "to_ts": to_ts, "label": label}
    if (err := check_dataset(dataset) or check_label(dataset, label)):
        return not_checkable("trend", dataset, params, err)
    if bucket not in BUCKETS:
        return not_checkable("trend", dataset, params,
                             f"bucket must be one of: {', '.join(sorted(BUCKETS))}")
    try:
        filters, normalized = resolve_filters(dataset, component=component, level=level,
                                              team=team, label=label)
        label = filters.pop("label")
        where, qp, scope = build_where(dataset, text, from_ts=from_ts, to_ts=to_ts,
                                       extra={"label": label}, **filters)
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
        stats = trend_stats(frm, where, qp, bucket_expr, totals["n"])
    except FilterError as exc:
        return not_checkable("trend", dataset, params, str(exc))
    except Exception as exc:
        log.exception("trend failed")
        return not_checkable("trend", dataset, params, str(exc))
    covered = sum(row["count"] for row in rows)
    result_evidence = evidence("trend", dataset, params, rows_sql, scope, totals["n"],
                               len(rows), MAX_BUCKETS, covered < totals["n"])
    result_evidence["buckets_total"] = totals["buckets"]
    result_evidence.update({k: to_json(v) for k, v in stats.items()})
    add_normalized(result_evidence, normalized)
    return {"results": clean_rows(rows), "evidence": result_evidence}


def trend_stats(frm: str, where: str, qp: dict, bucket_expr: str, rows_matched: int) -> dict:
    """Summary of the time distribution over ALL filtered lines (before the bucket limit).

    Lines without a timestamp are counted separately and never form a bucket.
    """
    stats = {"active_buckets": 0, "first_bucket": None, "last_bucket": None,
             "peak_bucket": None, "peak_count": None, "peak_share": None,
             "null_timestamp_rows": 0}
    if not rows_matched:
        return stats
    ts_where = f"{where} AND t.ts IS NOT NULL" if where else "WHERE t.ts IS NOT NULL"
    buckets = (f"SELECT {bucket_expr} AS bucket_start, COUNT(*) AS n "
               f"{frm} {ts_where} GROUP BY {bucket_expr}")
    summary = run_query(
        f"SELECT COUNT(*) AS active_buckets, MIN(b.bucket_start) AS first_bucket, "
        f"MAX(b.bucket_start) AS last_bucket, SUM(b.n) AS ts_rows FROM ({buckets}) b", qp)[0]
    stats["active_buckets"] = summary["active_buckets"] or 0
    stats["first_bucket"] = summary["first_bucket"]
    stats["last_bucket"] = summary["last_bucket"]
    stats["null_timestamp_rows"] = rows_matched - int(summary["ts_rows"] or 0)
    if stats["active_buckets"]:
        peak = run_query(
            f"SELECT b.bucket_start, b.n FROM ({buckets}) b "
            f"ORDER BY b.n DESC, b.bucket_start LIMIT 1", qp)[0]
        stats["peak_bucket"] = peak["bucket_start"]
        stats["peak_count"] = int(peak["n"])
        stats["peak_share"] = round(int(peak["n"]) / rows_matched, 6)
    return stats


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
