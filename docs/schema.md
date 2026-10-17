# Schema and tool contract

Shared interface between the loader (`loader/`, Berkan) and the MCP server (`server/`, Celil).
Merged from Berkan's draft and Celil's draft, 2026-10-17.
Rule: after both agree, nobody changes names or types without telling the other.

Status: DRAFT — agreed on: _(time, both initials)_

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
| `component` | VARCHAR | emitting component (BGL: field 8, OpenStack: module name) |
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
`parse_status`: `ok`, `variant_kill` (306 lines: node is `-` and the second node field is missing, so all later fields shift left by two; level is still present, e.g. `RAS KERNEL FATAL Kill job ...`), `variant_other` (10 lines: the node field is replaced by a truncated text fragment, followed by `RAS KERNEL INFO ...`; seen at position 9 as `single` 4x, `microseconds` 4x, `0x00544eb8,` 2x).
Parse by locating the `RAS` token, not by fixed positions. Suggested regex: `^(\S+) (\d+) (\S+) (\S+) (\S+) (?:(.*?) )?RAS (\S+) (\S+) (.*)$` (checked only on 13 sample lines, must match all rows).
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

The bracket after the component varies (`[req-… <user> <project> - - -]`, `[req-… - - - - -]`, `[-]`); `message` is everything after the closing bracket.
`level` must be one of INFO, WARNING, ERROR, CRITICAL. One known line has `w` as level: there `level` is NULL (not guessed) and `parse_status = 'variant_level'`; `raw_line` keeps the original.
Components (12): nova.osapi_compute.wsgi.server, nova.virt.libvirt.imagecache, nova.compute.manager, nova.metadata.wsgi.server, nova.compute.claims, nova.virt.libvirt.driver, nova.compute.resource_tracker, nova.api.openstack.compute.server_external_events, nova.api.openstack.wsgi, nova.scheduler.host_manager, oslo_service.periodic_task, keystonemiddleware.auth_token.
"Unknown base file" warning: 838 / 1,951 / 270 rows (1.60 / 1.42 / 1.46 %), so it is not a discriminating signal.

## `openstack_anomaly_vms`

Source: `/data/full/OpenStack/anomaly_labels.txt` (skip the header sentence).

| column | type | meaning |
|---|---|---|
| `instance_id` | VARCHAR | primary key, joins with `openstack_logs.instance_id` |

4 rows. Each id has exactly 28 lines in `abnormal` and 0 in the normal files.
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
Exact DDL: look up with the SereneDB docs MCP, do not guess, then paste it here.

```sql
-- TODO: CREATE INDEX for bgl_logs.message
-- TODO: CREATE INDEX for openstack_logs.message
```

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
| `search_logs` | `dataset`, `text`, optional `component`, `level`, `team`, `from_ts`, `to_ts`, `limit` (default 20, max 100) | matching rows + evidence |
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
| `openstack_logs` with `level IS NULL` | 1 (`parse_status = 'variant_level'`) |
| `openstack_logs` with `request_id` not NULL | count and record (not yet measured) |
| `openstack_anomaly_vms` rows | 4 |
| `openstack_logs` lines per anomaly VM | 28 each, all in `abnormal`, 0 in normal files |
| components without a `team_ownership` row | 0 |

## Open points

- Full-text index syntax (look up in SereneDB docs, do not guess).
- Whether a loaded table or a view over `read_csv` is fast enough on 4.7 M rows.
