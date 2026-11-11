# Dependencies

The processing core uses Python 3.12 and its standard-library SQLite module. The browser API uses FastAPI, Starlette and Uvicorn. Runtime versions, including transitive dependencies, are pinned in requirements.lock. Development/recording tools are separately pinned in requirements-dev.lock.

The initial installation used public PyPI metadata checked on 2026-11-11. The resolved runtime package set was queried against OSV's vulnerability database on that date; no listed advisory affected the queried versions. This is a dated database result, not a guarantee that a dependency has no vulnerability.

https://api.osv.dev

SQLite is supplied by Python/the operating system rather than replaced by this project. The demonstrated configuration uses rollback-journal mode and FULL synchronization. No system SQLite upgrade or WAL configuration change is required.

Public browser assets use local fonts/assets and have no CDN or model API dependency. Playwright and FFmpeg are development tools for the actual recording; they are not required to inspect the public evidence or use the processing core.

