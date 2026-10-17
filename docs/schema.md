# Schema and tool contract

Shared interface between the loader (`loader/`, Berkan) and the MCP server (`server/`, Celil).
Merged from Berkan's draft and Celil's draft, 2026-10-17.
Rule: after both agree, nobody changes names or types without telling the other.

Status: AGREED — 2026-10-17 15:00, Celil + Berkan

## Conventions

- Names in `snake_case`, English.
- Every row keeps its original text in `raw_line`. No line is dropped silently.
- Missing or unparsable values are `NULL`, never an empty string.
- File paths in SQL always start with `/data/...` (Docker mount, same on Windows and Linux).
- New datasets later = new table with the common core plus dataset-specific columns.

## Common core columns (every log table)

| column | type | meaning |
|---|---|---|
| `line_no` | BIGINT | 1-based line number in the source file |
| `raw_line` | VARCHAR | unmodified original line (never dropped) |
| `ts` | TIMESTAMP | event time parsed from the line |
| `component` | VARCHAR | emitting component (BGL: the token after the header's `RAS` or `NULL` type marker, accounting for the 316 structural variants; OpenStack: module name) |
| `level` | VARCHAR | severity as written in the log |
| `message` | VARCHAR | free-text part used for full-text search |
| `parse_status` | VARCHAR | `ok` or a variant tag, see below |

## `bgl_logs`

Source: `/data/full/BGL/BGL.log`. Primary key: `line_no`. Core columns plus:

| column | type | meaning |
|---|---|---|
| `ts_unix` | BIGINT | Unix time, field 2 |
| `node` | VARCHAR | node id, field 4; NULL where it is `-` |
| `rack` | VARCHAR | rack prefix of the node, e.g. `R02` (NULL if the node has no `Rnn-` prefix) |
| `label` | VARCHAR | field 1, `-` means normal |
| `is_alert` | BOOLEAN | `label <> '-'` |

`ts` comes from the precise timestamp (field 5, e.g. `2005-06-03-15.42.50.363779`).
`parse_status`: `ok`, `variant_kill` (306 lines: node is `-` and the second node field is missing, so all later fields shift left by one; level is still present, e.g. `RAS KERNEL FATAL Kill job ...`), `variant_other` (10 lines: the node field is replaced by a truncated text fragment, followed by `RAS KERNEL INFO ...`; seen at position 9 as `single` 4x, `microseconds` 4x, `0x00544eb8,` 2x).
The previous RAS-only regex was incomplete. A full-file check found 104,215 ordinary rows with the type token `NULL` and 34,470 rows without message text. Both are valid `ok` rows; absent `message` becomes SQL NULL. The parser uses the header structure, not an unrestricted search for `RAS` inside the message:

```regex
^(\S+) (\d+) (\S+) (\S+) (\S+) (?:(.*?) )?(RAS|NULL) (\S+) (\S+)(?: (.*))?$
```

The repeated location field differs from the first node in eight otherwise regular rows. Keep the first node and do not classify a different repeated node as `variant_other`; that tag identifies the multi-word location fragments. `ts` is parsed without inventing a timezone; `ts_unix` is preserved separately.

Unexpected structures or invalid values are preserved in the prepared CSV with `parse_status = 'parse_error'` and an entry in `data/processed/parse_errors.jsonl`. They block publication to the database until resolved. No agreed column name or type has changed.
Components: KERNEL, APP, DISCOVERY, MMCS, HARDWARE, MONITOR, LINKCARD, CMCS, BGLMASTER, SERV_NET.
Lines mentioning IP 172.16.96.116: 59,995, all level FATAL, by label: APPSEV 49,651, APPREAD 5,983, APPRES 2,370, APPTO 1,991.

## `openstack_logs`

Sources: `/data/full/OpenStack/openstack_{normal1,normal2,abnormal}.log`. Primary key: (`source_file`, `line_no`). Core columns plus:

| column | type | meaning |
|---|---|---|
| `source_file` | VARCHAR | `normal1`, `normal2`, `abnormal` |
| `pid` | INTEGER | process id |
| `service` | VARCHAR | `nova-compute`, `nova-api`, `nova-scheduler`, taken from the log file name at the start of each line |
| `request_id` | VARCHAR | matched by pattern `\[(req-[0-9a-f-]{36})`, not by position; NULL if no match (e.g. `[-]`) |
| `instance_id` | VARCHAR | VM id from `[instance: <uuid>]` if present, else NULL |
| `http_status` | INTEGER | parsed from `status: NNN`, NULL for lines without it |
| `latency_s` | DOUBLE PRECISION | parsed from `time: X`, NULL for lines without it |

The request-context bracket after the component varies (`[req-… <user> <project> - - -]`, `[req-… - - - - -]`, `[-]`); `message` is everything after the closing bracket. There are also 184 traceback rows without a request-context bracket: there the message starts after the component separator, with any additional indentation preserved. These are ordinary `ok` rows with NULL `request_id`. Keep each original physical line as its own row, rather than joining the traceback into one entry.
`level` must be one of INFO, WARNING, ERROR, CRITICAL. The verified original corpus has 204,506 INFO, 3,118 WARNING, 194 ERROR and 2 CRITICAL rows, with no missing levels or `variant_level` rows. An earlier local copy had `w` instead of `ERROR` at normal1 line 27179; this is not an original dataset variant. The parser still defensively retains `w` as NULL with `parse_status = 'variant_level'` and preserves `raw_line`, but full-corpus validation rejects that altered corpus. Original file fingerprints are documented in the root README.
Components (12): nova.osapi_compute.wsgi.server, nova.virt.libvirt.imagecache, nova.compute.manager, nova.metadata.wsgi.server, nova.compute.claims, nova.virt.libvirt.driver, nova.compute.resource_tracker, nova.api.openstack.compute.server_external_events, nova.api.openstack.wsgi, nova.scheduler.host_manager, oslo_service.periodic_task, keystonemiddleware.auth_token.
"Unknown base file" warning: 838 / 1,951 / 270 rows (1.60 / 1.42 / 1.46 %), so it is not a discriminating signal.

## `openstack_anomaly_vms`

Source: `/data/full/OpenStack/anomaly_labels.txt` (skip the header sentence).

| column | type | meaning |
|---|---|---|
| `instance_id` | VARCHAR | primary key, joins with `openstack_logs.instance_id` |

4 rows. Each ID occurs as text in 28 `abnormal` raw lines and 0 normal lines. Only 25 of those lines have the explicit `[instance: <uuid>]` tag, so the agreed `instance_id` field joins 25 rows per VM. Do not broaden that field to arbitrary UUID mentions to force a count of 28; validate the 28 raw mentions and 25 tagged rows separately.
Ground truth for evaluation and the worked investigation only; no tool exposes it to the agent.

## `team_ownership`

| column | type | meaning |
|---|---|---|
| `dataset` | VARCHAR | `bgl` or `openstack` |
| `component` | VARCHAR | matches `component` in the log tables |
| `team` | VARCHAR | invented team name, documented as fictional in the README |

Primary key: (`dataset`, `component`). Every component in the logs has exactly one row.
Proposal:

| dataset | component | team |
|---|---|---|
| bgl | KERNEL | Compute Platform |
| bgl | APP | Application Runtime |
| bgl | MMCS | Control System |
| bgl | BGLMASTER | Control System |
| bgl | CMCS | Control System |
| bgl | DISCOVERY | Hardware Operations |
| bgl | HARDWARE | Hardware Operations |
| bgl | MONITOR | Hardware Operations |
| bgl | LINKCARD | Network |
| bgl | SERV_NET | Network |
| openstack | nova.osapi_compute.wsgi.server | Cloud API |
| openstack | nova.api.openstack.wsgi | Cloud API |
| openstack | nova.api.openstack.compute.server_external_events | Cloud API |
| openstack | nova.metadata.wsgi.server | Cloud API |
| openstack | keystonemiddleware.auth_token | Cloud API |
| openstack | nova.compute.manager | Compute Nodes |
| openstack | nova.compute.claims | Compute Nodes |
| openstack | nova.compute.resource_tracker | Compute Nodes |
| openstack | oslo_service.periodic_task | Compute Nodes |
| openstack | nova.virt.libvirt.driver | Virtualization |
| openstack | nova.virt.libvirt.imagecache | Virtualization |
| openstack | nova.scheduler.host_manager | Scheduling |

## Full-text index

`message` in `bgl_logs` and `openstack_logs` gets SereneDB's inverted index (`@@`, BM25).
DDL is in `loader/indexes.sql`. Syntax was checked using the installed SereneDB 26.10.1 documentation (`sdb_docs.search`) and an integration test including refresh and BM25. The core definitions are:

```sql
CREATE TEXT SEARCH DICTIONARY log_insights_words AS
    split_text(case := 'lower') WITH (frequency, position);

CREATE INDEX bgl_logs_message_idx ON bgl_logs USING inverted (
    line_no, ts, component, level, node, rack, label, is_alert,
    message log_insights_words
) INCLUDE (raw_line, ts_unix, parse_status);

CREATE INDEX openstack_logs_message_idx ON openstack_logs USING inverted (
    source_file, line_no, ts, component, level, service, request_id, instance_id,
    http_status, message log_insights_words
) INCLUDE (raw_line, pid, latency_s, parse_status);
```

Commit index creation before running `VACUUM (REFRESH_TABLE) bgl_logs` and the equivalent for OpenStack. Full-text queries use the index name, e.g. `SELECT line_no FROM bgl_logs_message_idx WHERE message @@ 'ciod'`. The indexed and included columns expose all log-table fields. SQL aggregation can use the base tables. Ground-truth anomaly labels are not indexed or exposed as agent tools.

## Evidence record (returned by every tool)

```json
{
  "results": [],
  "evidence": {
    "query_id": "Q1",
    "tool": "search_logs",
    "dataset": "bgl",
    "params": {},
    "sql": "SELECT ...",
    "scope": "bgl_logs, all rows",
    "rows_matched": 0,
    "rows_returned": 0,
    "limit": 0,
    "truncated": false,
    "status": "ok"
  }
}
```

`status` is `ok`, `empty` or `not_checkable`. `not_checkable` always comes with `reason` (for example "no instance_id in these rows"). `truncated` is `true` whenever `rows_matched > rows_returned` (for aggregations: groups cut by `limit`).
`sql` is the exact statement; values are passed as parameters, never string-built.

## Tools (names as in the team rules)

All tools take `dataset` = `bgl` | `openstack`. Optional filters are AND-combined.

| tool | inputs | returns |
|---|---|---|
| `search_logs` | `dataset`, `text`, optional `component`, `level`, `team`, `from_ts`, `to_ts`, `label` (bgl only), `limit` (default 20, max 100), `phrase` (default false) | matching rows + evidence |
| `nearby_events` | `dataset`, `line_no` (+ `source_file` for OpenStack) or `ts`, `window_seconds` (default 60, max 3600), optional `node` or `request_id` / `instance_id`, `limit` (default 50, max 200) | rows around the anchor in time order + evidence |
| `count_by` | `dataset`, `group_by`, optional `text`, `component`, `level`, `team`, `from_ts`, `to_ts`, `limit` (default 20, max 100) | counts per group, largest first + evidence |
| `trend` | `dataset`, `bucket` (`minute`, `hour`, `day`), optional `text`, `component`, `level`, `team`, `from_ts`, `to_ts` | counts per time bucket + evidence |

`group_by` whitelist (anything else → `not_checkable`): `component`, `level`, `team`, `label`, `node`, `rack`, `service`, `http_status`, `instance_id`, `source_file`.
`team` is resolved by joining `team_ownership`.
`check_hypothesis` comes later and reuses the same evidence record per check.

## Import check (reference counts, all checked against the files)

| check | expected |
|---|---|
| `bgl_logs` rows | 4,747,963 |
| `bgl_logs` with `label = '-'` | 4,399,503 |
| `bgl_logs` with `is_alert` | 348,460 |
| `bgl_logs` with `label = 'APPREAD'` | 5,983 |
| `bgl_logs` with `parse_status <> 'ok'` | 316 (306 `variant_kill`, 10 `variant_other`) |
| `openstack_logs` rows per `source_file` | 52,312 / 137,074 / 18,434 |
| `openstack_logs` rows per `service` | nova-api 102,868, nova-compute 104,086, nova-scheduler 866 |
| `openstack_logs` with `http_status` not NULL | 98,733 |
| `openstack_logs` with `level IS NULL` | 0 |
| `openstack_logs` with `parse_status = 'variant_level'` | 0 |
| `openstack_logs` rows per `level` | INFO 204,506, WARNING 3,118, ERROR 194, CRITICAL 2 |
| `openstack_logs` with `request_id` not NULL | 192,174 (raw-file check; also checked by loader SQL validation) |
| `openstack_anomaly_vms` rows | 4 |
| `openstack_logs` raw UUID mentions per anomaly VM | 28 each, all in `abnormal`, 0 in normal files |
| `openstack_logs` joined by tagged `instance_id` per anomaly VM | 25 each, all in `abnormal`, 0 in normal files |
| components without a `team_ownership` row | 0 |

## Loader implementation

- Python streams the original files into immutable CSV generations under `data/processed/run-<id>/`, with explicit column order and SQL NULL handling. The raw files are unchanged. New generations use new paths because replacing an already-read file at the same path exposed stale file contents through the local Docker Desktop mount during testing.
- `loader/schema.sql` creates materialized tables with the agreed primary keys. VARCHAR, TIMESTAMP, BIGINT, DOUBLE PRECISION, BOOLEAN and composite primary keys are exercised by integration tests.
- All four tables are loaded and validated inside one transaction. A failed check rolls it back. Existing tables are refused unless `--replace` is explicitly supplied; a failed replacement restores the previous tables.
- `manifest.json` records source and CSV SHA-256 hashes, row counts, parser statuses and representative records. Import verifies those hashes. SQL checks and their results are saved in `import_report.json` and `validation_report.json`.
- Run commands and Docker setup are documented in the root README. The larger product workflow and agent tools remain separate work.

### Optional phrase search

`search_logs(..., phrase=true)` uses `message @@ phraseto_tsquery(text)` on the existing inverted index. Tokens must be adjacent and ordered, with case and punctuation handled by the index dictionary; this is not exact character substring matching. Default `phrase=false` preserves the existing word search. Both the full match count and BM25-ranked results use the same predicate and structured filters. Evidence records include `params.phrase` and the mode in `scope`. Aggregation tools retain their substring semantics and do not accept `phrase`.
