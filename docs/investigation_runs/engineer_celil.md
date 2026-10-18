## APPREAD on BGL, 2005-06-16

**Scope:** dataset `bgl`, `label = APPREAD`, ts from 2005-06-16T00:00:00 to 2005-06-17T00:00:00. The tool includes both ends of the range (`ts <= to_ts`).

### What failed (Observed)
- **Component:** APP (team "Application Runtime"; the team table is fictional). Level FATAL. The source is `ciod`, the I/O control daemon.
- **Volume:** 2,040 log lines that day (Q1, Q6). The full-text search for "failed to read message prefix" also matches all 2,040 (Q3).
- **Spread:** 510 distinct nodes (groups_total, Q1). The largest group has 4 lines, and 510 × 4 = 2,040, so every node logged exactly 4 lines.
- **Time range:** first_bucket 14:50, last_bucket 15:03. There are 6 active minutes: 14:50 (510), 14:52 (510), 14:54 (161), 14:55 (349), 15:02 (245) and 15:03 (265). Peak is 14:50 with 510 lines, peak_share 25.0% (Q6). null_timestamp_rows = 0.

### Relevant error messages
- 826075 (14:50:36.32, R37-M0-N0-I:J18-U11): `ciod: failed to read message prefix on control stream (CioStream socket to 172.16.96.116:50197`
- 826076 (14:50:36.38, R27-M1-N0-I:J18-U11): same message, port 50205
- 826077 (14:50:36.44, R35-M0-NC-I:J18-U01): same message, port 50160

### Before and after the first line of the day (826075)
**Whole system, ±60 s (Q5, truncated at 512 lines in the window):**
- −0.575 s, line 826073: `ciod: LOGIN chdir(/p/gb2/draeger/benchmark/dat32k_061605) failed: No such file or directory` (FATAL, node R20-M1-N4-I:J18-U11, label "-")
- −0.540 s, line 826074: the same chdir failure on R30-M1-N4-I:J18-U01
- The query fetched up to 15 lines before the anchor and got only these 2, so nothing else was logged in the 60 s before.
- 0 s, line 826075: the first APPREAD line
- +0.053 s to +1.225 s, lines 826076–826090: APPREAD lines on other nodes, about 30 ms apart, all to the same host 172.16.96.116 on different ports.

**Same node R37-M0-N0-I:J18-U11, ±600 s (Q4, 3 lines, not truncated):**
- No other events at all on this node, only its own APPREAD lines at 0 s (826075), +91.6 s (826638) and +259.7 s (827150).

**The chdir failure (Q10, substring "LOGIN chdir", 14:30–15:10):** 8 lines, 2 in each of the minutes 14:50, 14:52, 14:54 and 15:02. Those are 4 of the 6 APPREAD minutes. None appear in 14:55 or 15:03.

### Compared with 2005-06-04
| | 2005-06-04 | 2005-06-16 |
|---|---|---|
| APPREAD lines (Q2) | 2,040 (peak day, peak_share 34.1%) | 2,040 |
| Nodes (Q8 / Q1) | 510 | 510 |
| Message and host (Q9 / Q3) | same `failed to read message prefix ... 172.16.96.116` | same |
| Active minutes (Q7 / Q6) | 4: 00:24, 00:25, 04:45, 04:56 (510 each) | 6, between 14:50 and 15:03 |

It has the same signature: same message, same target host, same count, and same 510 nodes × 4 lines. The timing differs. On 06-04 the lines fell into four complete 510-line minutes over about 4.5 hours. On 06-16 they fell within about 13 minutes, and two of the rounds were split across minute boundaries.

### Possible cause (hypothesis)
The pattern fits a job-level event rather than separate faults on individual nodes, but this is not proven. A plausible sequence is that the job could not start because its working directory `/p/gb2/draeger/benchmark/dat32k_061605` did not exist, and then the ciod control streams to 172.16.96.116 broke on all 510 nodes. The two errors appear together in 4 of 6 minutes, which suggests a link but does not prove one. I ran nearby_events around only 1 of the 2,040 lines. What came before or after the other lines is unknown. A network or service problem on 172.16.96.116 is not ruled out. A similar pattern on 06-04 does not show the same cause.

