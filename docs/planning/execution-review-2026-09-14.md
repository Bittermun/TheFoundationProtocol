# Execution review — 2026-09-14

This is an implementation checkpoint, not completion of the Foundation mission or a release approval. Work remains governed by the full execution megaplan.

## W00: reliability and honest demonstration — in progress

The audit runner now bounds child execution and requires structured pytest assertion evidence. A crash, fake printed failure, timeout, collection error, or unwritable required report cannot certify an audit. JSON and text modes return a failing status when rejected.

Local credit changes use detached in-memory state and a shared SQLite transaction for replay claims, supply, receipts, and balances. Completed consensus durably records each matching participant's reward entitlement. Pending rewards recover on retry and startup. The tested abrupt exits cover persisted quorum, uncommitted reward writes, and committed rewards before response. Insufficient supply leaves all three rewards pending; it does not pay a subset. Invalid delegation input no longer consumes credits.

These changes establish tested local accounting behavior, not a distributed supply guarantee or proof of useful work. Expected task hashes remain public. Historical completed tasks without entitlement records are not automatically backpaid: that would require an explicit migration policy and historical participation evidence.

The previous full run reported 1,406 passed and two failures. Investigation found a security test leaking simulated gossip supply into later tests, and a missing build frontend in the validation environment. Gossip tests now restore their patched state, and test/development dependencies explicitly include the build tools. The focused rerun passed 41 tests, including settlement and wheel isolation. The subsequent full run passed **1,408 tests with 12 warnings in 190.65 seconds** (`.dist_verify/execution-full-tests.log`). This full run predates the optional model identity changes described below.

Scoped Ruff passed for the audit runner, accounting server, and changed regression/security tests. The real browser journey passed eight groups: assets/sample data, debit across refresh, draft recovery, failed publishing, exact UTF-8 download and inert HTML, filtering, offline/reconnection, and four mobile views. Raw local output: `.dist_verify/execution-browser.log`.

README and the demo explanation now describe contributed work, reusable lexicon resources, demand-directed delivery, and independent networks as the intended mechanism. The local library's demonstrated scope is explicit.

## Legacy acceptance reconciliation — requirements retained

| Requirement | Current evidence and remaining work |
| --- | --- |
| Functional lifecycle, actual execution, all participant rewards | New reward recovery coverage includes every qualifying participant. The older E2E's copied expected hashes do not prove task execution or useful artifact production. W05/W06 remain necessary. |
| Restart persistence, metrics, maintenance | Abrupt-process accounting tests add evidence beyond lifecycle-only tests. They do not cover every listed persisted subsystem, metric, or maintenance restart requirement. |
| Authentication, replay, supply, limits, secret scan | Local tests remain required. No local suite proves distributed economics or substitutes for the required remote security job. |
| Fresh/restarted operational surfaces, CLI and Docker | Browser checks cover the local UI. Installed-wheel and comprehensive operational checks remain separate requirements; Docker execution is unverified. |
| Lint, security scan, types, tests and build | Scoped lint is not whole-repository lint. Full-suite and final distribution evidence must be current; required broader checks remain open. Root packaging is authoritative for the runnable demo; the legacy nested installation command still requires reconciliation. |
| CI, docs freshness, release branch | No current remote green run or release approval is claimed. The README uses a live workflow badge, not a numeric test-count badge; stale numeric-badge acceptance needs an explicit equivalent check, not a fabricated count. |
| Behavior/ops smoke on fresh node and restart | Existing browser checks do not substitute for the full task lifecycle and operational smoke scripts. |

## W02: workload preparation — in progress

`scripts/prepare_lexicon_corpus.py` freezes reproducible paragraph records from repository Markdown at commit `42b31829dc8623a38a5c30ffffd4e37173ed671f`, with source hashes, file-separated train/tune/test splits, and exact duplicate removal. The existing exploratory output contains 623 records and 288,692 bytes from 20 files (361 train, 45 tune, 217 test). The corpus SHA256 is `359d6a285aa92f3b48ba160773a77aa45e27dfb0434a1160214d8fa66c290b68`.

This is normalized project documentation, not a real adopter workload or reuse trace. File separation does not exclude near-duplicate material. The development host is not modest-device evidence. No performance result or practical benefit threshold has been established yet. W02 cannot pass until the workload/budget contract is frozen and its limitations are explicit.

## Follow-up verification — 2026-09-15

The rebuilt wheel passed the archive inspection and installed into the previously absent `.dist_verify/installed-20260915` environment. Its HTTP smoke ran from `C:\Users\msunw\Downloads` with `PYTHONPATH` removed and passed installed-interface loading, enrollment, allowance, publication, tag discovery, exact UTF-8 retrieval, one-credit debit, and idempotent re-enrollment. The resulting balance was 9. The wheel SHA256 was `a0ba31f692ca133bac66a885bf4f5a7bba7c465af20c1eae1d7412a27b09a085`. This wheel predates the subsequent optional search repair and will require rebuilding before delivery.

