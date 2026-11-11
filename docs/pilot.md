# Declared local pilot

This pilot runs two small, separate strata once each: the original authored synthetic sample and the approved historical Unicode-hyphen case. A repetition or duplicate delivery is not an additional independent task, author or model output. The pilot measures this configured local workflow; it supplies no production representativeness or model accuracy estimate.

Run from a standalone checkout with its project-local environment:

```sh
.venv/bin/python tools/profile_pilot.py --root .state/pilot --output docs/pilot-report.json
```

The profiler requires fresh stratum state. It records input/catalog digests, actual settings, counts, source origins and frozen export metrics. Each stratum imports its approved local file, processes eligible exact tuples and exports an all-pending-review snapshot. This measurement performs no adjudication and creates no accepted training data. Root's separate real-case walkthrough supplies its own examined, explicitly attributed adjudications.

The declared batch has 12 raw deliveries across the two roots: eight synthetic input lines and four SWE-bench-compatible transport lines for the real case. There are nine unique memberships across the strata, with a duplicate in each and one invalid synthetic line. Two synthetic items and one real-case control remain pending evidence. Trusted execution covers four synthetic submissions and the two approved real-case tuples. The real candidate is the human-authored upstream fix; a comment-only negative is an authored synthetic control. The transport field `model_name_or_path` does not establish model authorship or official SWE-bench membership.

The configured limit is two workers, dispatched only after a current capacity check. Strata run sequentially. Resource capacity is an observation, not a reservation or CPU/RAM isolation guarantee. Each stage records monotonic wall time, parent process user/system CPU deltas, and waited-child user/system CPU deltas. Waited-child counters have the runtime's wait/descendant accounting scope; they are not continuous process-group telemetry. No other project's usage is attributed to this application.

Linux `ru_maxrss` is reported as a cumulative high-water counter before and after each stage, with scope and units. These counters do not measure a stage's memory peak, concurrent workers' aggregate memory, or a peak obtained by subtracting cumulative maxima. Active review time remains unavailable. Process timing from the authoritative frozen snapshot retains its normal cache/recovery and crash-completeness rules. This fresh run claims no cache reuse, interrupted recovery or serial/parallel speedup.

The stage with the largest summed observed wall time across both strata is reported as the limiting measured boundary for this small run. A processing boundary includes controller startup, worker/check execution, waits and result persistence. It does not identify an individual implementation bottleneck or justify a queue/database redesign. A single local observation cannot support a throughput target or projected speedup.

## Observed result, 2026-11-11

The declared pilot completed once at 21:36:26–21:36:27 UTC with two configured workers per sequential stratum. The JSON measurement record is `docs/pilot-report.json`; its source hashes identify the exact working bytes measured. Those hashes still matched after the run. No committed-revision identity is inferred from an uncommitted working tree.

| Stratum | Raw | Duplicate | Invalid | Unique | Completed measurements | Pending evidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Original synthetic sample | 8 | 1 | 1 | 6 | 4 | 2 |
| Configured historical upstream case | 4 | 1 | 0 | 3 | 2 | 1 |
| Sum of separately rooted strata | 12 | 2 | 1 | 9 | 6 | 3 |

All nine unique memberships remain pending review, and both accepted JSONL files are empty. Both exports verified offline; both core integrity checks succeeded, and all six measured results recorded preserved source. The real upstream candidate changed the two patched files and passed all three configured checks. Its baseline failed the Unicode check and passed the other two. The comment-only synthetic control retained the failing Unicode behavior and passed the other two checks; the unapproved variant remained unexecuted. Configured and observed maximum workers were both two in each stratum.

| Stratum / stage | Wall seconds | Parent CPU seconds | Waited-child CPU seconds |
| --- | ---: | ---: | ---: |
| Synthetic intake | 0.003539 | 0.002660 | 0 |
| Synthetic process | 0.193326 | 0.063553 | 0.253468 |
| Synthetic export | 0.011201 | 0.010073 | 0 |
| Real-case intake | 0.002789 | 0.002183 | 0 |
| Real-case process | 0.195540 | 0.029627 | 0.295733 |
| Real-case export | 0.010187 | 0.009058 | 0 |

Processing was the largest measured boundary: 0.388866 seconds across the strata, versus 0.006328 seconds for intake and 0.021388 seconds for export. Child CPU time can exceed wall time with concurrent workers. The measurement groups controller/check startup, executable checks, waiting and result persistence; it does not isolate which operation would benefit from optimization. This evidence supports retaining the simple bounded runner for this workload. No optimization or larger follow-up run is needed to complete this pilot.

The preflight observed 32 affinity CPUs, load averages 0.27/0.36/0.49 and 63,519,322,112 bytes available host memory; the visible cgroup ancestors reported unlimited CPU/memory maxima. The parent `ru_maxrss` counter was already 623,516 KiB before the first measured intake and remained unchanged throughout. Linux preserves resource-usage metrics across `execve`, so that inherited process-history high-water mark cannot be attributed to pilot allocations. Waited-child cumulative maximum counters ended at 21,248 KiB after the synthetic stratum and 46,336 KiB after the real stratum. Aggregate concurrent memory and stage-specific memory peaks remain unmeasured.

## Full Git patch handling

Git applies a patch relative to its discovered repository context. Within an enclosing repository, complete Git diffs can report success while paths outside the current worktree prefix are skipped. The worker now sets `GIT_CEILING_DIRECTORIES` per child invocation to the disposable command directory's parent. This keeps Git discovery within the attempt context while preserving ordinary path validation and exact patch bytes. The worker evidence label is `trusted-task-worker-v2`.

The regression uses the actual upstream two-file Git diff inside an isolated Git ancestor. It checks changed candidate bytes and the observed Node checks, and preserves the ancestor's files, Git metadata and baseline source. This change does not alter launch permission, process group ownership, generation fences or recovery behavior.

Primary implementation references checked 2026-11-11:

https://git-scm.com/docs/git/2.43.0

https://git-scm.com/docs/git-apply/2.43.0

https://docs.python.org/3.12/library/resource.html

https://docs.python.org/3.12/library/time.html#time.perf_counter

https://man7.org/linux/man-pages/man2/getrusage.2.html
