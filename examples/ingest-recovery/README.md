# Ingestion task audit and repair

A service commits a tenant total before its replay receipt. An interruption between those writes makes replay count an event twice. The first checker closes normally, so it gives the buggy control full credit.

Run from a clone after installing requirements.lock:

```sh
.venv/bin/python tools/run_quality_demo.py --root .state/quality-example
```

The account-free driver reconstructs the original committed source, calls the real preparation command, runs the same four admitted patches against weak-v1 and fixed-v3 and leaves an unapproved variant unexecuted. It explicitly replays the recorded AI-assisted task assessment, freezes both evaluation datasets and verifies them offline. The receipt identifies every output. Existing output directories are preserved; choose a fresh root for another run.

The source and controls are original MIT-licensed examples. One recorded Codex attempt received task.txt and visible/eventflow only. candidate-001.json records its actual access conditions and source hashes. Reference patches, protected checkers and expected outputs were outside that task's supplied directory. The shared user account was not an OS access sandbox. Repeated transport records reuse one patch result; they are not extra attempts.

The reference keeps totals and receipts in one transaction. The alternate derives totals from the durable receipt ledger. The recorded attempt moves the receipt into the total's transaction. They are checked by public behavior rather than similarity to the reference.

Two separately recorded AI-assisted calibration passes examined weak-v1 and the initial fixed-v2. Both identified the missing durable-effect assertion. Their original input, reports and involvement are retained under calibration/. One reviewer implemented the worker; the other authored candidate001. Their agreement is not independent human validation. fixed-v3 adds pre-replay durability, exit/exception at two positions, parsing boundaries, CLI and original successful-state compatibility. v2 bytes and preliminary results remain intact.

Credit is 25 ordinary, 25 identity and 50 recovery, with a separate critical recovery gate. It measures these named checks. Signed64 aggregate overflow remains an open, unmeasured coverage limitation: reaching it through valid signed32 public events requires over four billion records. The task retains that requirement; the demo does not certify exhaustive contract coverage. A passing candidate is separate from approval of the task into an evaluation set.

Outputs use separate formats: evaluation exports retain every candidate, including failures and missing evidence; the existing accepted-code JSONL contains only explicitly accepted code and is empty in this example.