Whole-repository Ruff passed after removing two unused imports in the AST lint tool. A configured medium/high Bandit scan found the optional RAG model downloaded mutable `main` despite claiming a fixed revision. Regression tests failed before repair. The default now pins CodeBERT to model-repository commit `3b0952feddeffad0063f274080e3c23d75e7eb39`, verified against the [publisher's repository API](https://huggingface.co/api/models/microsoft/codebert-base/revision/main). Custom models require an immutable commit. Loading is instance-local so different requested model identities cannot accidentally share the first loaded weights. This was tested with substituted loaders, not a heavyweight model download or inference run.

Three model-identity tests and six configuration tests passed. Configuration tests now use their own temporary directory rather than a shared hardcoded test path. Whole-repository Ruff still passes. Bandit with `-c bandit.ini -r tfp-foundation-protocol -x tfp-foundation-protocol/build -ll` reports zero medium/high findings (18 low findings remain). The exclusion removes generated package copies, not source or tests. No security certification is claimed.

The original type-check command stopped on duplicate generated modules. Re-running with only generated `build` directories excluded completed: **19 errors in 12 files, 172 source files checked** (`.dist_verify/execution-mypy-source.log`). These include incomplete annotations, a pending-gossip conversion calling a missing method, uploader cancellation handling, and a wallet transfer return-contract mismatch. They need causal review and appropriate regression tests, not broader error suppression. Existing mypy configuration already suppresses several categories and skips bodies of untyped functions; passing that configuration alone would not establish complete type safety.

## Next steps

The source type-check findings have now been resolved (see the continuation below). Finish the current full suite and rebuild/inspect/install the current wheel after source changes settle. Continue the remaining W00 acceptance checks, then complete measurement isolation and the workload contract before measuring a shared-resource candidate. W03–W14 remain unverified.

Latest continuation: the real-process operational smoke now passes fresh/restarted surfaces, signature rejection, all-participant earned-credit spending, five persisted counters, open/completed/verifying tasks, quorum continuation, and replay behavior. It exposed missing-signature responses returning 422 instead of the documented 401, and metrics being seeded before sample content/tasks. Both were corrected. `tfp_cli.operational_smoke` reaps each server process and uses the same temporary persistent data directory for the restart. Full maintenance timing, Docker, and remote CI remain unverified. Current runtime source has changed since the earlier wheel.

The first controlled shared-dictionary experiment is now executed and independently byte-audited. It failed the predeclared minimum cold-client savings (6.1% observed versus 10% required at 100 records). See [the experiment decision](lexicon-e1-v1-review.md). The exploratory candidate is recorded as verification_failed under W04; the overall packet remains waiting_for_dependencies and full G4 is unverified. No pooled dictionary implementation is being justified by this result.

## Type-check and behavioral follow-through — 2026-09-15

All 19 reported errors have been resolved without adding suppressed error categories. The original mypy command now excludes only generated `build` directories via configuration and passes for 172 source files. CI includes a source type-check job; its remote execution is not yet verified.

Regression tests first reproduced pending gossip retrieval calling a nonexistent serializer and both uploader paths returning cancellation objects as successful chunk IDs. Gossip now uses the repository model's serializer. Upload result handling propagates cancellation. The three regressions pass.

The hybrid-wallet simulation contained actual accounting defects behind its return-type error: unspent compute counted toward unauthorized mixed spending, failed mixed spending consumed compute, and transfers credited half of single-type amounts. New tests reproduced these failures and NaN spending. The repair validates authorized debit amounts before committing, preserves each credit type in a local transfer, returns the promised transaction record, and retains usable receipt change after partial spending. Custom transfers still create a new local recipient wallet; this is not a durable, authenticated cross-node transfer system. An old test accepted undercharging with an OR assertion; it now supplies a receipt and checks both exact balances. Fifty focused component/economics tests pass.

Other fixes describe existing runtime types, place `size_bytes` directly on its dataclass, and remove an unused domain cache. Chunk caching now imports its required packaged Bloom filter directly; the removed fallback did not implement the constructor's required sizing methods.

The E2E lifecycle now runs each supported task type (hash-preimage, matrix verification, content verification) for all three participants with the expected answer removed from the worker input. It submits computed output hashes and checks that every participant can pay for exact content retrieval. All seven tests in that module pass. This is in-process execution evidence; it does not yet prove useful lexicon output or a physical worker fleet.

Whole-repository Ruff passes. The source Bandit scan still reports zero medium/high findings and 18 low findings. Docker Engine was checked again and is unavailable (`dockerDesktopLinuxEngine` named pipe missing), so Docker runtime verification remains open. The full-suite run in `.dist_verify/execution-full-tests-current.log` passed **1,424 tests with 11 warnings in 187.36 seconds**; it began before the E2E test expansion, whose seven passing cases are recorded separately.

The current source was rebuilt and its wheel inspected, then installed in the newly created `.dist_verify/installed-current` environment. The HTTP smoke ran outside the checkout with `PYTHONPATH` removed and passed all eight checks, ending with nine credits. Raw result: `.dist_verify/execution-smoke-current.json`. Current wheel SHA256: `752636a1a10af510ccd414980e9a8ebcf46e63a60e5e393c1e105e0d3c91cd32`. No commit, push, remote CI pass, Docker run, or release completion is claimed. Full operational restart coverage and W01 onward remain work to execute.

## Commit checkpoint — 2026-09-15

The user explicitly requested committing and pushing this unfinished implementation checkpoint and a GitHub comment recording the intended mission and limitations. This supersedes the historical handoff's pending publication request; it does not authorize claiming a finished protocol or release.

Final source validation: **1,428 passed, 1 failed, 11 warnings in 190.33 seconds**. The failure was `tests/v2_8_mutualistic_defense/test_mutualistic_defense.py::TestEdgeCases::test_low_volume_malware_detection`, which relies on randomized sampling over 100 attempts. An isolated rerun passed (1 test, 0.21 seconds). This indicates a potentially intermittent test/behavior issue, not a clean full-suite pass; it remains unresolved. The test was not weakened or removed. Whole-repository Ruff and the configured source mypy check (172 files) passed. Existing mypy configuration limits coverage.

The manual-command test helper now loads the root smoke module explicitly by source path to avoid collection collisions with the legacy nested CLI package. Actual command checks still run in fresh subprocesses. Current source checks must not be confused with the earlier installed-wheel verification above: that wheel predates subsequent runtime changes. Final-wheel, Docker, and remote CI verification remain open.
