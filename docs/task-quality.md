# Task quality, credit and repair

A task context binds the complete task definition, source identity, checks, protected verifier bytes, rubric, role declarations and provenance. Task findings and decisions become immutable content-addressed artifacts referenced by the existing schema1 audit/store. Review revisions increase across versions of the same task in one database so a stale request cannot match a newer draft by accident.

The private owner API adds:

| Operation | Route |
|---|---|
| Read actual task-specific scores | GET /api/batches/{id}/evaluation |
| Record task findings and decision | POST /api/tasks/{id}/quality |
| Record separate reviews and author feedback | POST /api/tasks/{id}/calibration |
| Freeze every candidate outcome | POST /api/batches/{id}/evaluation-export |

Mutations keep the existing bearer, exact Origin and strict bounded JSON boundary. The browser exposes a findings editor, task review, recorded calibration and separate evaluation export. Generic accepted-code review remains unchanged.

Task decisions are draft, needs-repair, quarantined or approved. Approval requires a clean task kind, passing bound evidence from distinct declared reference and alternate patches, and no open high/critical findings. Medium coverage limitations stay visible. Approval establishes membership of this explicitly scoped task profile; it cannot prove exhaustive correctness of every possible implementation.

Each rubric criterion maps to named checks and nonnegative integer points. Known failure earns zero for that criterion; missing, stale or unresolved execution earns null. A critical gate is separate from the total. The ingestion recipe assigns 25 ordinary, 25 identity and 50 recovery; the buggy control retains 50 regression points after its critical recovery failure.

## Observed repair

weak-v1 falsely passed an authored unchanged-behavior control. The first fixed-v2 exposed replay double-counting but did not establish that the event was durable before the callback. Two separately recorded AI-assisted reviews identified this gap. Their original inputs and outputs remain under examples/ingest-recovery/calibration; those preliminary states are separate from the finalized run.

fixed-v3 checks pre-replay state and complete-source replay after exit and callback exceptions at two source positions. It also adds parsing boundaries, a real CLI call and a saved original-state fixture. The same reference, alternate, recorded candidate and negative control are measured against both final comparison versions. No candidate is regenerated to improve the outcome.

The reference stores total and receipt atomically; the alternate derives totals from the receipt ledger. Both are accepted by observed public behavior. Signed64 aggregate overflow remains unmeasured and explicitly open. The prototype does not replace that missing observation with a score or a claim of exhaustive coverage.

Calibration preserves each review's exact input/output digest, declared judgment and involvement. The recorded pair examined weak-v1/fixed-v2; v3 author resolution is a subsequent decision, not a retroactive change to their judgments. One reviewer implemented the worker, and one authored the candidate. Agreement summarizes those declared judgments and does not establish independence or correctness.

The account-free driver and video explicitly replay the recorded assessment through real functions/controls. Execution and export bytes are newly measured by those runs. Review reasons remain attributed to their original assisted assessment rather than fabricated new people or model requests.
