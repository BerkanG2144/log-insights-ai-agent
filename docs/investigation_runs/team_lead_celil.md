# FATAL problems that recur in BGL (full dataset)

## Period and scope
- **Dataset:** bgl, all 4,747,963 log lines, from 2005-06-03 15:42 to 2006-01-04 08:00. No lines lack a timestamp (Q1).
- **Filter:** level = FATAL, which leaves **855,501 log lines** (Q2).
- **Problem:** each problem below is one BGL alert `label`. Label "-" means the line has no alert label.
- **Teams:** these come from the fictional `team_ownership` table, matched on component.
- **Components:** FATAL lines come from KERNEL 626,756, APP 228,536, LINKCARD 206 and MMCS 3 (Q4).
- **Teams:** Compute Platform 626,756, Application Runtime 228,536, Network 206 and Control System 3 (Q2). groups_total = 4 for both.

## Recurring problems

"Share" means share of all 855,501 FATAL lines. Active days, first day and last day are taken from each problem's own daily trend.

| Problem (label) | Log lines | Share of FATAL | Active days | First day | Last day | Component | Team | Racks (groups_total) |
|---|---|---|---|---|---|---|---|---|
| "-" (FATAL, no alert label) | 507,103 | 59.3% | 196 | 2005-06-03 | 2006-01-03 | KERNEL 342,412 / APP 164,691 (Q11) | Compute Platform / Application Runtime | 65; top R27 56,921 (Q17) |
| KERNDTLB | 152,734 | 17.9% | 11 | 2005-06-05 | 2005-11-28 | KERNEL (Q12) | Compute Platform | 29; **R30 = 152,202** (Q18) |
| KERNSTOR | 63,491 | 7.4% | 5 | 2005-06-13 | 2005-11-22 | KERNEL (Q13) | Compute Platform | 23; top racks about 3,072 each (Q19) |
| APPSEV | 49,651 | 5.8% | **67** | 2005-07-20 | 2006-01-03 | APP (Q14) | Application Runtime | 64; top R27 922 (Q20) |
| KERNMNTF | 31,531 | 3.7% | 25 | 2005-08-03 | 2006-01-03 | KERNEL (Q15) | Compute Platform | 64; top R00 677 (Q21) |
| KERNTERM | 23,338 | 2.7% | 28 | 2005-07-01 | 2005-11-16 | KERNEL (Q16) | Compute Platform | 64; top R63 2,737 (Q22) |

The other 31 FATAL labels add up to 27,653 lines, 3.2% (Q3). I did not run trends for them, so whether they recur is not measured.

## Pattern over time (each from its own trend)
- **"-" unlabeled FATAL (Q10):** present almost all the time, on 196 active days. The peak was 2005-06-14 with 295,244 lines, 58.2% of this problem's lines. Lines reappear in bursts of 1,000 to 23,000 per day (2005-08-12, 2005-09-20, 2005-12-09) up to 2006-01-03.
- **KERNDTLB (Q5):** essentially one event. 2005-06-11 holds 152,182 lines (99.6%), and almost all of the problem's lines are on rack R30. The small tail after that is under 31 lines per day.
- **KERNSTOR (Q6):** 2005-06-13 and 2005-06-14 together hold 63,488 lines; the peak on 06-14 is 74.2%. After that there is only 1 line each on 3 days in November. The burst falls on the same days as the unlabeled peak. That is consistent with one shared event but not proven.
- **APPSEV (Q7):** the most steadily recurring problem. It appeared on 67 days in a row of separate bursts, and the peak (2005-11-26, 3,466 lines) is only 7.0%. It got heavier from mid-November to December and was still active on the last day of data.
- **KERNMNTF (Q8):** an intense spell from 2005-08-31 to 2005-09-13 (peak 2005-09-03, 4,352 lines, 13.8%). After that it returned every few weeks until 2006-01-03.
- **KERNTERM (Q9):** recurred from July to November (peak 2005-08-17, 3,967 lines, 17.0%). Several days count exactly 512, 1,024 or 2,048 lines. That looks like whole blocks of nodes reporting at once, but this is not proven. No lines after 2005-11-16.

