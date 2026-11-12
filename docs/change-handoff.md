# A portable real-change handoff

The real-change path reads explicit base/candidate Git objects and owner-selected UTF-8 evidence into the existing schema1 artifact/audit store. It does not execute the input project, import its database, change its checkout or create accepted-code/task-evaluation results.

The owner CLI supplies five operations: capture-handoff, handoff, review-handoff, export-handoff and verify-handoff. Capture uses a request with change_id, title, goal, repository and observations. Each observation identifies a named evidence attachment, a dictionary-key field_path, scope and required flag. An optional context_path identifies the source revision declared by that report. Embedded commands, paths and URLs are inert data.

Capture supports changed100644UTF8 regular files and existing local Git objects. It reuses the8MiB input limit and refuses unsupported files or oversized input. State must be separate from the source repository. Local hooks, external diff and text conversion are disabled. Before/after Git blob IDs, SHA256s, patch bytes and evidence bytes remain inspectable.

Source binding has three explicit states: declared-same-source, declared-other-source or unbound. None means the workbench independently executed the reported checks. Missing required evidence or a different declared source blocks a handoff-ready decision. That decision denotes review-package readiness; it does not grant code acceptance, merge or release authority.

Every review binds the current material digest and revision. Changed relevant material resets the current review; an unrelated source HEAD move does not alter a frozen pair of commits. Repeated identical capture is idempotent. A retried operation returns its original response while a distinct stale review is rejected.

The three-file export contains handoff.json, artifacts.json and manifest.json. It verifies the exact file set, historical material/state artifacts, selected audit-event hashes, source blobs and rendered observation values. It deliberately exports only this change's events, so unrelated private audit data is excluded. The selected event set is not represented as a complete global audit chain. Local hashes establish consistency rather than external custody, actor authentication or execution truth.

## What the real trial established

The input was another instance's actual Keep sandbox-preflight correction, not a manufactured failing patch. Read-only source inspection and its published qualification report distinguished .22 source from the .21 archive. Existing reports cover partial CI, supported-host preparation and restricted-host refusal; this operator did not rerun Keep or change its publication.

One fresh-context AI-assisted review, given only the first export, explained the change and detected unclear revision provenance. The subsequently retained public workflow explicitly checks out the product candidate. The fixture harness creates a separate repository whose commit is written as receipt.sourceRevision. The final package explains these roles, retaining the original review finding and its exact original input identities.

The product decision is to retain this as an optional portable handoff and keep the integration small. It adds a self-contained diff, exact evidence and review history, with a useful source-versus-download distinction. A concise Git/report handoff can answer the same substantive questions. Per-change mapping and once-only feature construction add overhead, and human productivity improvement has not been measured. The trial does not justify a new orchestration platform or mandatory use on every change.
