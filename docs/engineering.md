# Engineering decisions

SWE Data Workbench is an independent portfolio demonstration of processing coding submissions into a reviewed, traceable dataset. Keep informed its durable execution and audit design; no Keep installation or connection is required.

## One authority for state

SQLite stores input membership, attempts, review decisions and audit events. A state update and its audit row share a short database transaction. Long-running checks happen outside the transaction, so the review interface can read progress without holding a write lock for an entire evaluation.

The demonstration uses a local rollback journal with FULL synchronization. This small workload does not need a distributed database or message broker. Database durability remains conditional on the operating system and storage stack. Artifact files and database updates are separate operations, reconciled by content identity.

## Actual checks and human judgment

The fixture runner works on disposable copies and applies exact patches with ordinary Git. The source fixture remains intact. Check outcomes retain their actual status and output. A candidate passing visible checks remains subject to rubric review: a weak test can miss a real defect.

An adjudication binds the submission revision, check evidence and rubric. A stale browser cannot silently replace a newer decision. Seeded reviewer labels are synthetic examples. A demonstration decision performed by the developer or an automation script is identified as such; it does not represent independent expert agreement.

## Recovery with recorded intent

The application records an attempt before execution. Worker identity and generation connect the actual invocation to its result. Committed work survives restart; a result from an obsolete attempt cannot replace current evidence. A timer or lost acknowledgment alone does not prove that execution stopped. Unknown work remains visible for reconciliation.

## Honest measurements

The interface distinguishes input lines, unique submissions, duplicates, completed measurements and accepted output. Acceptance yield includes pending eligible submissions in its denominator. Throughput reports its measured interval; a recovered result is not automatically a newly processed item. A curated synthetic fixture corpus is useful for demonstrating behavior, but does not estimate general model quality or real staff productivity.

## Public inspection

The public view is a static explorer of a frozen recorded run. It has no execution or upload endpoint. Private live review uses a separate authenticated local application. Imported task text, patches and review explanations are rendered as text. A demonstration is not proof of an arbitrary-code sandbox or a production multi-tenant service.

## Attribution

Product direction and acceptance requirements are owner-led. Implementation, debugging, verification, documentation and demonstration preparation use substantial Codex assistance. Synthetic tasks and scripted decisions are labeled in the fixture/run evidence. No customer deployment or production-readiness claim is made.