## Example lines (2 of each problem inspected)
- KERNDTLB: `data TLB error interrupt` (Q23)
- KERNSTOR: `data storage interrupt` (Q24)
- APPSEV: `ciod: Error reading message prefix after LOGIN_MESSAGE on CioStream socket to 172.16.96.116:56214: Link has been severed` (Q25)
- KERNMNTF: `Lustre mount FAILED : bglio11 : block_id : location` (Q26)
- KERNTERM: `rts: kernel terminated for reason 1004rts: bad message header: expecting type 1, type=3, ...` (Q27)
- Unlabeled KERNEL: `critical input interrupt enable...0` (Q29). 86,752 of the 342,412 unlabeled KERNEL lines contain "interrupt".
- Unlabeled APP: `ciod: Error loading /p/gb2/.../raptor: invalid or missing program image, No such file or directory` (Q28). 164,551 of the 164,691 unlabeled APP lines contain "ciod".

## What to investigate first
1. **APPSEV, Application Runtime.** Investigate this first because it is the most persistent: 67 active days, no dominant day, 64 racks, and still active on 2006-01-03. Possible explanation: ciod losing its socket link to the I/O hosts. That is a hypothesis.
2. **KERNMNTF, Compute Platform.** Lustre mounts failed on 25 days across 64 racks, and it is still active at the end of the data. Possible explanation: a storage or I/O-node problem. Not proven.
3. **The 2005-06-13/14 event, Compute Platform.** 295,244 unlabeled FATAL lines and 63,488 KERNSTOR lines fall on these two days. Next check: run `nearby_events` around the first KERNSTOR line (line 382963) to see what came before it.
4. **KERNTERM, Compute Platform.** It recurred over 28 days and then stopped after 2005-11-16. Check whether a fix landed around that date, and why rack R63 has 2,737 lines.
5. **KERNDTLB.** It has the largest line count among labeled problems, but it was a single burst on R30 on 2005-06-11. Treat it as one past event on R30, not a recurring problem.

**Unknown:**
- The unlabeled "-" FATAL lines (59% of all FATAL lines) carry no alert category. Many look like register dumps and program-load errors. Which of them are real failures is not established.
- Line counts are not incidents. One event can produce thousands of lines; KERNTERM's counts of exactly 512 and 1,024 suggest this.
- Node-level spread was not measured; only racks were.

## Evidence

| query_id | tool | scope | rows_matched | truncated |
|---|---|---|---|---|
| Q1 | describe_dataset | bgl_logs, all rows | 4,747,963 | false |
| Q2 | count_by team | level=FATAL | 855,501 | false |
| Q3 | count_by label | level=FATAL | 855,501 | false |
| Q4 | count_by component | level=FATAL | 855,501 | false |
| Q5 | trend day | FATAL, label=KERNDTLB | 152,734 | false |
| Q6 | trend day | FATAL, label=KERNSTOR | 63,491 | false |
| Q7 | trend day | FATAL, label=APPSEV | 49,651 | false |
| Q8 | trend day | FATAL, label=KERNMNTF | 31,531 | false |
| Q9 | trend day | FATAL, label=KERNTERM | 23,338 | false |
| Q10 | trend day | FATAL, label=- | 507,103 | false |
| Q11 | count_by component | FATAL, label=- | 507,103 | false |
| Q12 | count_by component | FATAL, label=KERNDTLB | 152,734 | false |
| Q13 | count_by component | FATAL, label=KERNSTOR | 63,491 | false |
| Q14 | count_by component | FATAL, label=APPSEV | 49,651 | false |
| Q15 | count_by component | FATAL, label=KERNMNTF | 31,531 | false |
| Q16 | count_by component | FATAL, label=KERNTERM | 23,338 | false |
| Q17 | count_by rack (limit 5) | FATAL, label=- | 507,103 | true (65 groups) |
| Q18 | count_by rack (limit 5) | FATAL, label=KERNDTLB | 152,734 | true (29 groups) |
| Q19 | count_by rack (limit 5) | FATAL, label=KERNSTOR | 63,491 | true (23 groups) |
| Q20 | count_by rack (limit 5) | FATAL, label=APPSEV | 49,651 | true (64 groups) |
| Q21 | count_by rack (limit 5) | FATAL, label=KERNMNTF | 31,531 | true (64 groups) |
| Q22 | count_by rack (limit 5) | FATAL, label=KERNTERM | 23,338 | true (64 groups) |
| Q23 | search_logs "data TLB error interrupt" | FATAL, KERNDTLB | 152,734 | true |
| Q24 | search_logs "data storage interrupt" | FATAL, KERNSTOR | 63,491 | true |
| Q25 | search_logs "ciod error" | FATAL, APPSEV | 49,651 | true |
| Q26 | search_logs "lustre mount failed" | FATAL, KERNMNTF | 31,531 | true |
| Q27 | search_logs "kernel terminated" | FATAL, KERNTERM | 23,338 | true |
| Q28 | search_logs "ciod" | FATAL, label=-, APP | 164,551 | true |
| Q29 | search_logs "interrupt" | FATAL, label=-, KERNEL | 86,752 | true |

