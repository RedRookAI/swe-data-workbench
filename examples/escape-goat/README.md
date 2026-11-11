# Prepare and inspect a real repository

This example uses two genuine historical revisions of escape-goat PR13. Both were authored in the same upstream pull request; their transport names are labels, not model identities or independent attempts. Source and patches are MIT-licensed; the original notice is retained in license. The task text and three Node assertion checks were prepared with Codex assistance.

The early revision adds String conversion to regular functions. The later revision confines it to template-tag substitutions, as the upstream review requests. Our check recipe covers tag conversion, ordinary string preservation and the regular functions' existing non-string rejection. The original AVA/TypeScript suites are not executed.

## Obtain the pinned source explicitly

From the workbench checkout with its project-local environment installed:

```sh
mkdir -p .state
git init .state/escape-goat-source
git -C .state/escape-goat-source fetch --depth=1 https://github.com/sindresorhus/escape-goat.git 235683eb791e13336cf4bd9705ea9df97e0d8e51
.venv/bin/python tools/run_prepared_demo.py --repo .state/escape-goat-source
```

Fetching obtains the public Git objects without a checkout. The driver then calls the real preparation CLI, imports predictions, stops after one committed measurement and resumes in a fresh process. It makes no model call or review decision. The JSON receipt identifies the prepared bundle, state and observed batch. Use fresh owned output/state paths for another run. Both candidate measurements and the unapproved control remain available for inspection.

## Use the preparation command directly

```sh
.venv/bin/python -m swe_workbench.cli prepare-bundle \
  --repo .state/escape-goat-source \
  --commit 235683eb791e13336cf4bd9705ea9df97e0d8e51 \
  --task-id sindresorhus__escape-goat-pr13 \
  --task-text examples/escape-goat/task.txt \
  --source index.js --source test.js --source index.d.ts --notice license \
  --checks examples/escape-goat/checks.json \
  --candidates examples/escape-goat/candidates.json \
  --provenance examples/escape-goat/provenance.json \
  --predictions examples/escape-goat/predictions.jsonl --format swebench \
  --name escape-goat --title 'Prepared repository: escape-goat PR13' \
  --output .state/my-escape-goat-bundle
```

The fresh output must have an existing parent and be outside the selected source repository and input files. Its preparation.json lists exact committed blobs, command argv, patch/check/source identities, notices and prediction digest. Preparation runs no supplied check, applies no patch and creates no runtime database. A populated output is preserved rather than overwritten.

Selecting candidates.json deliberately admits those exact patches and commands to the existing trusted execution profile. Imported prediction claims never add permission. Here four records contain two genuine revisions, one repeated revised-patch delivery and one authored unapproved extra-newline variant. Only the two selected patches can execute.

For your own supported task, provide explicit tracked source/notice paths, task text, check argv, candidate files and provenance. checks.json is a list of name/argv/timeout objects. candidates.json lists patch_file, model_name_or_path and provenance for each explicitly selected patch. Source provenance requires origin, license and repository; candidate provenance requires origin and license. Omit --predictions to generate native records from selected candidates, or choose native/swebench for a supplied byte-exact file. The command generates the internal catalog. It never infers an admission decision from a model name.

The current preparation profile supports Linux, complete local Git objects and committed non-executable UTF-8 regular blobs (mode100644). Binary/executable/symlink/gitlink source entries and partial clones are refused. Dirty/untracked files are excluded; check dependencies must already fit the owner-inspected execution environment. Explicit task commands are trusted code, not contained by a general sandbox.

## Inspect, decide and export

The driver defaults to .state/prepared-example and .state/prepared-example-bundle. Supply the normal owner token through your local environment, then launch the existing private browser:

```sh
.venv/bin/python -m swe_workbench.server --root .state/prepared-example --bundle .state/prepared-example-bundle --port 8097
```

Use your trusted private connection with ?mode=live. Inspect Task & patch, Machine evidence and Provenance, then enter criterion judgments and an accurately attributed exact-version decision. Freeze accepted export through the interface. The receipt identifies a directory containing exactly accepted.jsonl, evidence.json and manifest.json. Verify it offline:

```sh
.venv/bin/python -c "from swe_workbench.exporter import verify_export; import sys; print(verify_export(sys.argv[1]))" PATH_FROM_EXPORT_RECEIPT
```

The public recording separately replays decisions that were actually examined after execution. Original AI-assisted assessments and evidence references are in docs/examples/prepared-run/assessment.json; the browser replay is explicitly scripted and binds to its own actual evidence. No independent human assessment is claimed.

https://github.com/sindresorhus/escape-goat/pull/13

https://github.com/sindresorhus/escape-goat/pull/13#discussion_r288880742
