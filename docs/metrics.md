# Metrics from one frozen cut

All units are valid unique submission memberships within the selected batch unless a measure explicitly says raw lines or review pairs. Intake and state counts derive from the same frozen evidence used for accepted output. Synthetic fixture origin, seeded labels and developer adjudication remain separate. The fixture corpus diagnoses this workflow and supplies no estimate of general model accuracy.

| Measure | Numerator | Denominator and missing-data policy |
| --- | --- | --- |
| Raw intake | Every source line | `raw_lines = invalid_lines + duplicate_lines + unique_items`; exact duplicate occurrences remain visible without another unique item. |
| Accepted yield | Currently eligible accepted unique items | All valid unique batch memberships, including pending, failed and incomplete items. This explicit population prevents an accepted-only denominator. No items gives `null`. |
| Send-back rate | Unique items currently adjudicated needs-work | Unique items with current accepted, rejected or needs-work disposition. Pending reviews are excluded and separately counted. No adjudication gives `null`. Reasons are counted verbatim. |
| Machine throughput | Unique items with completed required measurements and overall passed or failed | Sum of complete measured processing segments, in seconds, covering exactly those identities once. Any crashed/incomplete, missing, overlapping or workload-mismatched segment gives `null`. A resumed-tail duration cannot represent a whole batch. |
| Review throughput | Unavailable | Active review work time is not measured. Recorded event timestamps do not establish active duration. |
| Paired-label agreement | Matching current decisions among comparable reviewer pairs | Pairs from distinct named reviewers with identical explicit submission revision, evidence digest and rubric digest. Every item may contribute multiple pairs. Unbound labels and missing judgments are excluded. Pair count and the number involving a synthetic label are reported. No comparable pairs gives `null`. |

Execution and disposition are separate dimensions. A completed item can await review or be accepted, rejected or sent back; summing all statuses would double-count it. `counts.completed_measurements` includes passed and failed completed measurements, while error, timeout, not-run and missing evidence remain explicit states. Passing weak checks does not establish semantic correctness.

`cached_results` and `recovered_results` count only explicit true annotations in stored result evidence. They do not infer timing or cache hits from a later process restart. Missing annotations provide no measured cache/recovery attribution; the audit and attempts retain their recorded history. The serial demonstration is not a controlled serial/parallel comparison and claims no speedup.

Agreement is label consistency, not verified correctness. Synthetic labels do not measure independent staff performance. Paired labels are not independent Bernoulli samples, and the authored fixture set is not a random population sample, so no confidence interval or model accuracy estimate is computed.

The API returns numerator, denominator, nullable value and an unavailable reason for rates. Machine throughput includes its covered count, complete elapsed interval when usable, segment count and unavailable reason. Empty and unassessed populations never appear as perfect performance.
