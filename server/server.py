"""MCP server exposing log analysis tools over SereneDB.

Tables and tool contracts are defined in docs/schema.md.
Run via Claude Code (stdio transport); never print to stdout.
"""

import logging
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from mcp.server import MCPServer
from psycopg.rows import dict_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# stdout is reserved for the MCP protocol, so log to stderr only.
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("log-insights")

mcp = MCPServer("log-insights")


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


if __name__ == "__main__":
    mcp.run()
