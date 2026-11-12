# Review a change from setup to a reviewed handoff

Use the results you already have. This guide takes you through one project setup, a frozen first package, an explicit decision and a fresh export containing that decision. A second real change reuses the same setup.

The example reads two historical workbench changes and their original reports: a private UI route repair with one passing check, then the JUnit importer with three. It runs neither project's checks nor a model. New demonstration decisions are explicitly scripted; original evidence and original review histories stay in the downloaded inputs.

Inspect the original examples in your browser:

https://swe-data-workbench.flyswatterghost.chatgpt.site/change-b39b3e0c4fb83f37c2b2/

https://swe-data-workbench.flyswatterghost.chatgpt.site/change-833fc94c43fa30e26989/

## 1. Install and acquire explicit inputs

Requires Linux, Python3.12 and Git. Start from a checkout of this repository. Choose a fresh output root outside the checkout. Commands below use Bash arrays to preserve argument boundaries.

```sh
WORKBENCH_SOURCE="$PWD"
RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/workbench-review.XXXXXXXX")"
python3 -m venv "$RUN_ROOT/venv"
PYTHON="$RUN_ROOT/venv/bin/python"
"$PYTHON" -m pip install 'https://github.com/RedRookAI/swe-data-workbench/releases/download/v0.1.0a12/swe_data_workbench-0.1.0a12-py3-none-any.whl'
WB=("$PYTHON" -I -m swe_workbench.cli)

"$PYTHON" -I "$WORKBENCH_SOURCE/tools/prepare_daily_example.py" --output "$RUN_ROOT/inputs"
```

An existing isolated installation of this version can supply PYTHON instead of creating another environment. The small acquisition helper downloads two fixed public handoffs, verifies them, preserves the exact XML/context and common profile, then clones source objects into a fresh directory without checking out or executing the projects. It refuses an existing destination. A failed acquisition leaves named partial inputs for inspection; choose a new root rather than reset an old workspace.

This one-time network acquisition occurs before capture. The remaining review commands read committed Git objects and local evidence. Source files, original exports and original execution identities stay unchanged.

## 2. Configure once, then prepare the first change

```sh
INPUTS="$RUN_ROOT/inputs"
PROJECT="$RUN_ROOT/project.json"
STATE="$RUN_ROOT/state"
FIRST="$RUN_ROOT/startup-package"

"${WB[@]}" configure-project --repo "$INPUTS/source" \
  --profile "$INPUTS/profile.json" --evidence-directory "$INPUTS/startup" \
  --state "$STATE" \
  --base-ref 5d5e70cc1c00e28b31c11112ad8e9c148222b52a \
  --candidate-ref 2e7f1d4563cb9a70d77a60e5cc3323774b692d94 \
  --output "$PROJECT"

"${WB[@]}" prepare-review "$PROJECT" --change-id startup \
  --title 'Restore private UI startup' --goal 'Restore delivery of the verifier module to the private UI' \
  --report "$INPUTS/startup/original.xml" --run-context "$INPUTS/startup/run-context.json" \
  --output "$FIRST"

"${WB[@]}" verify-handoff "$FIRST/export"
"${WB[@]}" handoff-summary "$PROJECT" startup
```

Expected: the export verifies; the summary reports one passed check bound to candidate2e7f1d4, and the package decision is unreviewed. Check the goal, source diff, actual report scope, unknowns and next action. Passing that historical route check does not establish complete browser behavior.

The package contains private receipt/imports/selection files and a selected export/view/summary. Use the public original above for browser inspection without installation. To inspect newly generated private view/ on a headless server, serve only that selection through your existing trusted HTTP connection. The commands create no listener or upload. A local path, file:// page or localhost address is not a remote browser preview.

## 3. Record a deliberate decision and export it afresh

For this worked example, record the following explicitly scripted concern. For your own work, use your actual findings, reason, responsible party and reviewer mode.

```sh
"${WB[@]}" review-selection "$PROJECT" "$FIRST/selection.json" \
  --decision needs-work --reason 'Scripted example: the original route check has limited scope' \
  --finding 'The route report does not establish complete private browser behavior' \
  --next-action 'Inspect browser behavior separately before calling the package complete' \
  --responsible-party 'Project owner' --reviewer-mode scripted_adjudication

"${WB[@]}" --root "$STATE" export-handoff startup --output "$RUN_ROOT/startup-reviewed-export"
"${WB[@]}" verify-handoff "$RUN_ROOT/startup-reviewed-export"
"${WB[@]}" build-handoff-view "$RUN_ROOT/startup-reviewed-export" --output "$RUN_ROOT/startup-reviewed-view"
"${WB[@]}" handoff-summary "$PROJECT" startup
```

