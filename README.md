# SWE Data Workbench

**Turn coding patches into a reviewed dataset with executable evidence.**

A patch can pass its visible checks and still violate the task. SWE Data Workbench keeps the original input, actual execution results and version-bound judgments together, so an operator can inspect what should enter an accepted dataset.

Open the evidence explorer and silent recorded walkthrough:

https://swe-data-workbench.flyswatterghost.chatgpt.site

The current preview prepares a local repository and processes two genuine historical escape-goat patch revisions. Both fix template-tag conversion; the early revision also changes an existing API contract and is rejected. The revised fix is accepted against actual evidence. An unapproved variant stays pending. The public recording replays the examined decisions with explicit scripted attribution; original assessments are recorded separately.

![Actual upstream-case workbench](docs/images/workbench.png)

Installable wheel and selected evidence:

https://github.com/RedRookAI/swe-data-workbench/releases/tag/v0.1.0a3

## What is implemented

- A local preparation command that reads committed source, explicit checks and selected patches into an inspectable bundle without checking out or executing the repository.
- Bounded native and SWE-bench-compatible JSONL import, exact raw-byte lineage and per-occurrence source/model declarations. Repeated deliveries share execution while retaining their attribution.
- Owner-selected local bundles. Only admitted source/check/patch tuples execute; a model name or imported claim grants no execution permission.
- Separate baseline/candidate workspaces, ordinary Git patch application and executable checks. Output is collected incrementally with a 64 KiB retained prefix per stream; timeouts remain active under continuous output. The original source remains intact.
- Durable SQLite state, recorded launch intent, owned worker groups and generation fences. Committed results survive a fresh-process resume.
- A private owner interface for evidence/rubric-bound review, including stale-revision conflicts and explicit reviewer attribution.
- Deterministic accepted JSONL, a content-addressed manifest and an offline-verifiable evidence snapshot.
- A measured two-stratum pilot with explicit wall/CPU/memory scope and honest missing measurements.

The earlier escape-string-regexp Unicode-hyphen case and original synthetic counterexample remain inspectable with their original evidence:

https://swe-data-workbench.flyswatterghost.chatgpt.site/unicode-hyphen/

https://swe-data-workbench.flyswatterghost.chatgpt.site/synthetic/

## Run the account-free example

Requires Linux, Python3.12, Git and Node at /usr/bin/node. The demonstrated Node version is22.23.4. Keep is not required.

```sh
git clone https://github.com/RedRookAI/swe-data-workbench.git
cd swe-data-workbench
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
mkdir -p .state
git init .state/escape-goat-source
git -C .state/escape-goat-source fetch --depth=1 https://github.com/sindresorhus/escape-goat.git 235683eb791e13336cf4bd9705ea9df97e0d8e51
.venv/bin/python tools/run_prepared_demo.py --repo .state/escape-goat-source
```

This calls the real bundle-preparation command, runs checks, stops after one committed result and resumes in a fresh process. It leaves decisions pending for inspection. The receipt identifies state, bundle, measurements and retained evidence. Preparation never runs the supplied check commands or creates a runtime database. Fetching the source is an explicit separate step.

To use your own supported repository, follow examples/escape-goat/README.md: choose committed source/notice files, exact candidate patches and check argv. The command generates the internal catalog; you inspect its preparation summary and select it with --bundle. No catalog hand-editing is needed.

The original synthetic example remains runnable:

```sh
.venv/bin/python tools/run_demo.py --root .state/synthetic-example
```

The earlier upstream example also remains runnable:

```sh
.venv/bin/python tools/run_real_demo.py --root .state/real-example
```

That older driver explicitly replays its labeled reference decisions. The new prepared example leaves review to the operator. Both native and SWE-bench-compatible imports preserve occurrence attribution; prediction claims never expand execution permission. Neither historical case is advertised as an official SWE-bench instance.

## Private live review

Set a high-entropy `SWE_WORKBENCH_OWNER_TOKEN` in your local environment, then launch:

```sh
.venv/bin/python -m swe_workbench.server --root .state/prepared-example --bundle .state/prepared-example-bundle --port 8097
```

The token must contain at least32 ASCII characters. The server binds to loopback; access its root with `?mode=live` through your own trusted private connection. The owner form keeps the token in browser memory. Public hosting serves only selected frozen data and browser assets.

## Engineering choices and limits

SQLite supplies one transactional authority for this local workload. Content identities bind the exact source, patch, checks, rubric and review. Filesystem publication and database completion reconcile after interruption. These choices keep the demonstration small and make its state inspectable.

Execution currently trusts carefully inspected exact bundles. Retained command-output buffers are bounded while both streams are drained. The commands’ own memory and arbitrary descendants remain outside that guarantee. The demonstrated recipes need no network, installs or generated descendants during checks. Preparation currently supports committed non-executable UTF-8 regular source files from complete local Git objects. Arbitrary public code requires a stronger execution boundary. The pilot covers twelve deliveries across nine unique memberships and makes no production-scale or model-accuracy claim. Review time remains unmeasured.

Product direction and acceptance requirements are owner-led. Implementation, debugging, verification, documentation and demonstration preparation used substantial Codex assistance. The upstream revisions are human-authored; synthetic controls, examined AI-assisted assessments and scripted replays are labeled. This project runs independently from Keep, whose recovery and audit design informed it.

Engineering details: docs/engineering.md. Exact export contract: docs/data-contract.md. Current verification: docs/verification.md. Pilot observations: docs/pilot.md and docs/pilot-report.json. The v0.1.0a1/a2 evidence and releases remain available with their original identities.
