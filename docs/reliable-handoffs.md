# A handoff you can repeat and restore

Preview the files and evidence a profile selects. Capture their exact versions, inspect the result, record your decision and export a package another reviewer can verify. A private backup preserves your saved reviews and original history.

Install the release wheel in a local Python3.12 environment with its pinned runtime dependencies. Linux and Git are required. In a source checkout, the same commands work with that checkout's modules. Choose a fresh example directory under an existing parent:

```sh
python -m swe_workbench.receipt_example --output /tmp/handoff-example
```

This creates a new synthetic Git repository and runs one fixed check of value.py. It writes a reusable profile, receipt and inputs.json. The receipt records the revision observed at the check boundary and the source/check identities. Each invocation uses its own fresh directory. It does not open another project or call a model.

Use the full base/candidate commit IDs printed by the example. Supply the same explicit input arguments to preview and capture; substitute those actual IDs for BASE_COMMIT and CANDIDATE_COMMIT below:

```sh
python -m swe_workbench.cli --root /tmp/handoff-review preview-handoff \
  --repo /tmp/handoff-example/source --base BASE_COMMIT --candidate CANDIDATE_COMMIT \
  --profile /tmp/handoff-example/profile.json --evidence-dir /tmp/handoff-example/evidence \
  --change-id example-change --title "Change the example value" --goal "Set value to 2"

python -m swe_workbench.cli --root /tmp/handoff-review capture-handoff \
  --repo /tmp/handoff-example/source --base BASE_COMMIT --candidate CANDIDATE_COMMIT \
  --profile /tmp/handoff-example/profile.json --evidence-dir /tmp/handoff-example/evidence \
  --change-id example-change --title "Change the example value" --goal "Set value to 2"
```

Preview creates no runtime state. It shows the exact material and selected evidence bindings, with required completeness separate from reported outcomes. Missing report fields remain unknown. Invalid configuration names the field to correct. Capture rereads the inputs; preview does not reserve or approve later bytes.

Inspect the reported check, source context and scope. Use capture's actual revision and material_digest in your decision. This example command explicitly records an owner decision; supply your own reason, findings and next action after inspection:

```sh
python -m swe_workbench.cli --root /tmp/handoff-review review-handoff example-change \
  --expected-revision CAPTURE_REVISION --material-digest CAPTURE_DIGEST \
  --decision handoff-ready --reason "Inspected the fixed synthetic check and its scope" \
  --next-action "Review the exported change" --responsible-party "Project owner" \
  --reviewer-mode owner_adjudication --operation-key example-review-1

python -m swe_workbench.cli --root /tmp/handoff-review export-handoff example-change --output /tmp/handoff-export
python -m swe_workbench.cli verify-handoff /tmp/handoff-export
```

Use needs-work and repeat --finding when information is unresolved. A changed material rejects a stale review. Handoff-ready means the package is ready for review; check failures remain visible and code acceptance is separate. Normal repeated capture returns the current review. An explicit operation-key retry returns its original response. If export fails because its destination exists, retain the captured review and choose a new export directory.

## Reuse your own check results

write-receipt accepts a JSON file of supplied source/check facts and writes a fresh receipt file. It runs no checks. The producer remains responsible for supplying what actually happened. See swe_workbench/receipt_example.py for a complete fixed-check producer and docs/data-contract.md for the supported fields.

```sh
python -m swe_workbench.cli write-receipt --request /path/to/observed-facts.json --output /path/to/fresh-receipt.json
```

A clean declared revision supplies execution_revision; dirty or unknown working-tree context leaves that binding unknown. Outcomes distinguish passed, failed, skipped and unavailable. Preserve check/input hashes and explicit scope when adapting the example. The report is unsigned external evidence; its format does not authenticate a producer or establish SLSA compliance.

## Keep a private backup

Back up quiescent state into a fresh private directory. Restore into another fresh directory, then use that directory as --root:

```sh
python -m swe_workbench.cli --root /tmp/handoff-review backup-state --output /tmp/handoff-backup
python -m swe_workbench.cli restore-state /tmp/handoff-backup --output /tmp/handoff-restored
python -m swe_workbench.cli --root /tmp/handoff-restored handoff example-change
```

The snapshot includes SQLite records and content-addressed artifacts. It preserves original review, retry and audit identities. Reading and continuing a handoff review needs no original profile location. Running additional native tasks still requires their separately admitted bundles. Source repositories, published export locations, credentials and disposable attempt directories remain external; recorded locations are historical.

Active or uncertain unfinished execution is refused. Restore never resumes a worker or signals a historical process ID. Existing destinations, incompatible schemas and corrupted/missing content produce a refusal. Backups contain private evidence and should stay outside public Git, hosting and release assets.

## Verify a release installation

The maintainer check uses the actual installed wheel and existing frozen v1/v2 exports. Run it outside the source checkout, with absolute paths and a fresh output directory:

```sh
python -I -m swe_workbench.release_check \
  --wheel /path/to/swe_data_workbench-VERSION-py3-none-any.whl \
  --legacy-export /path/to/frozen-v1-export --current-export /path/to/frozen-v2-export \
  --output /path/to/fresh-private-qualification
```

It checks installed file parity, preview/capture/review/retries/export, backup/restore and review continuation, then verifies that missing source binding remains unresolved. The qualification decision is explicitly scripted. It records exact failed stages and never publishes. Browser checks are recorded separately in docs/verification.md.
