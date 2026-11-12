# SWE Data Workbench

**Review software changes and coding tasks with evidence you can hand off.**

SWE Data Workbench captures committed changes, keeps evidence and review decisions tied to exact versions, and exports a package another reviewer can inspect. Its coding-task workflow also executes admitted patches, records grader findings and freezes evaluation datasets.

Explore the recorded change reviews and earlier silent walkthrough:

https://swe-data-workbench.flyswatterghost.chatgpt.site

The current view shows two actual workbench changes and a clearly labeled authored example with a failed report and unknown run context. The actual changes are: a repaired private-server module route and an importer for existing test reports. Open either change to inspect its committed source, reported checks, exact evidence and review history. Reviews are AI-assisted operator judgments.

Configure a project once, then use prepare-review to turn an existing pytest/JUnit report and selected change into a review view, summary and saved decision selection. No field-map editing is needed for the supported pytest profile. The overview checks each card against its linked package before showing its status. Project associations keep local state separate, and v4 observations preserve numeric source text through Python capture and browser display. Shared source artifacts retain history with explicit metadata-only coverage. Setup and commands are in docs/daily-workflow.md.

The earlier task-quality example remains linked from the current view: a weak recovery checker gives buggy code100/100; the repaired checker gives it50/100 and a failed critical gate. Both valid repairs and the recorded Codex candidate pass.

![Actual workbench evidence view](docs/images/workbench.png)

Installable wheel, two daily-change exports, regression recipe and verification:

https://github.com/RedRookAI/swe-data-workbench/releases/tag/v0.1.0a10

## Try a complete handoff

Import an existing report, select your project context, capture a change and inspect it in a standalone view. Record an explicit review, export the evidence and restore your saved work. The small synthetic example runs one fixed Python check and needs no account or model call. Follow docs/reliable-handoffs.md for the installed-package commands.

## Reuse a project profile

Select a saved profile, exact source commits, the requested goal and the existing evidence directory. Capture reads the committed files and only the profile-declared evidence names. Normal repeated capture retains the latest review state. It performs no source-project execution or delivery.

The generic command and version-bound review/export flow are documented in docs/everyday-handoffs.md. A complete public profile is in examples/keep-handoff/profile.json. Existing explicit-request capture remains supported.

## Keep actual CI results with the change

The GitHub workflow now records its selected pytest invocation once, retains the original XML and observed source/run context, and prepares a downloadable review. Failed tests keep their failed CI status. A package starts unreviewed.

The same fixed recipe can inspect a pinned historical itsdangerous change. Its original signer tests run against the selected source; upstream authorship and the BSD notice stay with the export. The intentional failure option is a separate, clearly labeled artifact-delivery check.

See docs/ci-review.md for the commands, base-selection policy, artifact contents and limits. CI downloads require GitHub sign-in and follow repository retention. The selected browser view needs HTTP serving; the public preview supplies that for audited examples.

## Review the original real-change example

Requires Linux, Python3.12 and Git. Install requirements.lock in a project-local virtual environment. Select a local repository containing the example commits, then run:

```sh
.venv/bin/python tools/run_handoff_trial.py --repo /path/to/your/local/keep-repository --root .state/change-handoff
```

The input repository is read-only: no checkout, reset, installation or project execution. The command captures committed before/after files and selected evidence, explicitly replays the recorded assessment, exports the handoff and verifies it in a fresh process. Full source-object acquisition instructions and generic capture/review/export commands are in examples/keep-handoff/README.md. Keep is an example source, not a runtime dependency.

This is an optional portable handoff. Its original explicit request path uses operator-supplied mappings; the new daily path reuses a project profile. The trial demonstrates comprehension and preserved identities; human time savings and broad daily adoption remain unmeasured.

## Run the coding-task example

Requires Linux, Python 3.12 and Git. The new ingestion example uses the Python standard library for its checks and makes no network or model calls.

```sh
git clone https://github.com/RedRookAI/swe-data-workbench.git
cd swe-data-workbench
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python tools/run_quality_demo.py --root .state/quality-example
```

The driver reconstructs the original committed source, calls the real preparation command and runs weak-v1 and fixed-v3 against identical candidate bytes. It explicitly replays the recorded assessments after checking actual outcomes, freezes both datasets and verifies them offline. The receipt names the bundles, state and exports. Choose a fresh output root for another run; existing evidence is preserved.

For private live inspection, set a high-entropy `SWE_WORKBENCH_OWNER_TOKEN` in your local environment and start:

