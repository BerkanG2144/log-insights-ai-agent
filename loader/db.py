"""Shared database helpers for the loader."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def connect() -> psycopg.Connection:
    """Open a connection to the local SereneDB using the values from .env."""
    return psycopg.connect(
        host=os.environ["SERENEDB_HOST"],
        port=int(os.environ["SERENEDB_PORT"]),
        user=os.environ["SERENEDB_USER"],
        password=os.environ["SERENEDB_PASSWORD"],
        dbname=os.environ["SERENEDB_DB"],
        autocommit=True,
    )


if __name__ == "__main__":
    with connect() as conn:
        print(conn.execute("SELECT 1").fetchone())
