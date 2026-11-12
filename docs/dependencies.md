# Dependencies

The processing core uses Python 3.12 and its standard-library SQLite module. The browser API uses FastAPI, Starlette and Uvicorn. Runtime versions, including transitive dependencies, are pinned in requirements.lock. Development/recording tools are separately pinned in requirements-dev.lock.

The initial installation used public PyPI metadata checked on 2026-11-11. The resolved runtime package set was queried against OSV's vulnerability database on that date; no listed advisory affected the queried versions. This is a dated database result, not a guarantee that a dependency has no vulnerability.

https://api.osv.dev

SQLite is supplied by Python/the operating system rather than replaced by this project. The demonstrated configuration uses rollback-journal mode and FULL synchronization. No system SQLite upgrade or WAL configuration change is required.

Public browser assets use local fonts/assets and have no CDN or model API dependency. Playwright and FFmpeg are development tools for the actual recording; they are not required to inspect the public evidence or use the processing core.


Focused contributor checks use the existing requirements-dev.lock and Playwright Chromium. The daily-workflow CI uses one Linux/Python3.12 job, read-only repository permissions, immutable action revisions and the same selected tests/installed rehearsal. It requires no model account, owner token or deployment secret. Its browser installation runs in the isolated CI runner, not on the shared fleet host.

A local focused invocation is:

```sh
.venv/bin/python -m pytest tests/test_project_scope.py tests/test_report_containment.py tests/test_exact_observations.py tests/test_attention_cut.py tests/test_review_package.py tests/test_handoff_browser.py tests/test_review_overview.py tests/test_private_assets.py -q -p no:cacheprovider
```

Provision Chromium with the pinned Playwright tool in your own environment. Existing explicit PLAYWRIGHT_BROWSERS_PATH or SWE_WORKBENCH_CHROMIUM settings can select an installed browser where supported. The handoff browser tests generate owned temporary views and use tracked exports; they require no dist or private coordination directory. After installing the selected wheel, use tools/qualify_daily.py from Python isolated mode outside the checkout to exercise the composed CLI, actual private UI, verified overview and private restore. Its reports and decisions are explicitly authored/scripted fixtures.

The CI evidence path adds no Python runtime dependency. GitHub native upload-artifact v7 is pinned to cf430e030ddbb5b0abf93d22962f4752f3646cd9. Its current official tag/README was checked2026-11-12. Fixed external qualification fetches the two pinned public itsdangerous commits and runs only its signer module with the existing tools; historical dependency locks are not installed.
