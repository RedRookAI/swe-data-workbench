# Review a change with the results you already have

Configure a project once. Select a change and an existing test report, inspect the source and results, then record your decision and next action. The attention view shows which captured changes need review.

The daily path reads committed Git objects and selected local reports. It creates no new model request and does not run the source project's tests. The separate regression recipe explicitly runs its one admitted check when invoked.

## Start with an existing pytest report

If a run already produced JUnit XML, import that file. If you need to produce one during your normal check run, pytest supports --junit-xml=results.xml. The importer supports the pytest testsuite/testsuites dialect and keeps the exact original XML.

Supply available run context as JSON: schema swe-workbench-run-context/v1, source_revision (full Git ID or null), source_state (clean/dirty/unknown), optional definition_sha256 and inputs (named SHA256 values). Resolve execution context when the check runs. Missing metadata stays unknown; selecting a candidate later cannot manufacture its execution identity.

```sh
swe-workbench import-junit /path/to/results.xml --context /path/to/run-context.json --output /path/to/fresh-import
```

The import directory contains original.xml, report.json and a reusable profile.json. Omit --context when unavailable; the missing source/check definition remains visible. Failed, error, skipped and empty results keep their actual meaning. XML commands, links and paths are data.

## Configure once and prepare a review

Choose an existing base and candidate that identify a nonempty committed change. State and package output belong outside the input repository. The context is explicit local data; no repository configuration is discovered or executed.

```sh
swe-workbench configure-project --repo /path/to/repository \
  --profile /path/to/fresh-import/profile.json --evidence-directory /path/to/fresh-import \
  --state /path/outside/repository/review-state --base-ref main --candidate-ref your-change \
  --output /path/to/project.json

swe-workbench prepare-review /path/to/project.json \
  --change-id change-id --title "Describe the change" --goal "State the requested result" \
  --report /path/to/results.xml --run-context /path/to/run-context.json \
  --output /path/outside/repository/review-package
```

The package contains a view, summary, exact export, review selection and stage receipt. Use the view through your existing trusted private connection. The receipt/imports/selection keep their intended private audience. Omit --run-context when it is unavailable; source/check identity remains unknown. Use --base and --candidate to select explicit refs for later changes. The command reuses the pytest import profile; custom mapping profiles retain their lower-level commands.

prepare-review reads committed Git objects and the selected report. It creates no test/model execution, approval, listener or upload. A later output failure keeps a receipt showing whether capture committed. Resume the same selection explicitly:

```sh
swe-workbench prepare-review /path/to/project.json \
  --output /path/outside/repository/review-package --resume
```

Changed inputs, material or a newer review are refused during an unfinished resume. Completed packages remain frozen selections. No automatic retry or silent review-token refresh occurs.

## Project association and older state

New daily capture binds state to the selected local Git common-directory identity and repository label. Another project cannot reuse it accidentally, even with the same change ID. Context/selection v1 files retain their meanings. Existing legacy state requires explicit association after inspection:

```sh
swe-workbench associate-project /path/to/project.json
```

Mixed labels, unavailable original commits or a different bound project produce a specific refusal. Original source/material/review history is preserved. A same-filesystem directory move preserves Git-directory identity. For a deliberate clone or filesystem relocation, select an updated context and use associate-project with --relocate; it verifies the retained project/commits and records the new local association. This is local ownership context, not publisher authentication. Direct legacy read/export/restore remains supported.

## Lower-level capture and exact observations

The individual commands remain available:

```sh
swe-workbench project-capture /path/to/project.json change-id \
  --title "Describe the change" --goal "State the requested result" \
  --output /path/to/fresh-selection.json
```

Use --preview to inspect effective inputs without runtime writes, or --evidence-directory for another imported report. Ref names resolve to full immutable commit IDs. New daily captures use v4 exact observations and shared source; the earlier --compact flag remains accepted. Explicit legacy v1/v2/v3 capture/verification retains its original semantics.

V4 keeps numeric source tokens in typed observation trees, including0.95000000000000001 and1e-400. Numeric-looking strings remain strings. Existing Python default integer-input guard bounds token length; exponents are never expanded into giant decimal strings. Signed decimal zero and integer/decimal type remain distinguishable. Source spelling changes material identity even when two tokens express the same numeric value. Old floating-point-derived observations retain a visible legacy precision limitation.

Regular/executable UTF8 files are inert source artifacts. Binary, symlink, gitlink and over-budget phases are metadata-only with a reason; no targets are traversed. The patch covers fully captured text paths. Package readiness does not establish full source coverage or code acceptance.

## Inspect, decide and hand off

Use the selected material and report scope to make a decision. A saved selection carries exact review tokens so you do not have to copy a digest manually. It cannot approve a newer material unnoticed.

```sh
swe-workbench review-selection /path/to/project.json /path/to/review-package/selection.json \
  --decision needs-work --reason "Explain what remains unresolved" \
  --finding "Name the specific concern" --next-action "State the next useful action" \
  --responsible-party "Project owner" --reviewer-mode owner_adjudication

swe-workbench attention /path/to/project.json --only-attention
swe-workbench handoff-summary /path/to/project.json change-id
swe-workbench build-project-view /path/to/project.json --output /path/to/fresh-view
```

Use handoff-ready when the package is ready for review. Actual test failures, skipped work and missing source context are shown separately. Native accepted-code gates remain separate. A repeated identical decision is an operation retry; a different stale decision is refused. After recapture, read the original concerns and explicitly reassess them rather than carrying an earlier approval forward.

The summary includes the current source/material/review identity, observed results, unresolved findings and next action. The attention view freezes each selected change independently. Its cards verify against linked package identities before displaying/filtering status, and show purpose, scope, reported failures and missing context. A mismatch or unavailable package stays visible. Malformed report fields do not hide healthy changes; a broken global audit still fails loudly. Config paths are not automatically included in the shareable summary; private prose and evidence keep their intended audience.

build-project-view and build-handoff-view create local files only. Use your existing trusted private serving/connection for private views. Neither command opens a listener or uploads evidence. Public examples use separately authorized hosting. Private backup/restore continues to cover quiescent SQLite state and referenced artifacts.

For a single existing export:

```sh
swe-workbench build-handoff-view /path/to/export --output /path/to/fresh-single-view
```

## What was used here

The recorded daily example contains two actual workbench changes: restoring the private server's verifier-module route and adding the existing-report importer. Their reports retain actual source/check context. One saved project profile served both cases without mapping edits. Reviews are AI-assisted operator judgments. The first package's original needs-work finding and later reassessment remain historical.

The retained private-API regression selects the actual old source and committed repair through the existing admitted runner. Its original source fails and repaired source passes. The check reuses installed dependencies and covers the selected API contract; the actual private browser is checked separately. This is one concrete regression, with no general reliability or model-success claim. See examples/private-ui-regression/README.md and docs/verification.md.
