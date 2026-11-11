# Prior art

Checked 2026-11-11. These sources informed the design; their reported results are not measurements of this application.

Research on SWE-bench patch correctness motivates separating executable check results from semantic adjudication. The paper was first submitted in March 2025 and revised in September 2025.

https://arxiv.org/abs/2503.15223

October 2026 research treats task clarity and test coverage as separate data-quality problems. This demonstration uses explicit rubric criteria for both.

https://arxiv.org/abs/2610.39417

SWE-smith is prior art for creating executable coding tasks. This application focuses on processing and review rather than building another task generator.

https://arxiv.org/abs/2504.21798

Label Studio provides established annotation workflows. This demonstration uses a small fixed-rubric interface to show the relationship between actual execution evidence, recovery and dataset acceptance.

https://labelstud.io/guide/label_studio_compare

SQLite and Python document the transaction behavior used for the single local authority.

https://www.sqlite.org/transactional.html

https://docs.python.org/3.12/library/sqlite3.html

Keep supplies prior art for content-bound decisions, write-ahead intent and preservation of uncertain outcomes. This application runs independently and does not copy or import Keep's runtime.

https://github.com/RedRookAI/keep-research-preview

