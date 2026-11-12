# One real Keep change, reviewed without running Keep

This example captures an actual source correction made by another instance: check required sandbox readiness before offline dependency installation. It separates the corrected .22 source from the previously published .21 archive and retains unsigned reported checks with their scope.

The workbench reads Git objects and selected public evidence. It makes no Keep changes, executes no Keep checks and issues no model requests. It never treats reported checks as its own execution or grants permission to deliver the source project.

After installing the workbench dependencies, obtain the public Git objects explicitly into your own input directory:

```sh
mkdir -p .state
git init .state/keep-input
git -C .state/keep-input fetch --no-tags https://github.com/RedRookAI/keep-research-preview.git acb84e9be37a681790a4943718c675a0ee1566a0 e53867c1c2add998b9d382f26fc6c7aa97b3b2b7
.venv/bin/python tools/run_handoff_trial.py --repo .state/keep-input --root .state/change-handoff
```

An existing local repository containing those commits can be selected instead. Its working tree may contain unrelated edits; capture reads committed objects only. The driver needs a fresh owned output root and never checks out, resets, installs or executes the input project. Its review explicitly replays the recorded assisted assessment after checking the selected candidate and evidence identity.

The receipt separates capture, review, export and fresh-process read/verification times. These measure command execution only. They do not measure human review, prove time savings or include the one-time feature development and per-change evidence mapping work.

For another supported regular UTF-8 Git change, use the generic capture-handoff CLI with a small owner-authored request and named local evidence attachments. capture-request.json is an example: observations reference dictionary key paths within the retained JSON evidence. Paths/commands inside that evidence are data. Capture preserves exact source, patch and attachment bytes. Unsupported input refuses rather than widening execution authority.

A handoff-ready decision means the review package is ready for its owner. It does not mean the code was independently checked, merged or released. Changing the relevant material resets that current decision; prior reviews remain inspectable. Exported handoff.json, artifacts.json and manifest.json verify offline with verify-handoff.

The fresh-context assisted review found that multiple different revision fields were not explained. The later package includes the frozen qualification workflow, fixture harness and revision-roles.json. The workflow checks out the product source; the receipt's sourceRevision identifies the consumer fixture created by the harness. fresh-review.json preserves the original finding and identifies its initial input hashes rather than pretending a new review occurred.

The retained source/report/harness belong to the public Keep research preview under KEEP-LICENSE. They are evidence attachments, not automatic instructions or a complete runnable Keep installation. The public qualification report's scope and remaining compatibility work remain intact.
