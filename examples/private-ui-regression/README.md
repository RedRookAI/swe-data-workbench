# The imported module that the private server did not serve

The actual0.1.0a7 private app imported handoff-verify.js while its API returned404 for that asset. The original application source is commit5d5e70cc1c00e28b31c11112ad8e9c148222b52a. The repair is commit2e7f1d4563cb9a70d77a60e5cc3323774b692d94.

fix.patch contains the selected API-file diff from that actual repair. checks.json and verifier.json define one explicit protected check: index/app/verifier delivery, refusal of a database path and owner-only API access. The original selected source failed; the repaired source passed. This is actual workbench code, with owner direction and substantial Codex assistance. No new model-generation run is represented by the transport label in candidates.json.

Use the existing prepare-bundle command with this local repository, the pinned base, --source swe_workbench/api.py, --notice LICENSE, the task/check/candidate/provenance files here, --verifier-files verifier.json and a fresh output directory outside the repository. Then import-approved/process that inspected bundle through the ordinary owner CLI. Preparation reads Git objects only; process explicitly runs the admitted check. Read docs/reliable-handoffs.md and CLI help for the generic operations.

The check loads the selected API module and reuses installed workbench/FastAPI dependencies and web assets; its output records the dependency package version. The retained measurement used installed0.1.0a7 dependencies. The case covers the selected module/access contract and does not reconstruct a complete independent application environment. Full current private-browser startup is qualified separately. Runtime evidence and exact digests are recorded in docs/verification.json.
