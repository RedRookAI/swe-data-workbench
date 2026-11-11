# Synthetic fixture catalog

All source, checks, patches and seeded labels in this directory were authored for this demonstration, with substantial AI implementation assistance, under the repository MIT license. They are synthetic examples, not model evaluation results or independent human reviews.

`catalog.json` is the trusted execution allowlist. Exact patch strings bind to a task context; imported task IDs and patch strings do not choose commands or paths. `sample.jsonl` has eight raw lines: six first valid unique memberships, one exact duplicate and one deliberately malformed record. Four unique submissions are executable trusted tuples. One has no patch; another differs from its trusted patch by an extra final newline and must remain unexecuted. Context-distinct identical patches stay distinct.

The weak visible checks cover ascending inputs. Both the correct `list(dict.fromkeys(items))` patch and the semantically wrong `sorted(set(items))` patch pass them. For input `["b", "a", "b"]`, the task requires `["b", "a"]`; the sorting patch returns `["a", "b"]`. This counterexample is disclosed as fixture ground truth, not claimed as an additional executed check. The genuinely failing candidate drops distinct values. Baseline checks execute the unchanged source and fail duplicate removal while preserving empty/distinct ascending behavior.

Two seeded reviewer labels on the wrong patch are explicitly synthetic. They supply comparison data only. Current authoritative disposition remains pending until an actual operator review.
