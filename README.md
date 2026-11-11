# SWE Data Workbench

**Process coding submissions into reviewed datasets with traceable evidence.**

A coding patch can pass its visible checks and still violate the task. SWE Data Workbench keeps execution evidence and rubric judgments together, so an operator can inspect that distinction before a submission enters an accepted dataset.

Open the recorded evidence explorer:

https://swe-data-workbench.flyswatterghost.chatgpt.site

The public view is read-only. It includes synthetic tasks, actual executable-check results, scripted developer adjudications and downloadable evidence. The walkthrough records the real application. It makes no model requests.

## What you can inspect

- Eight input lines become six unique submissions, one duplicate occurrence and one invalid record.
- Four trusted candidates run in disposable workspaces. Two incomplete or unsupported submissions remain pending.
- A sorting patch passes the deliberately weak ascending-input checks but changes first-seen order. Its semantic defect is explained during adjudication.
- A correct patch is accepted against exact evidence and rubric versions.
- A controller can stop and a fresh process can recover committed progress. Separate focused checks cover an actual killed controller.
- Export produces deterministic accepted JSONL, its manifest and a frozen evidence snapshot.

Synthetic seeded reviewers illustrate disagreement. They are not independent human assessments. Demonstration adjudications are scripted through the real controls and labeled in the run notes.

## Run the account-free example

Requires Linux, Python 3.12 and Git. The processing core uses standard-library SQLite. Keep is not required.

```sh
git clone https://github.com/RedRookAI/swe-data-workbench.git
cd swe-data-workbench
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python tools/run_demo.py --root .state/documented-example
```

The command imports the sample, runs a controller that stops after one committed result, resumes in a fresh process, records scripted exact-evidence decisions and verifies a repeated export. Its JSON receipt identifies observed counts and artifact hashes. It preserves existing state rather than resetting a workspace.

Inspect the commands separately:

```sh
.venv/bin/python -m swe_workbench.cli --help
.venv/bin/python -m swe_workbench.cli --root .state/documented-example verify
```

The package also includes its fixture catalog and browser assets for an installed-wheel workflow.

## Private live review

The owner API and browser interface run separately from the public static explorer. Supply a high-entropy owner token through the local environment, then launch:

```sh
.venv/bin/python -m swe_workbench.server --root .state/live --port 8097
```

The server requires `SWE_WORKBENCH_OWNER_TOKEN` with at least 32 ASCII characters and binds to loopback. Open its root path with `?mode=live` through your own trusted private connection. Enter the token in the owner form; it stays in browser memory and travels in an Authorization header. Mutation requests must have the exact same Origin. Do not expose this execution API publicly.

## Engineering choices

SQLite is the sole authority for records, attempts, reviews and hash-linked audit events. State changes and audit append share one short transaction. Actual checks run outside that transaction, with recorded intent and bounded workers. Recovery uses process identity and attempt generation; elapsed time alone cannot establish that an old worker stopped.

A review binds an exact submission, evidence digest and rubric. Missing required evidence cannot become an accepted result. Export freezes one consistent cut and reconciles filesystem publication with database ready state.

The public site contains selected static artifacts and has no execution or upload endpoint. Imported text is rendered as text. Trusted manifest-listed fixtures are the supported execution profile; this is not an arbitrary-code sandbox.

See the engineering decisions, export contract, metrics definitions and measured verification in `docs/`. The fixture catalog explains deliberately weak checks and known counterexamples.

## Scope and attribution

Version 0.1.0a1 is a standalone portfolio preview. The small curated corpus demonstrates workflow behavior; it does not establish model accuracy, independent reviewer reliability, production throughput or production readiness.

Keep informed the durable execution and audit design. This application runs independently and does not import or copy Keep's runtime.

Product direction and acceptance requirements are owner-led. Implementation, debugging, checks, documentation and recording preparation use substantial Codex assistance. Original application and authored fixtures use the MIT license; dependencies retain their own licenses.

