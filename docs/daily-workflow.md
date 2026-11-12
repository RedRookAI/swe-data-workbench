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

## Configure once and capture

Choose explicit local paths and existing Git refs. State must be outside the input repository. The context is owner-selected data; the command does not discover or execute repository configuration.

```sh
swe-workbench configure-project --repo /path/to/repository \
  --profile /path/to/fresh-import/profile.json --evidence-directory /path/to/fresh-import \
  --state /path/outside/repository/review-state --base-ref main --candidate-ref HEAD \
  --output /path/to/project.json

swe-workbench project-capture /path/to/project.json change-id \
  --title "Describe the change" --goal "State the requested result" \
  --compact --output /path/to/fresh-selection.json
```

Use --preview to inspect effective inputs without runtime state writes. Use --base/--candidate to select different existing refs and --evidence-directory for a later imported report. Ref names are conveniences: the captured record retains their resolved full commit IDs. --compact selects v3 source sharing and explicit file coverage. Original v1/v2 capture remains supported.

A v3 text file is retained as an exact source artifact, including executable-file mode. Reading an executable file does not run it. Binary, symlink, gitlink and over-budget content is metadata-only with a reason; targets are never traversed. The displayed patch covers fully captured text paths, and omitted paths remain listed. Package readiness does not establish full source coverage or code acceptance.

## Inspect, decide and hand off

Use the selected material and report scope to make a decision. A saved selection carries exact review tokens so you do not have to copy a digest manually. It cannot approve a newer material unnoticed.

```sh
swe-workbench review-selection /path/to/project.json /path/to/fresh-selection.json \
  --decision needs-work --reason "Explain what remains unresolved" \
  --finding "Name the specific concern" --next-action "State the next useful action" \
  --responsible-party "Project owner" --reviewer-mode owner_adjudication

swe-workbench attention /path/to/project.json --only-attention
swe-workbench handoff-summary /path/to/project.json change-id
swe-workbench build-project-view /path/to/project.json --output /path/to/fresh-view
```

Use handoff-ready when the package is ready for review. Actual test failures, skipped work and missing source context are shown separately. Native accepted-code gates remain separate. A repeated identical decision is an operation retry; a different stale decision is refused. After recapture, read the original concerns and explicitly reassess them rather than carrying an earlier approval forward.

The summary includes the current source/material/review identity, observed results, unresolved findings and next action. The attention view freezes each selected change independently and links to a checked read-only view. Config paths are not automatically included in the shareable summary; private prose and evidence keep their intended audience.

build-project-view and build-handoff-view create local files only. Use your existing trusted private serving/connection for private views. Neither command opens a listener or uploads evidence. Public examples use separately authorized hosting. Private backup/restore continues to cover quiescent SQLite state and referenced artifacts.

For a single existing export:

```sh
swe-workbench build-handoff-view /path/to/export --output /path/to/fresh-single-view
```

## What was used here

The recorded daily example contains two actual workbench changes: restoring the private server's verifier-module route and adding the existing-report importer. Their reports retain actual source/check context. One saved project profile served both cases without mapping edits. Reviews are AI-assisted operator judgments. The first package's original needs-work finding and later reassessment remain historical.

The retained private-API regression selects the actual old source and committed repair through the existing admitted runner. Its original source fails and repaired source passes. The check reuses installed dependencies and covers the selected API contract; the actual private browser is checked separately. This is one concrete regression, with no general reliability or model-success claim. See examples/private-ui-regression/README.md and docs/verification.md.
