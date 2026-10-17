# log-insights-ai-agent

AI agent that turns log data into role-specific insights for engineers, team leads and managers. Built for the SereneDB challenge “Making Sense of Logs – The Right Insights for the Right People” at the National AI Hackathon 2026.

The database searches and calculates; the agent explains. A Python loader imports the complete BGL and OpenStack corpora into a local SereneDB and builds full-text indexes. An MCP server exposes a small set of parameterized search and summary tools. Claude (via Claude Code) chooses the tools, receives the results together with an evidence record (executed SQL, scope, counts, truncation), and answers in one of three roles.

```text
Question ──► Claude Code ──► MCP server (server/server.py) ──► SereneDB (SQL, full-text index)
   ▲                              │  tools + evidence record          │
   └──── role-specific answer ◄───┴──────────── rows, counts ◄────────┘
```

| Part | Path |
| --- | --- |
| Loader, schema, validation, ownership table | `loader/` |
| Shared data and tool contract | `docs/schema.md` |
| MCP server (tools) | `server/server.py` |
| Role prompts and evidence rules | `server/roles.py` |
| Worked investigation | `docs/worked_investigation.md` |
| Tests and checks | `tests/` |

## Quick start

1. Start SereneDB with Docker (password and `/data` mount as below).
2. Install the Python dependencies and create `.env`.
3. Place the raw datasets under `data/full/` and run the loader.
4. Register the MCP server in Claude Code and ask a question per role.

Each step is described below.

## Local setup

Requires Python 3.12 or newer (tested with 3.12 on Linux and 3.13 on Windows), Docker and the raw BGL/OpenStack datasets. Tested locally with SereneDB 26.10.1. From the repository root:

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

