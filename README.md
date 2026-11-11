# SWE Data Workbench

**Turn coding patches into a reviewed dataset with executable evidence.**

A patch can pass its visible checks and still violate the task. SWE Data Workbench keeps the original input, actual execution results and version-bound judgments together, so an operator can inspect what should enter an accepted dataset.

Open the evidence explorer and silent recorded walkthrough:

https://swe-data-workbench.flyswatterghost.chatgpt.site

The current preview processes a real historical JavaScript defect and its human-authored upstream fix. Four input records become three unique patches: the reference fix is accepted, an authored negative control is rejected, and an unapproved variant stays pending. The public view is read-only. Decisions in the recording replay a Codex-assisted code assessment and are labeled scripted adjudication.

![Actual upstream-case workbench](docs/images/workbench.png)

Installable wheel and selected evidence:

https://github.com/RedRookAI/swe-data-workbench/releases/tag/v0.1.0a2

## What is implemented

- Bounded native and SWE-bench-compatible JSONL import, exact raw-byte lineage and per-occurrence source/model declarations. Repeated deliveries share execution while retaining their attribution.
- Owner-selected local bundles. Only admitted source/check/patch tuples execute; a model name or imported claim grants no execution permission.
- Separate baseline/candidate workspaces, ordinary Git patch application and executable checks. The original source remains intact.
- Durable SQLite state, recorded launch intent, owned worker groups and generation fences. Committed results survive a fresh-process resume.
- A private owner interface for evidence/rubric-bound review, including stale-revision conflicts and explicit reviewer attribution.
- Deterministic accepted JSONL, a content-addressed manifest and an offline-verifiable evidence snapshot.
- A measured two-stratum pilot with explicit wall/CPU/memory scope and honest missing measurements.

The real case is escape-string-regexp issue20. Its pinned baseline fails Unicode-hyphen handling; the complete upstream fix passes that check and two preservation checks. The genuine patch, source notice and exact reproduction are included. The original synthetic demonstration separately shows a sorting patch that passes weak tests and is rejected for changing first-seen order.

Original synthetic explorer:

https://swe-data-workbench.flyswatterghost.chatgpt.site/synthetic/

## Run the account-free example

Requires Linux, Python3.12, Git and Node at /usr/bin/node. The demonstrated Node version is22.23.4. Keep is not required.

```sh
git clone https://github.com/RedRookAI/swe-data-workbench.git
cd swe-data-workbench
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python tools/run_real_demo.py --root .state/real-example
```

This runs actual checks, stops a controller after one committed result, resumes in a fresh process, replays the labeled reference assessment against matching evidence, and verifies a repeated export. Its JSON receipt reports observed counts and hashes. Use a fresh owned root for a separate run; existing evidence is retained.

The original synthetic example remains runnable:

```sh
.venv/bin/python tools/run_demo.py --root .state/synthetic-example
```

Import and process without replaying decisions:

```sh
.venv/bin/python -m swe_workbench.cli --root .state/my-review --bundle unicode-hyphen import-approved --operation-key my-import
# Use the returned batch ID:
.venv/bin/python -m swe_workbench.cli --root .state/my-review --bundle unicode-hyphen process BATCH_ID --workers 1
.venv/bin/python -m swe_workbench.cli --root .state/my-review --bundle unicode-hyphen items BATCH_ID
```

For other local prediction files, use `import FILE --format swebench --operation-key KEY`. Unknown patches remain inspectable but cannot execute until the owner admits their exact tuple. The built-in case is a historical upstream example using compatible transport fields; it is not an official SWE-bench instance.

## Private live review

Set a high-entropy `SWE_WORKBENCH_OWNER_TOKEN` in your local environment, then launch:

```sh
.venv/bin/python -m swe_workbench.server --root .state/live-real --bundle unicode-hyphen --port 8097
```

The token must contain at least32 ASCII characters. The server binds to loopback; access its root with `?mode=live` through your own trusted private connection. The owner form keeps the token in browser memory. Public hosting serves only selected frozen data and browser assets.

## Engineering choices and limits

SQLite supplies one transactional authority for this local workload. Content identities bind the exact source, patch, checks, rubric and review. Filesystem publication and database completion reconcile after interruption. These choices keep the demonstration small and make its state inspectable.

Execution currently trusts carefully inspected exact bundles. Output is truncated after capture, so truncation does not bound process memory. The chosen recipe needs no network, installs or generated descendants. Arbitrary public code requires a stronger execution boundary. The pilot covers twelve deliveries across nine unique memberships and makes no production-scale or model-accuracy claim. Review time remains unmeasured.

Product direction and acceptance requirements are owner-led. Implementation, debugging, verification, documentation and demonstration preparation used substantial Codex assistance. The upstream reference patch is human-authored; synthetic controls and replayed decisions are labeled. This project runs independently from Keep, whose recovery and audit design informed it.

Engineering details: docs/engineering.md. Exact export contract: docs/data-contract.md. Current verification: docs/verification.md. Pilot observations: docs/pilot.md and docs/pilot-report.json. The v0.1.0a1 evidence and release remain available with their original identities.
