All 25 queries are done and I'm writing up the answer.

**Candidates:** For BGL, the 5 largest alert labels other than "-" (Q1). For OpenStack, the 2 largest ERROR components and the 2 largest WARNING components (Q2, Q3). Q1 was truncated (20 of 42 groups returned), so the selection is limited by it. Results are sorted largest first, so the top 5 are among the returned groups.
**Rule (an agreed heuristic, not a validated risk model):** burst means peak_share > 50%. Otherwise recurring means 5 or more active days, and limited means fewer. "Still active" means the last day falls on or after 2005-12-28 (BGL ends 2006-01-04, Q4).

### BGL top 3 (all recurring; no BGL candidate was "limited")
| # | Problem (label) | Log lines | Active days | First → last | Peak share | Still active | Component / team* | Action |
|---|---|---|---|---|---|---|---|---|
| 1 | **APPSEV**: severe application errors. Sample: "ciod: Error reading message prefix … Link has been severed" (3 lines inspected, Q25) | 49,651 | 67 | 2005-07-20 → 2006-01-03 | 7.0% | **yes** | APP / Application Runtime | Find the cause of the dropped I/O links (ciod). Check whether a few nodes or racks dominate. |
| 2 | **KERNMNTF**: kernel mount failures (meaning taken from the label name, not checked) | 31,531 | 25 | 2005-08-03 → 2006-01-03 | 13.8% | **yes** | KERNEL / Compute Platform | Review the mount/filesystem targets. Check the node spread with count_by node. |
| 3 | **KERNTERM**: kernel terminations (meaning taken from the label name, not checked) | 23,338 | 28 | 2005-07-01 → 2005-11-16 | 17.0% | no | KERNEL / Compute Platform | Lower priority. Confirm it stopped and was fixed. |

**Bursts (BGL):**
- **KERNDTLB:** 152,734 lines; 99.6% of them fell on 2005-06-11. Owner: Compute Platform. Do a one-off post-mortem of that day.
- **KERNSTOR:** 63,491 lines; 74.2% of them fell on 2005-06-14. Owner: Compute Platform. Do a one-off post-mortem.
- Neither burst peaks near the end of the dataset. Both peaks are in early June 2005. Both labels still had small tails until 2005-11-22 or 2005-11-28 (Q6, Q7).

### OpenStack (2017-05-14 → 2017-05-17, under 7 days): recurrence not assessable; not directly comparable
1. nova.virt.libvirt.imagecache WARNING: 3,059 lines. Peak 2017-05-16 (64.3%). Owner: Virtualization.
2. oslo_service.periodic_task ERROR: 192 lines. Peak 2017-05-16 (75.0%). Owner: Compute Nodes.
3. nova.compute.manager WARNING: 45 lines. Peak 2017-05-16 (62.2%). Owner: Compute Nodes.
4. keystonemiddleware.auth_token ERROR: 2 lines (1 line per day). Owner: Cloud API.

Next step: have Compute Nodes look at the periodic_task ERROR lines first, because they are errors. The imagecache warnings are a volume item for Virtualization.

\*Teams come from a fictional ownership table. Each BGL label maps to a single team (Q15–Q19). I matched the OpenStack teams to components by identical line counts (Q23, Q24), not by a component filter.

### What the data does not tell us
- **Impact:** no downtime, cost or customer impact.
- **Incidents:** the counts are log lines, not separate incidents.
- **Labels:** the meanings of KERNMNTF and KERNTERM were not checked against the messages.
- **Node spread:** not measured.
- **Sample size:** only 3 APPSEV lines were inspected, so there is no shared root cause.
- **Recency:** the datasets end in 2006 and 2017, so "still active" refers to the end of each dataset.

### Evidence (all status ok, null_timestamp_rows = 0 where reported)
| ID | Tool | Scope | rows_matched | Truncated |
|---|---|---|---|---|
| Q1 | count_by label | bgl, all | 4,747,963 | **yes** (20/42) |
| Q2 / Q3 | count_by component | openstack, level=ERROR / WARNING | 194 / 3,118 | no |
| Q4 / Q5 | trend day | bgl / openstack, all | 4,747,963 / 207,820 | no |
| Q6–Q10 | trend day | bgl, label=KERNDTLB / KERNSTOR / APPSEV / KERNMNTF / KERNTERM | 152,734 / 63,491 / 49,651 / 31,531 / 23,338 | no |
| Q11–Q14 | trend day | openstack, periodic_task+ERROR / auth_token+ERROR / imagecache+WARNING / compute.manager+WARNING | 192 / 2 / 3,059 / 45 | no |
| Q15–Q19 | count_by team | bgl, label=APPSEV / KERNMNTF / KERNTERM / KERNDTLB / KERNSTOR | per label | no |
| Q20–Q22 | count_by component | bgl, label=APPSEV / KERNMNTF / KERNTERM | per label | no |
| Q23 / Q24 | count_by team | openstack, level=ERROR / WARNING | 194 / 3,118 | no |
| Q25 | search_logs "error" | bgl, label=APPSEV | 49,651 | yes (3 shown) |

**Exact SQL:**
- **Q1:** `SELECT t.label AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component  GROUP BY t.label ORDER BY count DESC LIMIT 20`
- **Q2, Q3** (level=ERROR / WARNING): `SELECT t.component AS key, COUNT(*) AS count FROM openstack_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s GROUP BY t.component ORDER BY count DESC LIMIT 20`
- **Q4:** `SELECT date_trunc('day', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component  GROUP BY date_trunc('day', t.ts) ORDER BY bucket_start LIMIT 1000`
- **Q5:** `SELECT date_trunc('day', t.ts) AS bucket_start, COUNT(*) AS count FROM openstack_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component  GROUP BY date_trunc('day', t.ts) ORDER BY bucket_start LIMIT 1000`
- **Q6–Q10** (one label each): `SELECT date_trunc('day', t.ts) AS bucket_start, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.label = %(label)s GROUP BY date_trunc('day', t.ts) ORDER BY bucket_start LIMIT 1000`
- **Q11–Q14** (component + level each): `SELECT date_trunc('day', t.ts) AS bucket_start, COUNT(*) AS count FROM openstack_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.component = %(component)s AND t.level = %(level)s GROUP BY date_trunc('day', t.ts) ORDER BY bucket_start LIMIT 1000`
- **Q15–Q19:** `SELECT o.team AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.label = %(label)s GROUP BY o.team ORDER BY count DESC LIMIT 5`
- **Q20–Q22:** `SELECT t.component AS key, COUNT(*) AS count FROM bgl_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.label = %(label)s GROUP BY t.component ORDER BY count DESC LIMIT 5`
- **Q23, Q24:** `SELECT o.team AS key, COUNT(*) AS count FROM openstack_logs t LEFT JOIN team_ownership o ON o.dataset = %(dataset)s AND o.component = t.component WHERE t.level = %(level)s GROUP BY o.team ORDER BY count DESC LIMIT 10`
- **Q25:** `SELECT bgl_logs_message_idx.line_no, bgl_logs_message_idx.ts, bgl_logs_message_idx.level, bgl_logs_message_idx.component, bgl_logs_message_idx.node, bgl_logs_message_idx.label, bgl_logs_message_idx.message, BM25(bgl_logs_message_idx.tableoid) AS score FROM bgl_logs_message_idx WHERE bgl_logs_message_idx.message @@ %(text)s AND bgl_logs_message_idx.label = %(label)s ORDER BY score DESC, bgl_logs_message_idx.line_no LIMIT 3`