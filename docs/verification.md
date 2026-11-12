# Verification: 0.1.0a13

Checked 2026-11-12 against ade4eeee6b1a8998522b173e7937c9074488eb4f. This checkpoint closes the final audit’s CI and presentation findings.

Normal CI now includes the existing core acceptance, runner, controller-kill recovery, bounded output capture, verifier-integrity and evaluation suites. It also executes the documented account-free example and verifies its expected checker comparison, export integrity and pending acceptance. Changes to tools, examples, fixtures and bundles now trigger the workflow. The existing intentional-failure and external-case recipes retain their distinct roles.

The review queue and inspector use the comparison table’s candidate names, matched by exact patch digest. Generic and live views retain their original title fallback. The recorded example explains why passing checks leave candidate acceptance pending and the accepted-code export empty; evaluation downloads still retain every outcome. No review decision or historical result changed.

Focused local qualification: 39 tests and 16 subtests passed. This includes the real controller interruption/recovery checks and the complete account-free driver; no model calls were made. All 87 selected evidence/media files remain byte-identical. The original 0.1.0a12 verification is preserved in verification-v0.1.0a12.md/json. Earlier compatibility, provenance and preview limits still apply.

Actual source CI, public release downloads and deployed-preview observations follow in the final publication receipt.

The first expanded CI run (43259673888, source db44aa490896b5a455eb69dc5a2a116c86ef316d) reported 55 passed and one failed Unicode integration test: its pinned /usr/bin/node runtime was absent from the hosted runner. The job now provisions nodejs explicitly, and the test gives an explicit prerequisite failure. The original failed run and its uploaded evidence remain available. No fixture/check identity was rewritten.

## Final publication

Release v0.1.0a13 targets 8173ec86a1078681c8fae01d33946fc17ba908bc. Corrected CI run 43260190189 passed 56 tests and 16 subtests, followed by installed compatibility and authored daily-workflow qualification. One existing FastAPI TestClient/httpx deprecation warning remains; it did not fail qualification.

https://github.com/RedRookAI/swe-data-workbench/actions/runs/43260190189

The five release assets were downloaded and matched original bytes, provider sizes and SHA256 digests. An anonymous wheel request returned HTTP 200 with the same digest. Its source/asset parity check matched 40 packaged Python and web files. SHA256SUMS is included in the release.

https://github.com/RedRookAI/swe-data-workbench/releases/tag/v0.1.0a13

The existing public Site deployed saved version 12 from db44aa490896b5a455eb69dc5a2a116c86ef316d. The subsequent CI correction changes only workflow, test diagnostics and verification docs; deployed application/assets are identical to the release source. Hosted checks verified all five queue names and corresponding inspector selections, the pending-acceptance explanation, muted/paused controls and mobile fit, with no page exceptions.

https://swe-data-workbench.flyswatterghost.chatgpt.site/evaluation-demo/

All three final-audit corrections are implemented. Original data/media and past releases remain unchanged. The release verification asset is a pre-download snapshot; this later source receipt records successful download verification. No new model call, recording, shared-service change or Keep update was made.