### Exact SQL
The tools ran these statements with bound parameters (`%(name)s`). In every query, `dataset = 'bgl'` and `level = 'FATAL'`, except Q1, which has no level filter. Queries that share the same SQL text are listed together, with each query's bound values.

**Q1** (describe_dataset):
```sql
SELECT COUNT(*) AS n, MIN(t.ts) AS first_ts, MAX(t.ts) AS last_ts, COUNT(*) - COUNT(t.ts) AS null_ts FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component; SELECT t.level AS value, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component GROUP BY 1 ORDER BY count DESC, value; SELECT t.component AS value, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component GROUP BY 1 ORDER BY count DESC, value; SELECT o.team AS value, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component GROUP BY 1 ORDER BY count DESC, value; SELECT t.label AS value, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component GROUP BY 1 ORDER BY count DESC, value
```
**Q2:**
```sql
SELECT o.team AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s GROUP BY o.team ORDER BY count DESC LIMIT 20
```
**Q3:**
```sql
SELECT t.label AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s GROUP BY t.label ORDER BY count DESC LIMIT 50
```
**Q4:**
```sql
SELECT t.component AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s GROUP BY t.component ORDER BY count DESC LIMIT 20
```
**Q5 to Q10** (label = KERNDTLB, KERNSTOR, APPSEV, KERNMNTF, KERNTERM, "-"):
```sql
SELECT date_trunc('day', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s AND t.label = %(label)s GROUP BY date_trunc('day', t.ts) ORDER BY bucket_start LIMIT 1000
```
**Q11 to Q16** (label = "-", KERNDTLB, KERNSTOR, APPSEV, KERNMNTF, KERNTERM):
```sql
SELECT t.component AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s AND t.label = %(label)s GROUP BY t.component ORDER BY count DESC LIMIT 20
```
**Q17 to Q22** (label = "-", KERNDTLB, KERNSTOR, APPSEV, KERNMNTF, KERNTERM):
```sql
SELECT t.rack AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s AND t.label = %(label)s GROUP BY t.rack ORDER BY count DESC LIMIT 5
```
**Q23 to Q27** (text/label pairs: "data TLB error interrupt"/KERNDTLB, "data storage interrupt"/KERNSTOR, "ciod error"/APPSEV, "lustre mount failed"/KERNMNTF, "kernel terminated"/KERNTERM):
```sql
SELECT bgl_logs_message_idx.line_no, bgl_logs_message_idx.ts, bgl_logs_message_idx.level, bgl_logs_message_idx.component, bgl_logs_message_idx.node, bgl_logs_message_idx.label, bgl_logs_message_idx.message, BM25(bgl_logs_message_idx.tableoid) AS score FROM bgl_logs_message_idx WHERE bgl_logs_message_idx.message @@ %(text)s AND bgl_logs_message_idx.level = %(level)s AND bgl_logs_message_idx.label = %(label)s ORDER BY score DESC, bgl_logs_message_idx.line_no LIMIT 2
```
**Q28** (text = "ciod", component = APP, label = "-") and **Q29** (text = "interrupt", component = KERNEL, label = "-"):
```sql
SELECT bgl_logs_message_idx.line_no, bgl_logs_message_idx.ts, bgl_logs_message_idx.level, bgl_logs_message_idx.component, bgl_logs_message_idx.node, bgl_logs_message_idx.label, bgl_logs_message_idx.message, BM25(bgl_logs_message_idx.tableoid) AS score FROM bgl_logs_message_idx WHERE bgl_logs_message_idx.message @@ %(text)s AND bgl_logs_message_idx.component = %(component)s AND bgl_logs_message_idx.level = %(level)s AND bgl_logs_message_idx.label = %(label)s ORDER BY score DESC, bgl_logs_message_idx.line_no LIMIT 2
```