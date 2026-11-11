# Verification profile: 0.1.0a1

Checked 2026-11-11 on Linux x64, Python 3.12.3, SQLite 3.45.1 and Git 2.43.0. Exact artifact identities and structured observations are in verification.json and examples/synthetic-run/recording.json.

## Checks actually executed

| Profile | Observed result | What it establishes |
|---|---|---|
| Intake/core/runner/recovery | 19 focused cases passed across their scoped runs | Raw lineage and bounds, transaction rollback, exact evidence/rubric binding, real Git/check execution, ownership, actual killed-controller recovery and content/generation fencing |
| Export | 11 focused cases passed | Stable same-cut bytes, artifact/audit verification, interruption around filesystem publication, correct denominators and safe public-file selection |
| API transport and real-core integration | 14 cases passed | Owner authorization, exact origin, schema/error boundaries and actual process/review/export integration |
| Browser security/accessibility fixtures | 3 Chromium cases passed | Inert imported text, keyboard tabs, small-screen layout, exact review payload and paused/muted playback |
| Documented command-line example | Passed on the current context-bound intake implementation | A real controller stopped after one result; fresh-process continuation retained that evidence and processed the remaining three candidates |
| Installed release wheel | Passed outside the source checkout, with isolated Python imports | Installed modules/browser assets matched checkout bytes; bundled fixtures executed one actual candidate; database integrity passed; Keep was absent |
| Actual owner-browser recording | Completed with zero browser errors | Real intake, cooperative stop/resume, scripted semantic adjudication and exact export |
| Public static browser view | Passed with the real frozen snapshot | Six items rendered, owner controls hidden, zero API/external requests, no browser errors, mobile layout without horizontal overflow, paused/muted low-volume player and local captions |

The component cases were run by separate Codex instances during implementation. These results are not presented as one full-suite execution on the final documentation commit. Relevant checks were repeated after actual changes or a concrete failure.

## One integration defect corrected

A changed current rubric initially left historical accepted decisions counted as current. Current read projections now invalidate only affected task/source/check/rubric/allowlist contexts while preserving historical results, decisions, revisions and audit evidence. Intake identity binds raw bytes plus effective context; reusing an old key under changed context conflicts, and a new key creates the appropriate context batch.

A focused regression exercised rubric, source and check changes, preserved an old frozen export and verified current counts, eligibility and reimport. The browser identifies historical decisions and prevents a stale-context review form from implying current authority.

## Recorded result

The public example contains eight authored input lines: six unique submissions, one duplicate and one invalid record. Four trusted candidates were measured. Two were accepted and two rejected through scripted developer adjudications; two remain pending for missing or unsupported evidence. The deliberately wrong sorting patch actually passed its weak visible checks before semantic rejection.

The visible interruption is a controlled cooperative stop after one committed result. A separate focused recovery case killed an actual controller and verified owned-worker cleanup, retained results and restart. The recording does not pretend that its cooperative stop is that crash test.

Recording decisions were scripted by tools/record_demo.py through the actual owner browser controls. No model request was made by the application. Development itself used Codex assistance.

## Reproduce proportionally

Install requirements-dev.lock for focused test tools. Core/export checks use Python unittest; API/browser checks use pytest. Select the files relevant to a change. The README's ordinary example exercises the complete account-free path.

The demonstration does not establish arbitrary-code containment, multi-tenant production readiness, independent review quality, a model accuracy estimate or a general throughput benchmark. Review time and incomparable seeded-label agreement remain unavailable rather than invented.

A Starlette warning deprecates the development httpx testclient path; the checks passed. Runtime behavior is not dependent on that testclient. The recording driver uses locator assertions compatible with the application's strict Content Security Policy; the policy was preserved.

