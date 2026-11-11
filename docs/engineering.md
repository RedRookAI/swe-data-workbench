# Engineering decisions

SWE Data Workbench is an independent portfolio demonstration of processing coding submissions into a reviewed, traceable dataset. Keep informed its durable execution and audit design; no Keep installation or connection is required.

## One authority for state

SQLite stores input membership, attempts, review decisions and audit events. A state update and its audit row share a short database transaction. Long-running checks happen outside the transaction, so the review interface can read progress without holding a write lock for an entire evaluation.

The demonstration uses a local rollback journal with FULL synchronization. This small workload does not need a distributed database or message broker. Database durability remains conditional on the operating system and storage stack. Artifact files and database updates are separate operations, reconciled by content identity.

## Actual checks and human judgment

The trusted-task runner works on disposable copies and applies exact patches with ordinary Git. The pinned source remains intact. Check outcomes retain their actual status and output. A candidate passing visible checks remains subject to rubric review: a weak test can miss a real defect.

An adjudication binds the submission revision, check evidence and rubric. A stale browser cannot silently replace a newer decision. Seeded reviewer labels are synthetic examples. A demonstration decision performed by the developer or an automation script is identified as such; it does not represent independent expert agreement.

## Recovery with recorded intent

The application records an attempt before execution. Worker identity and generation connect the actual invocation to its result. Committed work survives restart; a result from an obsolete attempt cannot replace current evidence. A timer or lost acknowledgment alone does not prove that execution stopped. Unknown work remains visible for reconciliation.

## Honest measurements

The interface distinguishes input lines, unique submissions, duplicates, completed measurements and accepted output. Acceptance yield includes pending eligible submissions in its denominator. Throughput reports its measured interval; a recovered result is not automatically a newly processed item. A curated synthetic fixture corpus is useful for demonstrating behavior, but does not estimate general model quality or real staff productivity.

## Public inspection

The public view is a static explorer of a frozen recorded run. It has no execution or upload endpoint. Private live review uses a separate authenticated local application. Imported task text, patches and review explanations are rendered as text. A demonstration is not proof of an arbitrary-code sandbox or a production multi-tenant service.

## Attribution

Product direction and acceptance requirements are owner-led. Implementation, debugging, verification, documentation and demonstration preparation use substantial Codex assistance. Public source/patch provenance, synthetic controls and scripted decisions are labeled in the bundle/run evidence. No customer deployment or production-readiness claim is made.


## Real-case integration

The owner selects a local bundle before serving/importing it. SWE-bench-style fields map into the same intake authority as native records. Exact raw bytes remain attached to every occurrence, including duplicates with distinct publisher/model declarations. Those declarations do not grant execution permission or prove authorship. The snapshot/export verifier checks the retained claims against the raw record.

The complete upstream Git diff exposed an ancestor-discovery problem: Git can return success after skipping paths outside a nested directory prefix. Each disposable command now stops Git discovery at its workspace parent. A regression verifies actual changed candidate bytes under an enclosing repository and preserves both baseline and ancestor metadata. Existing ordinary path validation remains intact.

Reviewer mode is an explicit recorded attribute. Owner, developer, AI-assisted and scripted decisions have the same exact-evidence acceptance requirements. This field records an operator declaration; it does not independently authenticate the named person or review quality. The shipped assessment plan documents the examined semantic reasons and refuses changed source/check/rubric identities or unexpected actual outcomes.

## Read-only local preparation

The prepare-bundle command reads explicitly selected committed Git blobs, check argv and exact patch/prediction bytes. It generates the existing catalog format and an inspectable preparation summary. Selection is deliberate operator admission; structural validation does not certify code safety. Git working copies are never reset or checked out, and untracked/dirty bytes do not enter the pinned source snapshot. Partial clones and unsupported source modes/types are refused. Preparation dispatches before Workbench initialization, so it creates no runtime database. A staged, fsynced Linux no-replace publication preserves existing inputs and outputs.

## Capture while commands run

The v3 worker concurrently drains both nonblocking pipes with a selector. Each stream retains at most65536 payload bytes; reads are at most16384 bytes and excess is discarded. UTF-8 replacement decoding, attempt-path redaction and actual exit status remain available. The monotonic deadline is checked even when output is continuously ready. Timeout closes descriptors and reaps the owned direct child with finite cleanup; the controller's existing group/uncertain reconciliation remains authoritative. This bounds retained output, not total child memory or hostile-code behavior. Historical v1/v2 evidence retains its identities.
