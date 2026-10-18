# Log Insights AI Agent: The Right Insights for the Right People

This project was built by a team of two students at the **National AI Hackathon 2026** for the SereneDB challenge **"Making Sense of Logs – The Right Insights for the Right People"**.

It is an AI agent that answers questions about large system logs and adapts the answer to the person asking: an **engineer**, a **team lead** or a **manager**. The agent (Claude in Claude Code) does not read raw log files. It works through a small set of tools in our own **MCP server**, which run parameterized SQL on the logs stored in **SereneDB**, and every answer comes with the queries that produced its numbers.

**The database searches and calculates; the agent explains.**

```text
Question ──► Claude Code ──► MCP server (server/server.py) ──► SereneDB (SQL, full-text index)
   ▲                              │  tools + evidence record          │
   └──── role-specific answer ◄───┴──────────── rows, counts ◄────────┘
```

The data are two public research log collections from [Loghub](https://github.com/logpai/loghub), imported completely:

- **BGL** – BlueGene/L supercomputer logs, 4,747,963 lines (2005–2006)
- **OpenStack** – OpenStack Nova cloud logs, 207,820 lines (2017)


---

## Demo-Video

You can watch the demo on YouTube: click [here](https://youtu.be/TODO) <!-- TODO: replace with the video link -->

The presentation slides are in [docs/slides.pdf](docs/slides.pdf).

<!-- Optional screenshots (e.g. the same question answered by the three roles in Claude Code):
<p align="center">
  <img src="docs/images/engineer.png"  alt="Engineer answer"  width="32%">
  <img src="docs/images/team_lead.png" alt="Team lead answer" width="32%">
  <img src="docs/images/manager.png"   alt="Manager answer"   width="32%">
</p>
-->


---

## Table of Contents

This README gives an overview of the project, describes the folder structure and the tech stack, explains step by step how to set up the database, import the data and start the agent, and documents the tools, roles, tests and known limitations.

1. [Project overview](#project-overview)
2. [Tech stack](#tech-stack)
3. [Folder and file structure](#folder-and-file-structure)
4. [Requirements](#requirements)
5. [How to set up and run the project](#how-to-set-up-and-run-the-project)
6. [How to use the agent](#how-to-use-the-agent)
7. [Tools and evidence record](#tools-and-evidence-record)
8. [Roles](#roles)
9. [Worked investigation](#worked-investigation)
10. [How to run test cases](#how-to-run-test-cases)
11. [Known limitations](#known-limitations)
12. [Data contract and verification](#data-contract-and-verification)
13. [Team](#team)
14. [Dataset attribution](#dataset-attribution)


---

## Project overview

The same log data matter differently to different people. An engineer needs the failing lines and what happened just before them. A team lead needs to know which problems keep coming back and who owns them. A manager needs a short, comparable ranking and a decision. All three should be able to trust the numbers.

### Key features

**1) Complete data in SereneDB**
- A Python loader imports the full BGL and OpenStack corpora (no samples), validates them with 54 SQL checks and builds full-text indexes.

**2) Search and analytics in one database**
- Full-text search with `@@` on SereneDB's inverted index, ranked by BM25, optionally as phrase search.
- Exact counts and time trends over all rows with SQL aggregations (`COUNT`, `GROUP BY`, `date_trunc`).

**3) Six read-only MCP tools instead of free SQL**
- `describe_dataset`, `search_logs`, `nearby_events`, `count_by`, `trend`, `ping`, all marked read-only via MCP tool annotations.
- Inputs are SQL parameters; column names and time buckets come from fixed whitelists.
- Filter values are checked against the data: wrong case is corrected and reported, unknown values return `not_checkable` with suggestions instead of an empty result.

**4) An evidence record for every result**
- Analysis results report a `query_id`, SQL exposed by the tool, input parameters, scope, matching and returned counts, truncation, and a status (`ok`, `empty`, `not_checkable`). This evidence is not a complete trace of all internal SQL or its actual bindings.

**5) Three roles, one agent**
- Engineer, team lead and manager use the same tools and data. Role prompts decide which evidence is collected and how the answer and the recommendation look.

**6) Honest answers**
- Every number is cited with its `query_id`. Answers separate *Observed*, *Possible explanation (hypothesis)*, *Unknown* and *Recommendation*. Cost, downtime and customer impact are never invented.


### Project process

- We first agreed on a shared data and tool contract (`docs/schema.md`) and then worked in parallel: **loader and data validation** on one side, **MCP server, tools and roles** on the other.
- All changes went through Git (pull before push, `.gitattributes` for consistent line endings between Windows and Linux).
- Every change was tested on **both machines** (Windows and Linux) against the complete data, and the role answers were checked against the tool results and reference values (`tests/check_trend_stats.py`). Where the model computed numbers itself and got them wrong, we moved the calculation into the database.
- We used AI coding assistants throughout the hackathon: Claude Code (Anthropic) and Codex (OpenAI). All results were checked against the tool outputs and the database.


---

## Tech stack

**Language**

- **Python** (3.12 or newer)

**Database**

- **SereneDB** (search and analytics database, PostgreSQL wire protocol on port 7890, running in **Docker**)
- Inverted index with `@@` full-text queries and **BM25** ranking

**Agent**

- **Claude Code** with **Claude Sonnet 5.5** (also tested with Claude Opus 5.5)
- **MCP** (Model Context Protocol) server with the official Python SDK (`mcp` 2.x), stdio transport

**Python packages** (`requirements.txt`)

- `psycopg[binary]` – PostgreSQL driver used to talk to SereneDB
- `mcp[cli]` – MCP server framework
- `python-dotenv` – reads the connection settings from `.env`


---

## Folder and file structure

- **`server/`** – the MCP server
  - `server.py` – the six tools, input checks, SQL building, evidence record, role prompts as MCP prompts
  - `roles.py` – shared evidence rules (sent to the agent on connect) and the engineer, team lead and manager prompts
- **`loader/`** – import and validation of the log data
  - `load.py` – main entry point: prepares CSVs, imports the four tables in one transaction, validates, builds indexes
  - `bgl.py`, `openstack.py` – parsers for the two log formats
  - `common.py` – shared parsing and CSV helpers
  - `db.py` – database connection (reads `.env`); `python -m loader.db` is a connection check
  - `validate.py` – the 54 SQL checks against the imported data
  - `schema.sql` – table definitions (`bgl_logs`, `openstack_logs`, `openstack_anomaly_vms`, `team_ownership`)
  - `indexes.sql` – full-text (inverted) indexes on the log messages
  - `team_ownership.csv` – **fictional** mapping of components to teams
- **`docs/`**
  - `schema.md` – shared data and tool contract
  - `worked_investigation.md` – one investigation of a real pattern, step by step for all three roles
  - `investigation_runs/` – the original final answers of the three role runs and a follow-up check
  - `slides.pdf` – presentation slides
- **`tests/`**
  - `test_loader.py`, `test_loader_db.py` – loader tests (parser, CSV, database import)
  - `test_server.py` – server checks: filter resolution, `describe_dataset`, tool annotations (partly without database)
  - `test_search_phrase.py` – phrase search checks against the full data
  - `test_literal_substring.py` – checks that `%` and `_` in the substring filter of `count_by`/`trend` are matched literally
  - `check_trend_stats.py` – compares the trend statistics of the server with reference values
- **`.env.example`** – template for the database connection settings
- **`requirements.txt`** – Python dependencies
- **`data/`** – (not in Git) raw datasets, prepared CSVs and reports


---

## Requirements

To run the project locally you need:

- **Python 3.12 or newer** ([Download](https://www.python.org/downloads/)) – tested with 3.12 on Linux and 3.13 on Windows
- **Docker** (Docker Desktop on Windows/macOS) ([Download](https://docs.docker.com/get-docker/))
- **Claude Code** ([Docs](https://code.claude.com/docs/en/setup)) with a paid Claude plan (Pro, Max, Team or Enterprise) or a Console account; installation is shown in step 6. Any MCP client that can start a stdio server works the same way
- The **raw BGL and OpenStack datasets** (full versions, not the 2,000-line samples):
  [BGL](https://zenodo.org/records/8196385/files/BGL.zip?download=1), [OpenStack](https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1)
- Enough disk space for the raw files, the prepared CSVs, the database tables and the indexes

Tested with SereneDB 26.10.1 and Claude Code 2.1.302.


---

## How to set up and run the project

### 1) Clone the repository

```bash
git clone https://github.com/celil-durna/log-insights-ai-agent.git
cd log-insights-ai-agent
```

All following commands are run from the repository root.

### 2) Install the Python dependencies and create `.env`

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

`.env` holds the five `SERENEDB_*` connection values. The defaults match the Docker command in step 4 (user `postgres`, password `hackathon`, host `127.0.0.1`, port `7890`). Use `127.0.0.1`, not `localhost` (some systems resolve `localhost` to IPv6 first). The loader and the server find `.env` relative to the repository, regardless of the calling directory. `.env` and `data/` are ignored by Git.

**Using another SereneDB instance (e.g. the one provided by the organisers).** Put its host, port, user, password and database into the five `SERENEDB_*` values in `.env`; the server and the loader use nothing else. The loader imports the prepared CSV files with a server-side `COPY` from `/data`, so loading the data (step 5) needs a SereneDB that can read this project's `data/` folder, such as the local container from step 4. If the instance already contains the four tables loaded by this loader, skip steps 3 to 5 and only run `python -m loader.validate` as a check.

### 3) Download and place the datasets

Download the original archives from Zenodo (keep `?download=1` and `-L`) and extract them into `data/full/`:

**Linux / macOS**

```bash
mkdir -p data/full/BGL data/full/OpenStack
curl -L -o data/full/BGL.zip "https://zenodo.org/records/8196385/files/BGL.zip?download=1"
unzip data/full/BGL.zip -d data/full/BGL
curl -L -o data/full/OpenStack.tar.gz "https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1"
tar -xzf data/full/OpenStack.tar.gz -C data/full/OpenStack
```

**Windows (PowerShell)** (use `curl.exe`, not `curl`; `tar` is built into Windows 10/11)

```powershell
New-Item -ItemType Directory -Force data\full\BGL, data\full\OpenStack | Out-Null
curl.exe -L -o data\full\BGL.zip "https://zenodo.org/records/8196385/files/BGL.zip?download=1"
Expand-Archive data\full\BGL.zip -DestinationPath data\full\BGL
curl.exe -L -o data\full\OpenStack.tar.gz "https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1"
tar -xzf data\full\OpenStack.tar.gz -C data\full\OpenStack
```

The archives are about 55 MB (BGL) and 5 MB (OpenStack); BGL unpacks to about 740 MB. Afterwards these files must exist:

```text
data/full/BGL/BGL.log
data/full/OpenStack/openstack_normal1.log
data/full/OpenStack/openstack_normal2.log
data/full/OpenStack/openstack_abnormal.log
data/full/OpenStack/anomaly_labels.txt
```

Optional: verify the OpenStack logs with `sha256sum data/full/OpenStack/*.log` (PowerShell: `Get-FileHash data\full\OpenStack\*.log`). Expected SHA-256 fingerprints (archive MD5: `66bd42c07837a094d9b0ea2d036b5713`):

```text
7ab718fbb2f2b804893955cecf37ad9533cfa0efaf5b03009474d5bb019b6af4  openstack_abnormal.log
4e4d47347bdae198056bb3b0a8a755e1cb0100d6c6a30bbd4058684234769199  openstack_normal1.log
3c51741dcea1fb0731d1f86588b12587707e7abea01e725ee16c9441b8b68db7  openstack_normal2.log
```

The loader checks these files itself. An earlier local `normal1` copy contained `w` instead of `ERROR` at line 27179; that copy is not the original corpus. Restore the original input rather than relaxing the checks.

### 4) Start SereneDB (Docker)

Make sure Docker is running (Docker Desktop: wait until it shows "Engine running"). For a **new** container, run this from the repository root. It sets the password used in `.env.example` and mounts the project's `data/` folder at `/data`, so SereneDB can read the prepared files:

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

If another container named `serenedb` or another service already uses port 7890, stop it first (`docker stop <name>`). If the container already exists with this mount, use `docker start serenedb` instead (with Docker Desktop on Linux possibly `docker --context desktop-linux start serenedb`). If you use a different password, change `SERENEDB_PASSWORD` in `.env`. The mounted host directory must be the same directory passed to `--data-dir` (default: this project's `data/`). `latest` may change; the verified runtime version is recorded in the validation report.

### 5) Import and validate the data

```bash
python -m loader.db
python -m loader.load
```

The first command is a connection check and should print `(1,)`. The second streams the input into CSVs, verifies SHA-256 fingerprints, creates and loads the four tables in one transaction, validates the complete corpus and then builds the search indexes. On a laptop this took about 2 minutes. A successful run ends with:

```text
Success: 54 SQL checks passed.
```

<details>
<summary>Separate loader stages and rebuilding</summary>

```bash
python -m loader.load --prepare-only    # CSVs only, no database needed
python -m loader.load --import-only     # import from existing CSVs (checked against the manifest)
python -m loader.validate               # rerun the SQL checks, including index readiness
```

Existing tables are refused by default. To deliberately rebuild the four tables and their indexes:

```bash
python -m loader.load --import-only --replace
```

A failed import or replacement rolls back the four-table transaction. Index creation runs after the committed import in a separate transaction; if it fails, the validated data stay loaded. Indexes can be deferred with `--skip-indexes` and built later with `python -m loader.load --indexes-only`. Each failing stage exits with a nonzero status.

</details>

Optional check of the trend statistics used by the agent (read-only, expects the full corpus):

```bash
python tests/check_trend_stats.py
```

It should print `all checks passed`.

### 6) Install Claude Code and register the MCP server

If Claude Code is not installed yet ([official setup guide](https://code.claude.com/docs/en/setup)):

**Linux / macOS**

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

**Windows (PowerShell)**

```powershell
irm https://claude.ai/install.ps1 | iex
```

Open a new terminal and check with `claude --version`. If `claude` is not found, the install folder is not on your PATH yet (see the setup guide). On the first start, `claude` asks you to log in in the browser (choose your Claude account with subscription) and whether you trust the project folder (choose "Yes").

Then register our MCP server once, from the repository root, with the Python interpreter that has the requirements installed:

**Linux / macOS (with the `.venv` from step 2)**

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

### 7) Start the agent

Start `claude` in the repository folder and type `/mcp`: `log-insights` should be connected with **6 tools**.

Quick test:

```text
Call the ping tool of the log-insights server.
```

Expected result: `{"ok": true}`.

Claude Code starts the MCP server itself in the background. After changing server code, restart Claude Code.

### 8) How to stop everything

- Leave Claude Code with `/exit` (this also stops the MCP server).
- Stop the database container (the data stay in the `serenedb-data` volume):
  ```bash
  docker stop serenedb
  ```


---

## How to use the agent

Ask a question in a role with the role prompts. They appear as slash commands in Claude Code (in the command picker shown as `/log-insights:engineer`, `/log-insights:team_lead`, `/log-insights:manager`; inserted as `/mcp__log-insights__engineer` etc.). Type the question after the command:

```text
/mcp__log-insights__engineer What is going on with APPREAD alerts in BGL?
/mcp__log-insights__team_lead Across the full BGL dataset, which FATAL problems recur, how often, and which components and teams should investigate first?
/mcp__log-insights__manager Across BGL and OpenStack, which observed problems deserve attention first and what should happen next?
/mcp__log-insights__engineer In OpenStack, investigate Error during ComputeManager._run_image_cache_manager_pass. What failed, what happened immediately before and after a representative error, and what cause can the logs establish?
```

Tips:

- Add `Include the exact SQL of every query in the evidence list.` to request the SQL exposed by the tools in the answer. Internal helper queries and complete SQL bindings are not all exposed.
- Use `/clear` between unrelated questions. Query ids (`Q1`, `Q2`, …) keep counting until Claude Code is restarted, so restart it if a fresh run should start at `Q1`.
- `/export <file>` saves a conversation as a text file.
- Claude Code may load the tool definitions only when they are first needed. In our clean-checkout test the first few tool calls of a session were sent before that and failed; the model then loaded the definitions and repeated the calls on its own. These failed calls do not reach the database and do not get a query id.
- Tested with Claude Sonnet 5.5 (effort medium) and Claude Opus 5.5 in Claude Code 2.1.302 on Windows and Linux.


---

## Tools and evidence record

All analysis tools take `dataset` = `bgl` or `openstack`. Values are passed as SQL parameters; column names and buckets come from fixed whitelists. Analysis tools return `results` and `evidence`; `describe_dataset` uses an overview object for `results` and adds `metadata` and `notes`. `ping` is a separate health check returning `ok`.

| Tool | Purpose | Main inputs | Returns |
| --- | --- | --- | --- |
| `describe_dataset` | Overview of one dataset, to pick valid filters | – | Measured `results`: `rows`, `first_ts`, `last_ts`, `null_timestamp_rows`, all values of `level`, `component`, `team` and `label` (bgl) with line counts. `metadata.count_by_group_by`: configured grouping options. Separate `notes`: documented meanings (e.g. `-` = no alert, fictional teams) |
| `search_logs` | Full-text search over the log message via the inverted index (`@@`), ranked by BM25 | `text`; optional `phrase` (default false; adjacent ordered tokens), `component`, `level`, `team`, `from_ts`, `to_ts`, `label` (bgl), `limit` (default 20, max 100) | Matching rows with `score` and `team`; total matches in `rows_matched` |
| `nearby_events` | Lines just before and after one anchor line, in time order | `line_no` (+ `source_file` for openstack) or `ts`; `window_seconds` (default 60, max 3600); optional `node` (bgl) or `request_id` / `instance_id` (openstack); `limit` (default 50, max 200) | Half of the limit before and half after the anchor, each with `offset_s`; OpenStack stays in the anchor's file |
| `count_by` | Counts per group over the complete filtered data, largest first | `group_by` (bgl: component, level, team, label, node, rack; openstack: component, level, team, service, http_status, instance_id, source_file); structured filters as in `search_logs` (`text` = substring; no `phrase` option); `limit` (default 20, max 100) | `[{key, count}]`, `groups_total` |
| `trend` | Counts per time bucket over the complete filtered data | `bucket` (`minute`, `hour`, `day`); same filters as `count_by` | `[{bucket_start, count}]` (max 1,000 buckets) plus summary fields computed in the database: `active_buckets`, `first_bucket`, `last_bucket`, `peak_bucket`, `peak_count`, `peak_share`, `null_timestamp_rows` |
| `ping` | Connection check | – | `{"ok": true}` |

`component`, `level`, `team` and `label` are matched ignoring case. A corrected value is shown in the evidence as `normalized_filters` (e.g. `appread -> APPREAD`); `params` keep the input. A value that does not exist in the dataset returns `not_checkable` with suggestions (e.g. `unknown label 'APREAD' in bgl; did you mean: APPREAD, APPRES`), so a typo is never reported as zero lines.

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


---

## Roles

Same agent, same data, same tools for all roles. `server/roles.py` defines shared evidence rules and one prompt per role; what changes is the question, the evidence selected and the recommendation.

**Shared rules (all roles):** every number comes from a tool result and is cited as `(query_id, scope)`; answers separate *Observed*, *Possible explanation (hypothesis)*, *Unknown* and *Recommendation*; counts are log lines, not incidents; statements about one problem (recurring, burst, spread) need a query filtered to that problem, otherwise "not measured"; examples are never generalised; trend statistics are taken from the tool, never computed by the model; no invented cost, downtime or customer impact; every answer ends with an evidence list.

| Role | Question it answers | Typical tool flow | Answer |
| --- | --- | --- | --- |
| Engineer | What failed, where, what happened just before and after? | `search_logs` → `nearby_events` → `count_by`/`trend` for the real frequency | Failing component/node, quoted lines with `line_no`, sequence with offsets, cause as hypothesis (with number of inspected cases), next diagnostic check |
| Team lead | Which problems recur, how often, which components and teams? | `count_by` (team, component, label) → `trend` per discussed problem → `count_by` node/rack for spread → examples | Table with log lines, share, active days, first/last day, owner; pattern per problem; what to investigate first |
| Manager | What deserves attention first and what next? | Fixed candidate set (5 largest BGL labels, 2 largest OpenStack components for ERROR and for WARNING) → `trend` for every candidate | Ranking rule, top 3 assessable recurring/limited problems, separate burst and OpenStack blocks, actions, what the data do not tell |

The manager classification is an agreed heuristic, not a validated risk model: dataset shorter than 7 days → "recurrence not assessable"; `peak_share` > 0.5 → burst; ≥ 5 active days → recurring; otherwise limited. "Still active" means observed within the last 7 days of that dataset.


---

## Worked investigation

See [docs/worked_investigation.md](docs/worked_investigation.md): one investigation from the whole corpus down to a single burst. The manager compares problems across BGL and OpenStack, the team lead measures which FATAL problems in BGL recur, and the engineer uses a time-filtered full-text search and nearby events to examine the APPREAD burst of 2005-06-16. All tool calls with their inputs, reported SQL and result counts are documented, and the original final answers are in [docs/investigation_runs/](docs/investigation_runs/).

Result in short: APPSEV and KERNMNTF are the recurring BGL problems to assign first, while KERNDTLB and KERNSTOR are dominated by bursts in June 2005. On 2005-06-16, APPREAD accounts for 2,040 log lines across 510 nodes in minute buckets from 14:50 to 15:03. Two failed job-login messages (`chdir … No such file or directory`) immediately precede the inspected first APPREAD line; a causal link is a hypothesis, not proven. The inspected samples share an error pattern and target host; this was not verified for every line. A separate [follow-up check](docs/investigation_runs/appread_followup_berkan.md) also found two chdir failures immediately before the inspected first APPREAD line on June 4, supporting the hypothesis without proving causation.


---

## How to run test cases

**Loader tests** (parser and preparation; database tests are skipped):

```bash
python -m unittest discover -s tests -v
```

**All tests including the database tests** (needs the running SereneDB with the full imported corpus):

**Linux / macOS**

```bash
LOADER_DB_TESTS=1 python -m unittest discover -s tests -v
```

**Windows (PowerShell)**

```powershell
$env:LOADER_DB_TESTS = "1"
python -m unittest discover -s tests -v
Remove-Item Env:LOADER_DB_TESTS
```

The database tests exercise CSV round-tripping, composite keys, NULLs, search refresh/BM25, duplicate-import refusal and replacement rollback. They create uniquely named `loader_test_*` schemas and remove them afterwards; they do not change the application's tables. `test_search_phrase.py` and the full-corpus part of `test_server.py` read the imported tables and check reference values (phrase search, `describe_dataset`, filter resolution).

**Trend statistics of the server** (read-only, full corpus):

```bash
python tests/check_trend_stats.py
```


---

## Known limitations

- Full-text search defaults to word matching. Set `phrase=true` in `search_logs` to require adjacent tokens in order (`phraseto_tsquery`) with the same index and BM25 ranking. This is case-insensitive token matching, not an exact character substring. On the verified corpus, "Error during ComputeManager" returns 4,069 word matches and 8 phrase matches; "failed to read message prefix" returns 5,983 phrase matches, exactly the APPREAD label count, while the word `ciod` matches 350,567 lines. `count_by`/`trend` use case-insensitive substring filters. The evidence scope states the method.
- Counts are log lines, not incidents. One event can write one line per node (e.g. ~510 lines per APPREAD burst) or a multi-line traceback.
- Burst counts depend on the bucket size (minute, hour, day). "Active days" are days with at least one line, not the calendar span (BGL: 215 active days, 2005-06-03 to 2006-01-04; OpenStack: 3 active days, 2017-05-14 to 2017-05-17).
- OpenStack covers only a few days, so its recurrence cannot be assessed and it is not directly comparable with BGL.
- The team ownership mapping is fictional. Cost, downtime and customer impact are not in the logs and are never estimated.
- Interpretations of alert labels and causes rest on the lines actually inspected and are marked as hypotheses.
- Numbers come from the tools, but the wording and the labels the model assigns (e.g. the manager's burst/recurring/limited classification) can vary between runs and should be checked against the evidence fields.
- SereneDB 26.10.1 occasionally crashed during our tests (container exit code 139, SIGSEGV), not tied to one reproducible query; the cause is unknown. If a tool suddenly returns a connection error, run `docker start serenedb` and restart Claude Code.
- Not implemented (optional in the challenge): agent-managed indexes, huge remote datasets, traces/metrics, row-level security, fuzzy search.


---

## Data contract and verification

See [docs/schema.md](docs/schema.md) for the shared contract and [loader/schema.sql](loader/schema.sql) for the executable DDL. The tables are `bgl_logs`, `openstack_logs`, `openstack_anomaly_vms` and `team_ownership`.

- Expected corpus: 4,747,963 BGL rows and 207,820 OpenStack rows (52,312 normal1 / 137,074 normal2 / 18,434 abnormal).
- BGL retains the 306 `variant_kill` and ten `variant_other` records. The 104,215 `NULL` type markers and 34,470 absent messages are ordinary supported rows. Time is taken from the precise timestamp without assuming a timezone.
- OpenStack retains missing optional fields as SQL NULL, including 184 traceback lines without a request-context bracket. Their indentation and separate line numbers are preserved. The parser defensively retains a `w` level as NULL with `variant_level`, rather than guessing a severity; the verified original corpus contains no such rows (194 ERROR rows, no missing levels).
- `raw_line` preserves the original log text, including trailing spaces, excluding only the record's LF/CRLF terminator. `line_no` is one-based within the original file.
- Unexpected parsing failures retain the raw row in the CSV and record a reason in `parse_errors.jsonl`. They block database import. Invalid UTF-8 aborts preparation visibly. No line is silently skipped.
- Four labelled VMs are kept separately for evaluation. Each has 28 raw UUID mentions but only 25 explicit instance tags, all in `abnormal`. Both counts are checked separately; `instance_id` keeps its agreed meaning. Labels are not exposed to the agent as ground-truth hints.
- [loader/team_ownership.csv](loader/team_ownership.csv) contains **fictional teams** from the agreed mapping, not real ownership facts.

<details>
<summary>Local loader outputs under <code>data/processed/</code></summary>

CSV exports are stored in immutable `run-<id>/` directories. `manifest.json` points to the current generation. Reusing a filename after replacing its contents exposed a stale file view through the local Docker Desktop mount; using a fresh path for each preparation avoids that issue. Old generations are retained so previous evidence can still be inspected.

| File | Purpose |
| --- | --- |
| `manifest.json` | Input/CSV hashes, row counts, parse statuses and representative parsed records |
| `parse_errors.jsonl` | Unexpected parsing failures and original source line numbers (empty on success) |
| `import_report.json` | SQL checks before publication, with an explicit `committed` flag |
| `validation_report.json` | Checks against committed data, executed SQL, bound parameters, results and database version |

</details>

### Search directly in SereneDB

SereneDB full-text queries use the index name; the base tables remain available for complete aggregations:

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

The index dictionary lowercases tokens and records frequencies/positions for BM25 and phrase queries. It does not apply stemming. See [loader/indexes.sql](loader/indexes.sql). A limited search result is not a frequency estimate; use a complete count query for measured claims.


---

## Team

- **Celil Durna** – MCP server and tools, evidence record, role prompts, trend statistics in the database, README
- **Berkan Gürbüz** – loader, data validation, database schema and indexes, loader tests, phrase search

The data and tool contract (`docs/schema.md`), testing on Windows and Linux and the worked investigation were done together.


---

## Dataset attribution

Loghub is a research dataset collection. Cite Zhu et al., *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics*, ISSRE 2023; for BGL also Oliner & Stearley, *What Supercomputers Say*, DSN 2007. OpenStack's dataset README additionally references Du et al., *DeepLog*, CCS 2017. See the original [Loghub repository](https://github.com/logpai/loghub) for dataset documentation and usage terms.
