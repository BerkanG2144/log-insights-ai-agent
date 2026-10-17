# log-insights-ai-agent
AI agent that turns log data into role-specific insights for engineers, team leads and managers (Python, SereneDB, SQL, LLM). Built at the National AI Hackathon 2026.

The loader prepares BGL/OpenStack, imports the complete corpus into SereneDB, validates it with SQL and builds full-text indexes. The MCP server exposes `ping`, `search_logs`, `nearby_events`, `count_by` and `trend`, plus prompts for engineers, team leads and managers. Connecting the server's text filters to the full-text indexes is the remaining search integration step.

## Local setup

Requires Python 3.12, Docker and the raw BGL/OpenStack datasets. Tested locally with SereneDB 26.10.1. From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Adjust the five `SERENEDB_*` connection values in `.env` for your local container. The loader resolves this file relative to the repository, regardless of the calling directory. The data and `.env` are ignored by Git.

Place the original, extracted datasets at these paths:

```text
data/full/BGL/BGL.log
data/full/OpenStack/openstack_normal1.log
data/full/OpenStack/openstack_normal2.log
data/full/OpenStack/openstack_abnormal.log
data/full/OpenStack/anomaly_labels.txt
```

Original archives: [BGL](https://zenodo.org/records/8196385/files/BGL.zip?download=1), [OpenStack](https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1). Use the full datasets here, not the 2,000-line samples.

Verify the extracted OpenStack logs with `sha256sum data/full/OpenStack/*.log`. Expected SHA-256 fingerprints from the original archive (archive MD5: `66bd42c07837a094d9b0ea2d036b5713`):

```text
7ab718fbb2f2b804893955cecf37ad9533cfa0efaf5b03009474d5bb019b6af4  openstack_abnormal.log
4e4d47347bdae198056bb3b0a8a755e1cb0100d6c6a30bbd4058684234769199  openstack_normal1.log
3c51741dcea1fb0731d1f86588b12587707e7abea01e725ee16c9441b8b68db7  openstack_normal2.log
```

An earlier local `normal1` copy contained `w` instead of `ERROR` at line 27179. That copy is not the original corpus. Full-corpus validation expects 194 ERROR rows, no missing levels and no `variant_level` rows; restore the original input rather than relaxing these checks.

For a **new** container, create the host data directory and mount it at `/data`:

```bash
mkdir -p data
docker run -d --name serenedb \
  -p 127.0.0.1:7890:7890 \
  -v serenedb-data:/var/lib/serenedb \
  -v "$PWD/data":/data \
  serenedb/serenedb:latest
```

If the container already exists with this mount, use `docker start serenedb` instead. On Berkan's Docker Desktop setup, use `docker --context desktop-linux start serenedb`. The mounted host directory must be the same directory passed to `--data-dir` (the default is this project's `data/`). `latest` may change; the verified runtime version is also recorded in the validation report.

## Run the loader

```bash
python -m loader.db
python -m loader.load
```

The first command should print `(1,)`. The second streams the input into CSVs, verifies SHA-256 fingerprints, creates and loads the four agreed tables in one transaction, validates the full corpus, then creates and refreshes the search indexes. Progress is printed during preparation. Allow disk space for the CSV exports, database tables and indexes in addition to the original files.

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