### Next checks
1. Run `search_logs text="LOGIN chdir"` for 2005-06-04, then `nearby_events` at line 14738 (the first 06-04 APPREAD line in Q9). This shows whether the 06-04 burst was also preceded by a chdir failure.
2. Run `nearby_events` at the first line of the 14:55 and 15:03 rounds. Those minutes had no chdir lines, so this would test the hypothesis.

### Evidence
| query_id | tool | scope | rows_matched | truncated |
|---|---|---|---|---|
| Q1 | count_by node | bgl, 06-16, label=APPREAD | 2040 | true (510 groups) |
| Q2 | trend day | bgl, label=APPREAD, all time | 5983 | false |
| Q3 | search_logs | bgl, "failed to read message prefix", label=APPREAD, 06-16 | 2040 | true |
| Q4 | nearby_events | line 826075, node R37-M0-N0-I:J18-U11, ±600 s | 3 | false |
| Q5 | nearby_events | line 826075, all nodes, ±60 s | 512 | true |
| Q6 | trend minute | bgl, 06-16, label=APPREAD | 2040 | false |
| Q7 | trend minute | bgl, 06-04, label=APPREAD | 2040 | false |
| Q8 | count_by node | bgl, 06-04, label=APPREAD | 2040 | true (510 groups) |
| Q9 | search_logs | bgl, "failed to read message prefix", label=APPREAD, 06-04 | 2040 | true |
| Q10 | trend minute | bgl, "LOGIN chdir", 06-16 14:30–15:10 | 8 | false |

**SQL of each query**
- **Q1:** `SELECT t.node AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND t.label = %(label)s GROUP BY t.node ORDER BY count DESC LIMIT 20`
- **Q2:** `SELECT date_trunc('day', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.label = %(label)s GROUP BY date_trunc('day', t.ts) ORDER BY bucket_start LIMIT 1000`
- **Q3:** `SELECT bgl_logs_message_idx.line_no, bgl_logs_message_idx.ts, bgl_logs_message_idx.level, bgl_logs_message_idx.component, bgl_logs_message_idx.node, bgl_logs_message_idx.label, bgl_logs_message_idx.message, BM25(bgl_logs_message_idx.tableoid) AS score FROM bgl_logs_message_idx WHERE bgl_logs_message_idx.message @@ %(text)s AND bgl_logs_message_idx.label = %(label)s AND bgl_logs_message_idx.ts >= %(from_ts)s AND bgl_logs_message_idx.ts <= %(to_ts)s ORDER BY score DESC, bgl_logs_message_idx.line_no LIMIT 20`
- **Q4:** `SELECT t.line_no, t.ts, t.level, t.component, t.node, t.label, t.message, o.team FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND t.node = %(node)s AND (t.ts < %(anchor)s OR (t.ts = %(anchor)s AND t.line_no <= %(anchor_line)s)) ORDER BY t.ts DESC, t.line_no DESC LIMIT 25; SELECT t.line_no, t.ts, t.level, t.component, t.node, t.label, t.message, o.team FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND t.node = %(node)s AND (t.ts > %(anchor)s OR (t.ts = %(anchor)s AND t.line_no > %(anchor_line)s)) ORDER BY t.ts, t.line_no LIMIT 25`
- **Q5:** `SELECT t.line_no, t.ts, t.level, t.component, t.node, t.label, t.message, o.team FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND (t.ts < %(anchor)s OR (t.ts = %(anchor)s AND t.line_no <= %(anchor_line)s)) ORDER BY t.ts DESC, t.line_no DESC LIMIT 15; SELECT t.line_no, t.ts, t.level, t.component, t.node, t.label, t.message, o.team FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND (t.ts > %(anchor)s OR (t.ts = %(anchor)s AND t.line_no > %(anchor_line)s)) ORDER BY t.ts, t.line_no LIMIT 15`
- **Q6 and Q7** (same SQL, different date range): `SELECT date_trunc('minute', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s AND t.label = %(label)s GROUP BY date_trunc('minute', t.ts) ORDER BY bucket_start LIMIT 1000`
- **Q8:** same as Q1 but with `LIMIT 5`
- **Q9:** same as Q3 but with `LIMIT 3`
- **Q10:** `SELECT date_trunc('minute', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE LOWER(t.message) LIKE %(text)s AND t.ts >= %(from_ts)s AND t.ts <= %(to_ts)s GROUP BY date_trunc('minute', t.ts) ORDER BY bucket_start LIMIT 1000`