**Windows (PowerShell)**

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` holds the five `SERENEDB_*` connection values. The defaults in `.env.example` match the Docker command below (user `postgres`, password `hackathon`, host `127.0.0.1`, port `7890`). Use `127.0.0.1`, not `localhost` (some systems resolve `localhost` to IPv6 first). The loader and the server resolve `.env` relative to the repository, regardless of the calling directory. The data and `.env` are ignored by Git.

Place the original, extracted datasets at these paths:

```text
data/full/BGL/BGL.log
data/full/OpenStack/openstack_normal1.log
data/full/OpenStack/openstack_normal2.log
data/full/OpenStack/openstack_abnormal.log
data/full/OpenStack/anomaly_labels.txt
```

Original archives: [BGL](https://zenodo.org/records/8196385/files/BGL.zip?download=1), [OpenStack](https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1). Use the full datasets here, not the 2,000-line samples.

Verify the extracted OpenStack logs with `sha256sum data/full/OpenStack/*.log` (PowerShell: `Get-FileHash data\full\OpenStack\*.log`). Expected SHA-256 fingerprints from the original archive (archive MD5: `66bd42c07837a094d9b0ea2d036b5713`):

```text
7ab718fbb2f2b804893955cecf37ad9533cfa0efaf5b03009474d5bb019b6af4  openstack_abnormal.log
4e4d47347bdae198056bb3b0a8a755e1cb0100d6c6a30bbd4058684234769199  openstack_normal1.log
3c51741dcea1fb0731d1f86588b12587707e7abea01e725ee16c9441b8b68db7  openstack_normal2.log
```

An earlier local `normal1` copy contained `w` instead of `ERROR` at line 27179. That copy is not the original corpus. Full-corpus validation expects 194 ERROR rows, no missing levels and no `variant_level` rows; restore the original input rather than relaxing these checks.

### Start SereneDB

For a **new** container, run this from the repository root. It sets the password used in `.env.example` and mounts the project's `data/` folder at `/data`, so SereneDB can read the prepared files:

**Linux / macOS**

```bash
mkdir -p data
docker run -d --name serenedb \
  -p 127.0.0.1:7890:7890 \
  -e POSTGRES_PASSWORD=hackathon \
  -v serenedb-data:/var/lib/serenedb \
  -v "$PWD/data":/data \
  serenedb/serenedb:latest
```

**Windows (PowerShell)**

```powershell
New-Item -ItemType Directory -Force data | Out-Null
docker run -d --name serenedb -p 127.0.0.1:7890:7890 -e POSTGRES_PASSWORD=hackathon -v serenedb-data:/var/lib/serenedb -v "${PWD}\data:/data" serenedb/serenedb:latest
```

If the container already exists with this mount, use `docker start serenedb` instead (with Docker Desktop on Linux possibly `docker --context desktop-linux start serenedb`). If you use a different password or none, change `SERENEDB_PASSWORD` in `.env` accordingly. The mounted host directory must be the same directory passed to `--data-dir` (the default is this project's `data/`). `latest` may change; the verified runtime version is also recorded in the validation report.

## Run the loader

```bash
python -m loader.db
python -m loader.load
```

The first command should print `(1,)`. The second streams the input into CSVs, verifies SHA-256 fingerprints, creates and loads the four agreed tables in one transaction, validates the full corpus, then creates and refreshes the search indexes. A successful run ends with `Success: 54 SQL checks passed.` Progress is printed during preparation. Allow disk space for the CSV exports, database tables and indexes in addition to the original files.

Useful separate stages:

```bash
python -m loader.load --prepare-only
python -m loader.load --import-only
python -m loader.validate
```

`--prepare-only` needs no running database. `--import-only` checks that the input files and CSVs still match the manifest. `loader.validate` reruns the SQL checks, including index readiness. Each failing stage exits with a nonzero status.

Existing loader tables are refused by default. To deliberately rebuild these four tables and their indexes:

```bash
python -m loader.load --import-only --replace
```

A failed import or replacement rolls back the four-table transaction. Index creation follows the committed import in a separate transaction. If index creation fails, the validated data remains loaded. Index creation can also be deferred with `--skip-indexes` and run later with `python -m loader.load --indexes-only`; do not rerun the data import just to build indexes.

Optional read-only check of the trend statistics used by the agent (expects the full corpus):

```bash
python tests/check_trend_stats.py
```

It should print `all checks passed`.

## Start the agent (MCP server in Claude Code)

The MCP server is a stdio server (`server/server.py`, Python `mcp` SDK 2.x). It reads the connection from `.env`. We use it with [Claude Code](https://docs.claude.com/en/docs/claude-code/overview); any MCP client that can start a stdio server works the same way.

Register it once, from the repository root, with the Python interpreter that has the requirements installed:

**Linux / macOS (with the `.venv` from above)**

```bash
claude mcp add log-insights -- "$PWD/.venv/bin/python" "$PWD/server/server.py"
```

**Windows (PowerShell)**

```powershell
claude mcp add log-insights -- python "$PWD\server\server.py"
```

Optional, as recommended by the challenge: the SereneDB docs MCP for development questions.

```bash
claude mcp add --transport http serenedb-docs https://api.serenedb.com/mcp
```

Then start `claude` in the repository folder and type `/mcp`: `log-insights` should be connected with 5 tools. Quick test: `Call the ping tool of the log-insights server.` → `{"ok": true}`.

Ask a question in a role with the role prompts (they appear as slash commands; type the question after the command):

```text
/mcp__log-insights__engineer In OpenStack, investigate Error during ComputeManager._run_image_cache_manager_pass. What failed, what happened immediately before and after a representative error, and what cause can the logs establish?
/mcp__log-insights__team_lead Across the full BGL dataset, which FATAL problems recur, how often, and which components and teams should investigate first?
/mcp__log-insights__manager Across BGL and OpenStack, which observed problems deserve attention first and what should happen next?
```

Use `/clear` between unrelated questions. Tested with Claude Sonnet 5.5 (effort medium) and Claude Opus 5.5 in Claude Code 2.1.302 on Windows and Linux. After changing server code, restart Claude Code.

## Tools

All tools take `dataset` = `bgl` or `openstack`. Values are passed as SQL parameters; column names and buckets come from fixed whitelists. Every tool returns `{"results": [...], "evidence": {...}}`.

| Tool | Purpose | Main inputs | Returns |
| --- | --- | --- | --- |
| `search_logs` | Full-text search over the log message via the inverted index (`@@`), ranked by BM25 | `text`; optional `component`, `level`, `team`, `from_ts`, `to_ts`, `label` (bgl), `limit` (default 20, max 100) | Matching rows with `score` and `team`; total matches in `rows_matched` |
| `nearby_events` | Lines just before and after one anchor line, in time order | `line_no` (+ `source_file` for openstack) or `ts`; `window_seconds` (default 60, max 3600); optional `node` (bgl) or `request_id` / `instance_id` (openstack); `limit` (default 50, max 200) | Half of the limit before and half after the anchor, each with `offset_s`; OpenStack stays in the anchor's file |
| `count_by` | Counts per group over the complete filtered data, largest first | `group_by` (bgl: component, level, team, label, node, rack; openstack: component, level, team, service, http_status, instance_id, source_file); same filters as `search_logs` (`text` = substring); `limit` (default 20, max 100) | `[{key, count}]`, `groups_total` |
| `trend` | Counts per time bucket over the complete filtered data | `bucket` (`minute`, `hour`, `day`); same filters as `count_by` | `[{bucket_start, count}]` (max 1,000 buckets) plus summary fields computed in the database: `active_buckets`, `first_bucket`, `last_bucket`, `peak_bucket`, `peak_count`, `peak_share`, `null_timestamp_rows` |
| `ping` | Connection check | – | `{"ok": true}` |

`team` is resolved through the fictional `team_ownership` table. Full details: [docs/schema.md](docs/schema.md).

### Evidence record

Every answer can be checked against the queries that actually ran:

```json
{
  "query_id": "Q8",
  "tool": "trend",
  "dataset": "bgl",
  "params": {"bucket": "day", "label": "APPSEV"},
  "sql": "(shortened) SELECT date_trunc('day', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON ... WHERE t.label = %(label)s GROUP BY ... ORDER BY bucket_start LIMIT 1000",
  "scope": "bgl_logs, label = APPSEV",
  "rows_matched": 49651,
  "rows_returned": 67,
  "limit": 1000,
  "truncated": false,
  "status": "ok",
  "active_buckets": 67,
  "first_bucket": "2005-07-20 00:00:00",
  "last_bucket": "2006-01-03 00:00:00",
  "peak_bucket": "2005-11-26 00:00:00",
  "peak_count": 3466,
  "peak_share": 0.069807
}
```

- `status`: `ok`, `empty` (query ran, nothing matched) or `not_checkable` (with `reason`, e.g. unknown column, missing `source_file`, database error). Missing evidence is reported, never filled with guesses.
- `truncated` is `true` whenever not all matching rows or groups were returned.

## Roles

Same agent, same data, same tools for all roles. `server/roles.py` defines shared evidence rules and one prompt per role; what changes is the question, the evidence selected and the recommendation.

**Shared rules (all roles):** every number comes from a tool result and is cited as `(query_id, scope)`; answers separate *Observed*, *Possible explanation (hypothesis)*, *Unknown* and *Recommendation*; counts are log lines, not incidents; statements about one problem (recurring, burst, spread) need a query filtered to that problem, otherwise “not measured”; examples are never generalised; trend statistics are taken from the tool, never computed by the model; no invented cost, downtime or customer impact; every answer ends with an evidence list.

| Role | Question it answers | Typical tool flow | Answer |
| --- | --- | --- | --- |
| Engineer | What failed, where, what happened just before and after? | `search_logs` → `nearby_events` → `count_by`/`trend` for the real frequency | Failing component/node, quoted lines with `line_no`, sequence with offsets, cause as hypothesis (with number of inspected cases), next diagnostic check |
| Team lead | Which problems recur, how often, which components and teams? | `count_by` (team, component, label) → `trend` per discussed problem → `count_by` node/rack for spread → examples | Table with log lines, share, active days, first/last day, owner; pattern per problem; what to investigate first |
| Manager | What deserves attention first and what next? | Fixed candidate set (5 largest BGL labels, 2 largest OpenStack components for ERROR and for WARNING) → `trend` for every candidate | Ranking rule, top 3 assessable recurring/limited problems, separate burst and OpenStack blocks, actions, what the data does not tell |

The manager classification is an agreed heuristic, not a validated risk model: dataset shorter than 7 days → “recurrence not assessable”; `peak_share` > 0.5 → burst; ≥ 5 active days → recurring; otherwise limited. “Still active” means observed within the last 7 days of that dataset.

## Worked investigation

See [docs/worked_investigation.md](docs/worked_investigation.md): one real pattern in BGL, with the questions, tool calls, executed queries, results and the answer and recommended action for each role.

## Known limitations

- Full-text search matches words, not phrases: “Error during ComputeManager” returns 4,077 word matches, while the exact message occurs 8 times. Measured claims use `count_by`/`trend`, whose `text` filter is a case-insensitive substring match on the base table. The `scope` field states which method ran.
- Counts are log lines, not incidents. One event can write one line per node (e.g. ~510 lines per APPREAD burst) or a multi-line traceback.
- Burst counts depend on the bucket size (minute, hour, day). “Active days” are days with at least one line, not the calendar span (BGL: 215 active days, 2005-06-03 to 2006-01-04; OpenStack: 3 active days, 2017-05-14 to 2017-05-17).
- OpenStack covers only a few days, so its recurrence cannot be assessed and it is not directly comparable with BGL.
- The team ownership mapping is fictional. Cost, downtime and customer impact are not in the logs and are never estimated.
- Interpretations of alert labels and causes rest on the lines actually inspected and are marked as hypotheses.
- The agent's wording can vary between runs; numbers come from the tools. Tested with Claude Sonnet 5.5 and Opus 5.5.
- Not implemented (optional in the challenge): agent-managed indexes, huge remote datasets, traces/metrics, row-level security, phrase or fuzzy search.


## Data contract and verification

See [docs/schema.md](docs/schema.md) for the shared contract and [loader/schema.sql](loader/schema.sql) for the executable DDL. The tables are `bgl_logs`, `openstack_logs`, `openstack_anomaly_vms` and `team_ownership`.

- Expected corpus: 4,747,963 BGL rows and 207,820 OpenStack rows (52,312 normal1 / 137,074 normal2 / 18,434 abnormal).
- BGL retains the 306 `variant_kill` and ten `variant_other` records. The 104,215 `NULL` type markers and 34,470 absent messages are ordinary supported rows. Time is taken from the precise timestamp without assuming a timezone.
- OpenStack retains missing optional fields as SQL NULL, including 184 traceback lines without a request-context bracket. Their indentation and separate line numbers are preserved. The parser defensively retains a `w` level as NULL with `variant_level`, rather than guessing a severity; the verified original corpus contains no such rows.
- `raw_line` preserves the original log text, including trailing spaces, excluding only the record's LF/CRLF terminator. `line_no` is one-based within the original file.
- Unexpected parsing failures retain the raw row in the CSV and record a reason in `parse_errors.jsonl`. They block database import. Invalid UTF-8 aborts preparation visibly. No line is silently skipped.
- Four labelled VMs are kept separately for evaluation. Each has 28 raw UUID mentions but only 25 explicit instance tags, all in `abnormal`. Both counts are checked separately; `instance_id` keeps its agreed meaning. Labels are not exposed to the agent as ground-truth hints.
- [loader/team_ownership.csv](loader/team_ownership.csv) contains **fictional teams** from the agreed mapping, not real ownership facts.

Local outputs under `data/processed/`:

CSV exports are stored in immutable `run-<id>/` directories. `manifest.json` points to the current generation. Reusing a filename after replacing its contents exposed a stale file view through the local Docker Desktop mount; using a fresh path for each preparation avoids that issue. Old generations are retained so previous evidence can still be inspected.

| File | Purpose |
| --- | --- |
| `manifest.json` | Input/CSV hashes, row counts, parse statuses and representative parsed records |
| `parse_errors.jsonl` | Unexpected parsing failures and original source line numbers (empty on success) |
| `import_report.json` | SQL checks before publication, with an explicit `committed` flag |
| `validation_report.json` | Checks against committed data, executed SQL, bound parameters, results and database version |

Counts describe log entries, not independent incidents. Dataset labels, severity and root-cause hypotheses are different concepts.

## Search after import

SereneDB full-text queries use the index name. Base tables remain available for complete aggregations:

```sql
SELECT line_no, ts, node, message
FROM bgl_logs_message_idx
WHERE message @@ 'ciod'
ORDER BY line_no
LIMIT 20;

SELECT source_file, COUNT(*)
FROM openstack_logs
GROUP BY source_file;
```

The index dictionary lowercases tokens and records frequencies/positions for BM25 and phrase queries. It does not apply stemming. See [loader/indexes.sql](loader/indexes.sql). The limited search result is not a frequency estimate; use a complete count query for measured claims.

## Tests

```bash
python -m unittest discover -s tests -v
LOADER_DB_TESTS=1 python -m unittest discover -s tests -v
```

The first command runs parser/preparation tests and skips DB tests. The second also exercises CSV round-tripping, composite keys, NULLs, search refresh/BM25, duplicate-import refusal and replacement rollback on the local SereneDB. DB tests create uniquely named `loader_test_*` schemas and remove them afterwards; they do not use the application's tables.

## Dataset attribution

Loghub is a research dataset collection. Cite Zhu et al., *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics*, ISSRE 2023; for BGL also Oliner & Stearley, *What Supercomputers Say*, DSN 2007. OpenStack's dataset README additionally references Du et al., *DeepLog*, CCS 2017. See the original [Loghub repository](https://github.com/logpai/loghub) for dataset documentation and usage terms.
