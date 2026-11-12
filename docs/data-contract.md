# Frozen export contract

An export is a durable snapshot from `Workbench.prepare_export`, published by `export_batch`. SQLite remains the authority. The exporter creates no second database and performs no review writes.

The three downloadable files are:

- `accepted.jsonl`: full, unique eligible item records, ordered lexicographically by submission ID. Exact task text, patch whitespace and final newlines within strings are preserved. The file is empty when no item qualifies.
- `evidence.json`: the frozen batch, all unique items including incomplete items, full audit prefix, cut, runtime identities and timing segments. `artifacts` maps each result's SHA-256 to the base64 encoding of its exact stored evidence bytes. `export_schema` is `swe-workbench-export-v1`.
- `manifest.json`: schema, export ID, batch ID, audit cut, accepted IDs, measured metrics, byte lengths and SHA-256 hashes of the other two files. Its own SHA-256 names the publication directory and is recorded by core when ready.

Export files use UTF-8 JSON with sorted object keys, compact separators, `ensure_ascii=False`, `allow_nan=False`, and a final LF. Each JSONL record has its own LF. Lists retain their semantic order except the top-level items and audit events, which sort by ID and sequence respectively. This is a project serialization, not a claim of RFC 8785 compatibility. Generation timestamps and output paths are absent from export content. Core audit events and machine artifacts use the same JSON settings **without** the final LF; their exact original bytes are retained for digest verification.

An accepted record must have completed passing machine evidence, preserved source, existing checks, valid source/patch/check/rubric digests and an authoritative recorded adjudication with all five criteria passing. The review's evidence and rubric must match the item. `review.submission_revision` is the state revision inspected; the review commit increments `item.revision` by one. The corresponding `submission-reviewed` audit event must bind the same item, committed revision, actor and complete review payload. Synthetic seeded reviews cannot authorize acceptance. Controlled reviewer modes are developer_adjudication, ai_assisted_adjudication, owner_adjudication and scripted_adjudication; each uses the same eligibility checks, and audit actor remains the authorized operator. Legacy developer reviews remain verifiable. Invalid accepted state fails export; the exporter does not silently drop it.

Offline verification checks canonical file bytes, exact accepted membership, counts, machine artifact hashes and contents, exact submission/source/patch/check/rubric bindings within the machine artifact, patch bytes against their digest, the review's exact evidence/rubric/revision binding, and the audit chain through the manifest cut. An audit event hashes the canonical event without `hash`; the genesis previous hash is 64 zeroes. Referenced source/check/rubric hashes identify the pinned inputs; the corresponding implementation and authored fixture catalog live in the source distribution. Verification establishes consistency of this evidence bundle. An administrator able to rewrite the entire chain and all references can replace it; independent custody is not claimed.

Core freezes the snapshot in one read/write transaction before publication and stores that exact snapshot in a pending export row. Its cut is the last event whose kind is not prefixed `export-`. The full prefix through that cut is retained, including any earlier export events. Creating or completing an export alone therefore leaves the data identity unchanged. A later substantive event advances the cut and can create a new snapshot. Old directories remain immutable and identify their original cut; comparing later manifests establishes which cut is newer.

Publication writes a temporary sibling directory, flushes each file, fsyncs files and directory, renames it to the manifest hash, fsyncs the parent, verifies all contents and only then invokes `complete_export`. Filesystem publication and the SQL ready update are separate operations. An interruption before publication leaves the row pending. An interruption after publication reuses the same prepared snapshot and verifies the existing directory before completion. Partial temporary directories are never returned as ready; surviving orphans are private and are not automatically collected. Concurrent publication can reuse identical verified content. Storage guarantees depend on local filesystem and device behavior.

`verify_export(path)` is read-only and returns `ok`, `errors` and, on success, the exact manifest digest and accepted count. Missing files, symlinks, unexpected files, changed evidence, stale acceptance or inconsistent hashes fail verification. These files contain imported text and must be rendered as inert text by consumers.

