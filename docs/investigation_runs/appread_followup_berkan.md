# Supplementary APPREAD check: did the June 4 burst also follow a chdir failure?

This is a separate follow-up to the original engineer run, not a replacement role run. It calls the existing read-only server functions directly, without an LLM session. Query IDs Q1–Q3 below belong only to this follow-up. No application code or database contents were changed.

Executed at 2026-10-18T15:05:44.701351+00:00 (UTC), with application code at commit `13a537b31507ca1ae5adda485626f887acd69e5c`. The machine-readable query results are retained in a local backup and are not published here. Tool inputs, result counts, selected observations and reported SQL are documented below. This is not a full trace of internal helper queries or complete SQL bindings.

## Observed

- **Eight** full-text phrase matches for `LOGIN chdir` on 2005-06-04; all eight results were returned (follow-up Q1). Each reports `No such file or directory`.
- Immediately before APPREAD line **14738**, at `00:24:32.398284`, there are two chdir failures: line **14736**, **0.838 s before**, and line **14737**, **0.804 s before** (follow-up Q2). Both name `/p/gb2/draeger/benchmark/dat32k_060205`. They occur on different nodes from the anchor APPREAD line.
- In the all-node ±60 s context window, **991** lines match and **23** are returned (follow-up Q2, truncated). Only two precede the anchor; both are the chdir failures. The returned context does not cover every later line in the window.
- A separate substring trend finds **two chdir lines in each of four minutes**: `00:24`, `00:25`, `04:45`, `04:56` (follow-up Q3, not truncated). These are also the four APPREAD minutes in the original engineer run (Celil engineer Q7). Same-minute counts do not establish event order for each later group.
- The eight chdir messages involve two paths: the benchmark path above for the first four, and `/p/gb2/glosli` for the final four (follow-up Q1). A single missing directory does not explain the entire day.

## Interpretation and limits

The inspected first APPREAD occurrence on **both June 4 and June 16** is immediately preceded by two failed working-directory changes (follow-up Q2 versus Celil engineer Q5). This repeated temporal pattern strengthens the hypothesis of a job-start or working-directory problem associated with the ciod errors. It does **not** prove that the chdir failure caused the APPREAD errors, that both days share one root cause, or that every APPREAD group follows the same sequence.

Only the first APPREAD occurrence on June 4 was examined with nearby_events in this follow-up. The paths differ across the two days and within June 4. Network or peer-host problems remain possible.

## Next diagnostic step

Inspect the earliest APPREAD line in each remaining time group and correlate it with job identifiers or scheduler records, if available. That would test ordering and job association rather than relying on same-minute counts.

## Evidence

| Follow-up ID | Tool | Scope | Matched | Returned | Truncated |
| --- | --- | --- | --- | --- | --- |
| Q1 | `search_logs` | bgl_logs_message_idx (bgl_logs), message matches 'LOGIN chdir' (full-text phrase, adjacent ordered tokens), ts >= 2005-06-04T00:00:00, ts <= 2005-06-04T23:59:59.999999 | 8 | 8 | false |
| Q2 | `nearby_events` | bgl_logs, ts >= 2005-06-04 00:23:32.398284, ts <= 2005-06-04 00:25:32.398284 | 991 | 23 | true |
| Q3 | `trend` | bgl_logs, message contains 'LOGIN chdir' (substring), ts >= 2005-06-04T00:00:00, ts <= 2005-06-04T23:59:59.999999 | 8 | 4 | false |

## Reproduce with the existing server functions

From the repository root, with the project virtual environment active and the loaded database running:

```python
import sys
sys.path.insert(0, "server")
import server

server.search_logs(**{'dataset': 'bgl', 'text': 'LOGIN chdir', 'phrase': True, 'from_ts': '2005-06-04T00:00:00', 'to_ts': '2005-06-04T23:59:59.999999', 'limit': 100})
server.nearby_events(**{'dataset': 'bgl', 'line_no': 14738, 'window_seconds': 60, 'limit': 40})
server.trend(**{'dataset': 'bgl', 'bucket': 'minute', 'text': 'LOGIN chdir', 'from_ts': '2005-06-04T00:00:00', 'to_ts': '2005-06-04T23:59:59.999999'})
```

## Executed SQL

These are the SQL statements exposed by the tools, not every internally executed statement. The reproduction section gives tool inputs; computed anchor/window bindings and all internal count queries are not included as executable SQL-parameter pairs. Full returned rows remain in local evidence backups.

### Q1

```sql
SELECT bgl_logs_message_idx.line_no, bgl_logs_message_idx.ts, bgl_logs_message_idx.level, bgl_logs_message_idx.component, bgl_logs_message_idx.node, bgl_logs_message_idx.label, bgl_logs_message_idx.message, BM25(bgl_logs_message_idx.tableoid) AS score FROM bgl_logs_message_idx WHERE bgl_logs_message_idx.message @@ phraseto_tsquery(%(text)s) AND bgl_logs_message_idx.ts >= %(from_ts)s AND bgl_logs_message_idx.ts <= %(to_ts)s ORDER BY score DESC, bgl_logs_message_idx.line_no LIMIT 100
```

### Q2

```sql
SELECT t.line_no, t.ts, t.level, t.component, t.node, t.label, t.message, o.team FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND (t.ts < %(anchor)s OR (t.ts = %(anchor)s AND t.line_no <= %(anchor_line)s)) ORDER BY t.ts DESC, t.line_no DESC LIMIT 20; SELECT t.line_no, t.ts, t.level, t.component, t.node, t.label, t.message, o.team FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND (t.ts > %(anchor)s OR (t.ts = %(anchor)s AND t.line_no > %(anchor_line)s)) ORDER BY t.ts, t.line_no LIMIT 20
```

### Q3

```sql
SELECT date_trunc('minute', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE LOWER(t.message) LIKE %(text)s AND t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s GROUP BY date_trunc('minute', t.ts) ORDER BY bucket_start LIMIT 1000
```