```sh
.venv/bin/python -m swe_workbench.server --root .state/quality-example/workbench --bundle .state/quality-example/bundle-fixed-v3 --port 8097
```

Use the server through your own trusted private connection with `?mode=live`. The token requires at least 32 ASCII characters and stays in browser memory. The public site serves frozen evidence only.

## What is implemented

- Preview selected profile mappings without creating runtime state; write reusable source-bound check receipts and back up/restore quiescent review state.
- Reuse a project profile, inspect typed revision roles and compare current/prior reviews with unknown evidence applicability left explicit.
- Capture a real committed change and selected external evidence without executing its project. Preserve version-bound review history and export an offline-verifiable handoff.
- Read committed source and selected patches into an inspectable task bundle without checkout or execution during preparation.
- Import native or SWE-bench-style JSONL with exact raw bytes, per-occurrence attribution and duplicate accounting. Imported claims do not grant execution permission.
- Run baseline and candidate checks in separate workspaces with ordinary Git patch application, bounded retained output and active deadlines. Preserve the original source.
- Keep protected verifier files outside candidate patches and check their integrity before and after each phase. This is local role separation within a trusted execution profile.
- Record task-quality findings, repair requests, reviewer involvement and feedback against exact material versions. Reject stale review revisions.
- Compute task-specific integer credit from actual named checks and show the critical gate separately. Missing evidence stays unassessed.
- Approve a clean task only with passing reference and alternate implementations and no unresolved high or critical findings.
- Export every candidate outcome for an evaluation task, including failures and pending evidence. The existing accepted-code JSONL remains a separate output requiring explicit code acceptance.
- Recover committed results through SQLite state, recorded launch intent, owned worker groups and generation fences.

## What the demonstration establishes

The ingestion service can commit a total before its replay receipt. The original checker restarts after normal completion and misses that defect. The repaired checker interrupts after a durable event, inspects state before replay and checks for loss or double-counting. It also exercises callback exceptions, a later event, parsing boundaries, the CLI and compatibility with a successfully saved original state.

Credit is 25 ordinary, 25 identity and 50 recovery. Passing those checks measures that recipe. Signed64 aggregate overflow remains a visible, unmeasured coverage limitation; the task retains the requirement. This small authored corpus supports a task-audit example, not a model success-rate estimate. The account-free recording replays actual recorded judgments through working controls with explicit scripted attribution.

Original source and controls are MIT-licensed. One separate Codex task produced the recorded candidate from the supplied goal and starter files. Its receipt records actual visibility; the shared account was not an OS sandbox. Both calibration reviewers were AI-assisted, and one authored that candidate. Their agreement is recorded without claiming independent human validation.

## Earlier working examples

The prepared escape-goat case examines two genuine historical human patch revisions, rejecting the first for changing an existing API contract. It remains available with its original evidence:

https://swe-data-workbench.flyswatterghost.chatgpt.site/evaluation-demo/prepared/

The Unicode-hyphen and original synthetic cases are also preserved:

https://swe-data-workbench.flyswatterghost.chatgpt.site/evaluation-demo/unicode-hyphen/

https://swe-data-workbench.flyswatterghost.chatgpt.site/evaluation-demo/synthetic/

Their runnable drivers and source-fetch instructions remain in examples/escape-goat/README.md and bundles/unicode-hyphen/README.md. These historical Node checks require /usr/bin/node. Old releases and receipts keep their original identities.

## Design choices and current limits

SQLite provides one local transactional authority. Content-addressed artifacts retain the material behind each task, result and decision. Task-quality states reuse the existing audit and artifact store without a database schema migration. Separate evaluation and accepted-code exports serve different dataset uses.

Execution admits inspected exact source/check/patch tuples. Verifier integrity checks do not isolate arbitrary hostile same-user code. Check commands' total memory and arbitrary descendants are outside the bounded-output guarantee. Stronger isolation and the planned migration/concurrency task families remain follow-up work. The earlier throughput pilot is historical workload evidence; it was not rerun or presented as a scale claim.

Product direction and acceptance requirements are owner-led. Implementation, debugging, verification, documentation and demonstration preparation used substantial Codex assistance. Keep supplied prior art for recovery and auditable decisions; this application runs independently.

Details: docs/daily-workflow.md, docs/everyday-handoffs.md, docs/change-handoff.md, examples/keep-handoff/README.md, examples/ingest-recovery/README.md, docs/task-quality.md, docs/engineering.md and docs/data-contract.md. Exact verification is in docs/verification.md. Prior releases retain their original verification files.
