# Retain an actual CI run with its change

The fixed GitHub recipe runs the selected pytest command once and emits its original JUnit XML. It records source/check context before and after that command, then uses the existing prepare-review path. A nonzero test exit remains a failed workflow even when evidence packaging succeeds. Assembly leaves the review unreviewed.

## Run the fixed recipe

Install requirements-dev.lock and the workbench wheel in a project-local environment. In GitHub, open Daily workflow → Run workflow. Choose normal, itsdangerous or intentional-failure. The last option deliberately executes one failing pytest assertion to qualify evidence delivery. Ordinary pushes and pull requests use normal.

For the historical external case locally, choose a fresh absolute output directory outside the workbench and use the installed environment:

```sh
.venv/bin/python -I tools/ci_recipe.py setup --workspace "$PWD" --root /owned/fresh-external-run --case itsdangerous
.venv/bin/python -I tools/ci_recipe.py check --root /owned/fresh-external-run
.venv/bin/python -I tools/ci_recipe.py package --root /owned/fresh-external-run
```

Run packaging after a failed check too; it preserves that outcome. The source acquisition is a fixed public fetch into a fresh owned copy. The ordinary packager and observer perform no source acquisition. One-time setup selects the profile, source and comparison refs; each fresh run repeats observation, execution and packaging. Human time savings remain unmeasured.

The historical source is pallets/itsdangerous at7f4dcf83a07bb3d53f4e0e65ef1b43327b4cca90, compared with parent93ae366874bbd4f69d90495c45b2cd336387496c (2024-04-16). It defers SHA-1 lookup until use. The recipe checks the unmodified tests/test_itsdangerous/test_signer.py with the current pinned workbench tools and confirms imports come from that checkout's src directory. This ordinary signer scope does not establish FIPS compliance or a baseline-failure/candidate-pass result. The workbench did not author the change. LICENSE.txt is redistributed with its source-containing package.

https://github.com/pallets/itsdangerous/commit/7f4dcf83a07bb3d53f4e0e65ef1b43327b4cca90

## Observe an existing pytest invocation

The generic observer executes nothing. The caller supplies the same declared argument list it executes, selected input paths and an output directory outside source:

```sh
checks=("$PWD/.venv/bin/python" -m pytest tests/test_ci_evidence.py -q -p no:cacheprovider --junitxml=/owned/fresh-observation/original.xml)
.venv/bin/python -m swe_workbench.ci_evidence begin --repo "$PWD" --product RedRookAI/swe-data-workbench --output /owned/fresh-observation --input tests/test_ci_evidence.py --input requirements-dev.lock -- "${checks[@]}"
set +e
"${checks[@]}"
result=$?
set -e
.venv/bin/python -m swe_workbench.ci_evidence finish --output /owned/fresh-observation --exit-code "$result"
# Preserve "$result" as the test outcome; successful finalization does not change it.
```

The fixed recipe declares all tracked product files as inputs and keeps outputs outside source. A local caller chooses the relevant inputs. Dirty source, changed HEAD/status/input bytes, missing inputs or unavailable observations leave candidate execution unbound. Git-ignored, nonselected files, dependency contents and changes that disappear between observations remain outside this guarantee. Runtime versions and selected input hashes describe scope; they do not make execution hermetic.

Exit0,1,2,3,4,5 and6 retain pytest's pass, test failure, interruption, internal error, usage error, no-tests and warning-limit meanings. Other exits remain named errors/termination. A valid empty report retains zero executed cases. Missing or malformed XML yields incomplete evidence with the original available bytes; finalization never creates cases or synthetic XML. Terminated runners may leave no final receipt or artifact.

## Explicit optional receipt import

The unchanged run-context/v1 contains source revision/state, check-definition digest and named input digests. CI-receipt/v1 separately binds the exact XML, context and check-definition bytes, observed pre/post source, process exit and allowlisted provider identity. The XML hash is output identity; the check definition hashes the declared argv/input/runtime manifest. Provider upload identity is obtained later and cannot be embedded in its own payload.