Expected: the new export/view and current summary contain needs-work and the named concern at review revision1. The original FIRST/export and FIRST/view remain unreviewed at revision0. They are frozen selections. Completed prepare-review --resume returns that same original package; it does not refresh it after a later decision.

Share the fresh reviewed export/view when you want the decision included. Select only evidence suited to its audience. State, context, private receipts, saved selections and backups stay private. A handoff-ready decision means package readiness; it grants no execution, merge or native code-acceptance authority.

## 4. Reuse the setup for the second change

The common profile and project state stay in place. Only change ID, requested result, existing report/context, selected commits and fresh destination change. Both examples use ordinary pytest evidence; switching to the optional CI profile is a separate explicit setup choice.

```sh
SECOND="$RUN_ROOT/importer-package"
"${WB[@]}" prepare-review "$PROJECT" --change-id importer \
  --title 'Read existing pytest results' --goal 'Import original pytest outcomes without executing report instructions' \
  --base 2e7f1d4563cb9a70d77a60e5cc3323774b692d94 \
  --candidate 217064e5637e4fa493af23cef3dc2f95c9d19a7c \
  --report "$INPUTS/importer/original.xml" --run-context "$INPUTS/importer/run-context.json" \
  --output "$SECOND"
"${WB[@]}" verify-handoff "$SECOND/export"
"${WB[@]}" handoff-summary "$PROJECT" importer

"${WB[@]}" review-selection "$PROJECT" "$SECOND/selection.json" \
  --decision handoff-ready --reason 'Scripted example: inspectable source and original scoped report are retained' \
  --next-action 'Review the retained importer source and its three original checks' \
  --responsible-party 'Project owner' --reviewer-mode scripted_adjudication
"${WB[@]}" --root "$STATE" export-handoff importer --output "$RUN_ROOT/importer-reviewed-export"
"${WB[@]}" verify-handoff "$RUN_ROOT/importer-reviewed-export"
"${WB[@]}" build-handoff-view "$RUN_ROOT/importer-reviewed-export" --output "$RUN_ROOT/importer-reviewed-view"
"${WB[@]}" handoff-summary "$PROJECT" importer
"${WB[@]}" attention "$PROJECT"
```

Expected: three original passed checks remain bound to candidate217064e. The fresh importer export is handoff-ready at revision1; its original package stays unreviewed. Attention still includes startup's concern. New scripted decisions do not replace the original downloaded review histories.

## Use your own report or CI evidence

Import an existing pytest testsuite/testsuites XML file into a fresh directory with import-junit, then configure with its generated profile. Supply --context when real execution context is available. A report-only null context stays unbound rather than borrowing the later selected candidate identity. Producing JUnit during your normal test invocation needs no extra test run.

For observed CI evidence, add --ci-receipt and --check-definition to both import-junit and prepare-review alongside the original report and run context. The new CI profile automatically uses the validated tested product label; workflow repository identity remains separate. Existing profiles/context files are never rewritten. See ci-review.md for the complete observation and optional-attachment contract. A mismatched old profile needs explicit setup with a new generated profile/context, preserving its old files and state association.

## Resume and inspect problems

If assembly fails after capture, receipt.json records whether capture committed. After resolving the named output problem, explicitly resume the same selected package:

```sh
"${WB[@]}" prepare-review "$PROJECT" --output "$FIRST" --resume
```

Changed inputs/profile/context or a newer review during an unfinished assembly are refused. Use an explicit fresh selection for intentional newer work. An existing export/view destination is preserved; choose a new destination. A stale review-selection cannot approve changed material. Do not delete state or reset a source workspace to retry.

Malformed supported reports are visibly invalid, including CI evidence missing required run context. A project view keeps a named problem entry instead of offering an invalid-report leaf, while healthy records stay inspectable. Global audit corruption still fails the operation loudly. verify-handoff performs Python semantic checks; browser verification checks content consistency against its selected unsigned manifest and has a narrower guarantee. Neither authenticates the external producer.

## Reference and evidence

Project association, explicit legacy relocation, exact v4 observations and lower-level capture retain their existing contracts. New daily captures use v4; v1/v2/v3 remain readable with their original semantics. Use associate-project for deliberately selected legacy state and --relocate only for an intentional source move with retained commit availability. Other projects cannot silently reuse a bound state.

See everyday-handoffs.md for profiles/roles and explicit capture, reliable-handoffs.md for backup/restore and installation checks, and ci-review.md for actual CI artifacts. Old frozen packages and release bytes remain historical. The scoped two-change operator conclusion is in operator-trial.md; assistance and original check execution are distinguished there. Independent human productivity and adoption remain unmeasured.
