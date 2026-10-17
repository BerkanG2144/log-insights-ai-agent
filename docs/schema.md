# Schema and tool contracts

Shared interface between the loader (`loader/`, Berkan) and the MCP server (`server/`, Celil).
**Do not rename tables, columns or tool fields without telling the other person.**

Status: DRAFT — agreed on: _(date/time, both initials)_

---

## 1. Conventions

- Table and column names: `snake_case`, English.
- Every row keeps its original text in `raw_line`. No line is dropped silently.
- Missing or unparsable values are `NULL`, never an empty string or a made-up value.
- Timestamps are `TIMESTAMP` without time zone (the logs have no time zone; we treat them as local log time).
- File paths in SQL always start with `/data/...` (Docker mount, same on Windows and Linux).

---

## 2. Table `bgl_logs`

Source: `/data/full/BGL/BGL.log` (4,747,963 lines).

Example line:

```
- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected
```

| Column | Type | From field | Notes |
|---|---|---|---|
| `line_no` | BIGINT | — | 1-based line number in the file. Primary key. |
| `raw_line` | TEXT | whole line | Unchanged original. |
| `label` | TEXT | ① | `-` = normal, otherwise alert type (41 values, e.g. `KERNDTLB`, `APPREAD`). |
| `is_alert` | BOOLEAN | ① | `label <> '-'`. |
| `ts_unix` | BIGINT | ② | Unix seconds. |
| `ts` | TIMESTAMP | ⑤ | `2005-06-03-15.42.50.363779` → `2005-06-03 15:42:50.363779`. Main time column. |
| `node` | TEXT | ④ | e.g. `R02-M1-N0-C:J12-U11`; also `NULL`, `UNKNOWN_LOCATION`, `-` as in the file. |
| `rack` | TEXT | ④ | Prefix before the first `-` if it matches `R\d\d` (e.g. `R02`), else `NULL`. |
| `event_type` | TEXT | ⑦ | `RAS` or `NULL`. |
| `component` | TEXT | ⑧ | KERNEL, APP, DISCOVERY, MMCS, HARDWARE, MONITOR, LINKCARD, CMCS, BGLMASTER, SERV_NET. |
| `level` | TEXT | ⑨ | INFO, FATAL, ERROR, WARNING, SEVERE, FAILURE. |
| `message` | TEXT | ⑩ | Rest of the line. **Full-text index.** |
| `parse_status` | TEXT | — | `ok`, `variant_kill` (306 lines, `Kill` at position 9), `variant_other` (10 lines). |

Dropped as redundant (still in `raw_line`): ③ date, ⑥ node repeat.

For `variant_*` rows: fill only what is safely parsable (`label`, `ts_unix`, `ts`, `node`), rest `NULL`, `message` = text after field ⑧.

---

## 3. Table `openstack_logs`

Sources: `/data/full/OpenStack/openstack_normal1.log` (52,312), `openstack_normal2.log` (137,074), `openstack_abnormal.log` (18,434).

Example lines:

```
nova-api.log.1.2017-05-16_13:53:08 2017-05-16 00:00:00.008 25746 INFO nova.osapi_compute.wsgi.server [req-38101a0b-... 113d3a99... 54fadb41... - - -] 10.11.10.1 "GET /v2/.../servers/detail HTTP/1.1" status: 200 len: 1893 time: 0.2477829
nova-compute.log.2017-05-14_21:27:09 2017-05-14 19:39:03.166 2931 INFO nova.compute.manager [-] [instance: 2b590f10-49fd-4ec9-ae41-19596c2f4b25] VM Stopped (Lifecycle Event)
```

| Column | Type | Notes |
|---|---|---|
| `source_file` | TEXT | `normal1`, `normal2`, `abnormal`. |
| `line_no` | BIGINT | 1-based within `source_file`. Primary key = (`source_file`, `line_no`). |
| `raw_line` | TEXT | Unchanged original. |
| `log_name` | TEXT | First field, e.g. `nova-api.log.1.2017-05-16_13:53:08`. |
| `service` | TEXT | From `log_name`: `api`, `compute`, `scheduler`. |
| `ts` | TIMESTAMP | Fields 2+3, e.g. `2017-05-16 00:00:00.008`. |
| `pid` | INTEGER | |
| `level` | TEXT | INFO, WARNING, ERROR, CRITICAL. |
| `component` | TEXT | e.g. `nova.osapi_compute.wsgi.server`, `nova.compute.manager` (12 values). |
| `request_id` | TEXT | `req-...` from the bracket, `NULL` if `[-]`. |
| `instance_id` | TEXT | UUID from `[instance: ...]`, else `NULL`. |
| `http_status` | INTEGER | From `status: NNN`, else `NULL` (200, 202, 204, 404, 503). |
| `latency_s` | DOUBLE | From `time: N.NNN`, else `NULL`. |
| `message` | TEXT | Everything after the request bracket. **Full-text index.** |