```sh
swe-workbench import-junit /owned/fresh-observation/original.xml \
  --context /owned/fresh-observation/run-context.json \
  --ci-receipt /owned/fresh-observation/ci-receipt.json \
  --check-definition /owned/fresh-observation/check-definition.json \
  --output /owned/fresh-import
```

This explicitly generates the CI variant of the pytest profile. Its repository label comes from the validated receipt's tested product, independently of the workflow repository. Configure directly with this fresh profile as in daily-workflow.md. Supply the same --ci-receipt and --check-definition to prepare-review along with --report and --run-context. Report-only profiles retain their original two attachments and need no migration. The extension does not silently edit a configured profile or its context identity. Exact unfinished resume and legacy v1..v4 histories retain their original rules. Existing configured profiles/contexts are never rewritten; an old mismatched profile needs explicit setup with a new generated profile and fresh context, preserving the prior files and state association.

The view and summary distinguish tested product/SHA, workflow repository/SHA, run/attempt/job, proposed PR head/base, process exit, report counts and explicit review. Missing provider data means local scope. Hash or source-label conflicts are refused or displayed as invalid evidence; successful process exits with failed/error/empty reports remain discrepant.

## Source and base selection

The tested source is the actual checkout HEAD. GitHub's workflow SHA/ref identifies the workflow separately. A PR comparison uses its declared base and the actual checkout (normally the test merge); the proposed head is retained separately. A push uses its previous SHA. Manual workbench qualification uses the pinned0.1.0a9 docs checkpoint4ed531cae30a8cd7c8a18ca2da5d675b0511cc7f. The external recipe uses its fixed historical parent/candidate. CI acquires the required Git objects before capture.

An unavailable initial base, missing base object or identical base/candidate leaves a named diagnostic outcome and original report. There is no guessed diff or acquisition inside capture. Reports may remain unbound when source changes; packaging success never grants approval.

## Download and disclosure boundaries

A run/attempt/job/case name identifies an immutable native artifact. Staging contains only view/, export/, summary.json, original.xml, ci-receipt.json, run-context.json, check-definition.json, package-status.json and external notices when applicable. Diagnostics may contain a subset. Runtime databases, backups, project contexts, private assembly receipts/selections, full checkouts, environments and unrelated logs are excluded. Source and XML embedded in exports remain disclosed and must suit the audience.

Upload uses the pinned native upload-artifact action, hidden files disabled, overwrite false, missing-file error and the repository's retention policy. Returned artifact ID/URL/digest are written separately to the job summary after upload. Inspect the original check, packaging and upload outcomes independently. No PR commenting, secret expansion or automatic release/site deployment is configured.

Download through GitHub's artifact control while signed in. After extraction, use verify-handoff on export/ or view/handoff/. Provider ZIP SHA256 and the workbench manifest digest identify different layers; compare each with its corresponding receipt. Serve view/ through an existing trusted HTTP connection. A double-clicked file:// page cannot reliably load its modules/evidence. The audited public selection on the existing preview provides an anonymous browser route and the release retains a stable chosen download.

For an existing static workbench build, tools/build_ci_gallery.py can add these three explicitly selected extracted artifacts using --dist, --normal, --external and --failure. It verifies each export, receipt, source/outcome and file allowlist before copying. Only use public-safe inputs. Existing CI selections refuse overwrite; start with the retained earlier build for a different selection.

## Research checked2026-11-12

GitHub variable/event and artifact documentation supplies the identity, status and delivery behavior. Current tagged upload-artifact v7 was checked against its official ref; older tutorial snippets still use v4. Pytest documents JUnit and exit meanings. Research about artifact verifiability motivated retained source/recipe context; this preview makes no measured reproducibility, independent-attestation or model-quality claim.

https://docs.github.com/en/actions/reference/workflows-and-actions/variables

https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

https://docs.github.com/en/actions/reference/workflows-and-actions/expressions

https://github.com/actions/upload-artifact/blob/v7/README.md

https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files

https://docs.pytest.org/en/stable/reference/exit-codes.html

https://arxiv.org/abs/2608.18180

https://arxiv.org/abs/2605.21089