The public builder accepts a verified export and copies only `index.html`, `app.js`, `style.css`/`styles.css` and approved `assets/` formats from the web directory. It copies the three frozen files to `dist/data`, re-verifies the copy, and adds static hosting/build markers. It never traverses the database, coordination directory, owner credentials, run workspaces or arbitrary project files. Symlinks are refused. Replacing a prior output requires the builder's own marker. The build produces a static explorer; hosting, publication and an actual browser-accessible URL remain coordinator tasks.

Implementation references checked 2026-11-11:

https://docs.python.org/3.12/library/json.html

https://docs.python.org/3.12/library/os.html#os.fsync

https://docs.python.org/3.12/library/os.html#os.rename

## Raw occurrence extension

New snapshots record runtime.intake_version as raw-occurrence-v2 while retaining the export-v1 envelope for backward verification. Each lineage entry adds input_format, declared_source, declared_model and raw_record_base64. Offline verification checks the exact decoded bytes/digest, task/patch correspondence and declared values; selected-batch membership reconciliation prevents dropping a repeated attribution. Native and SWE-bench transport can refer to the same computed tuple while preserving separate source records. Old frozen v1 exports without this extension retain their original bytes and verification semantics.

## Task evaluation export (0.1.0a4)

The separate swe-workbench-evaluation-v1 format has exactly evaluation.json, evidence.json and manifest.json. It preserves the frozen task context/material, rubric, quality decision, original raw candidate lineage, named machine observations, computed credit, critical gates, historical task states and audit references. Clean approved tasks enter clean_tasks; challenge or unapproved tasks enter audit_tasks. Failed and unassessed candidates remain in either record. An evaluation export never grants accepted-code membership.

verify_evaluation(path) is read-only. It resolves original material/state/result artifacts, verifies their digests and audit bindings, recomputes criterion credit, rechecks reference/alternate qualification, and requires the exact frozen file set. Repeated exports at an unchanged substantive cut produce the same manifest identity. The static builder matches its displayed quality versions against the verified exported scores and copies only the selected three-file snapshots.

## Real-change handoff (0.1.0a5)

swe-workbench-handoff/v1 is separate from both accepted-code and evaluation datasets. Its exact three-file export contains handoff.json, artifacts.json and manifest.json. It retains before/after regular UTF-8 Git blobs, exact patch and named evidence bytes, observations recomputed from dictionary-key paths, version-bound owner review and selected change history. Only this change's artifacts/events are exported; unrelated private audit content is excluded. The event subset is not a complete global audit-chain proof.

A handoff-ready decision describes review-package readiness. External checks remain unsigned reports and cannot grant native execution success, code acceptance or source-project delivery authority. Missing/different-source required evidence prevents handoff readiness. Changed relevant material resets current review; exact unchanged capture and operation retries are idempotent. The source checkout is read-only and the input byte limit remains8MiB.

## Handoff v2: resolved profiles, typed roles and comparison (0.1.0a6)

New profile/role captures use swe-workbench-handoff/v2 while the v1 reader remains supported. Profile definitions and their exact effective mappings are retained without the profile's local path. Product source is the captured Git candidate; workflow/fixture/artifact identities are evidence-selected subjects. Declared relationships retain both endpoint references and support; unknown/mismatching identities remain unknown. These labels are not signatures or new machine execution.

The v2 envelope adds a comparison recomputed from retained prior/current state and material artifacts. It defaults to the latest earlier reviewed state of the same change, with optional explicit earlier selection. Derived differences and applicability cannot contradict the retained inputs. Old decisions remain historical. Captures of unchanged material do not create a new revision; explicit operation-key retries retain their original idempotent response. Normal key-free capture returns the current material's current review.

The same exact handoff.json/artifacts.json/manifest.json file set and schema1 Store remain in use. Mixed v1/v2 history is exported with a v2 envelope and validates each historical material with its own schema. Original frozen v1 bytes are never rewritten. All handoffs retain zero source-project execution/mutation claims, and native accepted-code semantics remain separate.
