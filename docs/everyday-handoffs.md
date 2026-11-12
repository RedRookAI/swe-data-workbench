# Reuse a project profile and review only what changed

A profile saves a project's evidence slot names, dictionary-key mappings, required scope and revision-role declarations. Select the profile explicitly, supply the change's requested goal and exact commits, and bind a directory containing the declared evidence names. The workbench reads only those names; it does not scan for extra files or execute the profile.

```sh
.venv/bin/python -m swe_workbench.cli --root .state/review capture-handoff \
  --repo /path/to/local/input-repository \
  --base FULL_BASE_COMMIT --candidate FULL_CANDIDATE_COMMIT \
  --profile /path/to/project-profile.json --evidence-dir /path/to/selected/evidence \
  --change-id change-identifier --title "Describe the change" \
  --goal "State the requested result"
```

examples/keep-handoff/profile.json is a complete public example. Its matching source revisions and input-acquisition instructions remain in that example directory. It replaces repeated field-map editing and individual evidence-path arguments. A profile can also use explicit NAME=FILE bindings. Missing files, symlink slots and invalid profile definitions produce a specific refusal before capture state changes. Missing report fields remain unknown observations. Profile files and their evidence directories remain source inputs; the state directory must be separate.

The expanded effective request and profile identity are retained. Relocating an unchanged profile does not alter material. Changing its effective mappings changes the captured version and requires applicable review. Normal repeated capture returns the current review state without inventing another source change. Explicit operation-key retries retain their original response for compatibility.

Review remains deliberate and bound to the material digest/revision printed by capture. Supply a review JSON or inline decision, reason, findings, next action and responsible-party label. These labels are operator declarations, not authenticated identities. An absent responsible party displays Unassigned. Handoff readiness describes the package, not code acceptance or delivery permission.

The overview leads with the requested change, external evidence scope, unresolved findings, responsible party and next action. Versions, hashes, diff, raw observations and historical inputs remain expandable. Historical material is loaded from the selected fixed artifact file and checked against its content hash before display.

## Revision roles

The v2 format distinguishes captured product source, qualification workflow, consumer fixture and released artifact. Non-product subjects use explicit selectors into retained evidence. A relationship references the identities of both endpoints and supporting retained fields or quoted text. Missing identities or mismatching support stay unknown. The reader can distinguish a report's declared relationship from independently witnessed execution.

A fixture hash cannot replace the captured product identity. A reported archive hash can be known while its relationship to the candidate remains unknown. Different version labels alone do not establish whether an archive includes a correction. Evidence and source-project effects remain separate; capture performs neither tests nor delivery.

Old v1 requests, operation retries and immutable three-file exports retain their meanings. New role-bearing captures use v2 material/envelopes, with schema dispatch and mixed-version history support. Schema1 SQLite artifacts/audit are reused; no new database or migration is required.

## Previous versus current

The default comparison uses the latest earlier reviewed state of this change. An explicit earlier reviewed revision can be selected with --baseline-revision on handoff or export-handoff. A first capture displays no prior reviewed baseline; another change cannot silently supply one.

The comparison shows changed source/goal context, files, evidence, role relationships, findings, decision, attribution and next action. False, zero and missing values remain distinct. Unchanged reported bindings are labeled as such; changed or insufficient context requires review or stays unknown. It never infers semantic coverage from unchanged lines, reruns the source project or carries an old approval forward.

## What was actually tried

The public example adds a reusable profile and explicit roles to the earlier actual Keep change, retaining its original reviewed state. Source and requested goal stay unchanged while the provenance explanation becomes structured. No new Keep generation, test, branch, release or service change occurred.

A second, private application change and retained replay report also used the generic profile flow. The actual report omitted the execution revision, so its positive observations remained unbound and the review stayed needs-work. The same profile was reused without copied mapping edits. Private source, report, mappings and project identifiers remain private.

This demonstrates profile reuse, portable state and clearer scope across two projects. It does not establish human time savings. Per-project profile setup, change-specific goals and review decisions still require work. The workflow remains optional; an ordinary Git/report handoff remains a valid simpler choice.