---

## 4. Table `openstack_anomaly_vms`

Source: `/data/full/OpenStack/anomaly_labels.txt` (4 UUIDs, skip the header sentence).

| Column | Type | Notes |
|---|---|---|
| `instance_id` | TEXT | Primary key. Joins with `openstack_logs.instance_id`. |

Used only as ground truth for evaluation and the worked investigation, **not** as a tool input the agent can "peek" at for answers.

---

## 5. Table `team_ownership`

Fictional mapping, documented as such in the README.

| Column | Type | Notes |
|---|---|---|
| `dataset` | TEXT | `bgl` or `openstack`. |
| `component` | TEXT | Exactly as in the log tables. |
| `team` | TEXT | Fictional team name. |

Primary key = (`dataset`, `component`). Every component that appears in the logs must have exactly one row (check with an anti-join after loading).

Proposal (to be agreed):

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

---

## 6. Full-text index

`message` in `bgl_logs` and `openstack_logs` gets SereneDB's inverted index, so `search_logs` can use `@@` with BM25 ranking.
Exact DDL and analyzer: **look up with the SereneDB docs MCP before writing it** (do not guess), then paste the final statement here:

```sql
-- TODO: final CREATE INDEX statement for bgl_logs.message
-- TODO: final CREATE INDEX statement for openstack_logs.message
```

---

## 7. Evidence record (returned by every tool)

```json
{
  "results": [],
  "evidence": {
    "tool": "search_logs",
    "dataset": "bgl",
    "params": {"text": "failed to read message prefix", "limit": 5},
    "sql": "SELECT ...",
    "scope": "bgl_logs, all rows",
    "rows_matched": 253,
    "rows_returned": 5,
    "limit": 5,
    "truncated": true,
    "status": "ok"
  }
}
```

- `status`: `ok` | `not_checkable` (field missing, filter not supported, query error) | `empty` (query ran, 0 rows).
- With `not_checkable` the evidence also carries `"reason": "..."`.
- Aggregations: `truncated` is `false` unless groups were cut by `top`; `rows_matched` = number of underlying rows.
- `sql` is the exact statement sent, with parameters shown separately in `params` (no string-built SQL).

---

## 8. Tool contracts

All tools take `dataset`: `"bgl"` | `"openstack"`.
Common optional filters (`filters` object, all AND-combined): `level`, `component`, `team`, `start`, `end` (ISO timestamps), plus `node`, `rack`, `label`, `is_alert` (BGL) or `service`, `instance_id`, `request_id`, `http_status`, `source_file` (OpenStack).
`team` is resolved via `team_ownership`.

### `search_logs`
Full-text search over `message`.
- In: `dataset`, `text`, `filters?`, `limit` (default 20, max 100).
- Out `results[]`: `line_no` (+ `source_file`), `ts`, `level`, `component`, `node` / `instance_id`, `message`, `score`.

### `nearby_events`
Lines around one anchor line, in time order.
- In: `dataset`, `line_no` (+ `source_file` for OpenStack), `window_s` (default 60, max 3600), `same_entity` (bool: same `node` / `instance_id`), `limit` (default 50, max 200).
- Out `results[]`: same shape as `search_logs`, plus `offset_s` relative to the anchor.

### `count_by`
Counts grouped by one column.
- In: `dataset`, `group_by` (whitelist: `level`, `component`, `team`, `label`, `node`, `rack`, `service`, `http_status`, `instance_id`, `source_file`), `filters?`, `top` (default 20, max 100).
- Out `results[]`: `{ "key": ..., "count": ... }`, sorted by `count` desc.

### `trend`
Counts per time bucket.
- In: `dataset`, `bucket` (`minute` | `hour` | `day`), `filters?`, `text?` (optional full-text filter).
- Out `results[]`: `{ "bucket_start": ..., "count": ... }`, in time order, empty buckets included as 0.

Later (Sunday): `check_hypothesis` with check types `burst` and `rate_vs_baseline`.

---

## 9. Import check (reference counts)

| Check | Expected |
|---|---|
| `bgl_logs` rows | 4,747,963 |
| `bgl_logs` with `label = '-'` | 4,399,503 |
| `bgl_logs` with `is_alert` | 348,460 |
| `bgl_logs` with `label = 'APPREAD'` | 5,983 |
| `bgl_logs` with `parse_status <> 'ok'` | 316 |
| `openstack_logs` rows per `source_file` | normal1 52,312 · normal2 137,074 · abnormal 18,434 |
| `openstack_logs` with `http_status` not NULL | 98,733 |
| `openstack_anomaly_vms` rows | 4 |
| components without a `team_ownership` row | 0 |
