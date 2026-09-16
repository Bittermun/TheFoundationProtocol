# Foundation Protocol — AI handoff

Prepared 2026-09-12. Read this before changing the project. This is a continuation brief, not a claim that the project is complete.

Read the root [agent guide](AGENTS.md) and [purpose/downside review](docs/planning/purpose-and-regression-review.md) alongside this historical brief. In particular, the 6.1% standalone dictionary result does not evaluate the integrated Lexicon or define its potential. The notebook is a demonstration, not the project objective.

Implementation continuation: [execution review](docs/planning/execution-review-2026-09-14.md) records subsequent accounting recovery, audit, type-check, E2E, and installed-wheel work through 2026-09-15. The older failure counts and some defect descriptions below are historical. Consult that review and the current worktree before repeating repairs; the full mission remains unfinished.

Planning follow-up: [Foundation execution megaplan](docs/FOUNDATION_MEGAPLAN.md) and its [execution board](docs/planning/execution-board.json) now extend this handoff. Eight bounded source probes identified additional lexicon identity/update and measurement issues. No runtime repairs or full-suite validation were performed by that planning work. Preserve this handoff's mission and existing edits; use the megaplan for the updated dependency order.

## Start here

**Keep the reliability improvements. Correct the narrowed product story. Prove one useful connection between pooled work and a shared resource before expanding the feature list.**

The user gave authority for a long autonomous improvement session and requested a commit/push to GitHub after completion. They then asked for discussion and this handoff. The original completion/push request remains unfinished. Do not interpret this document as a request to publish an unfinished release immediately.

The user has limited ability to review AI-written software and wants something they can understand, trust, and proudly demonstrate. Explain observable results in plain language. Proceed with authorized routine work; ask only for decisions that materially affect the intended mechanisms. Do not substitute a simpler product for their idea because it is easier to demonstrate.

## The project the user actually means

Foundation is intended as shared infrastructure for content and useful computation across devices and networks. The content library is one demonstration, not the whole product.

The user's corrections are essential:

- Weak devices should contribute meaningfully, with benefits beyond merely receiving credits.
- Pooled computation is supposed to make the lexicon efficient. That shared resource should reduce the work and cost of managing content and building other systems.
- Video should scale automatically with demand, through mechanisms more distinctive than ordinary bandwidth reduction.
- Devices should be able to contribute to other projects, and people should be able to build their own networks that integrate with existing networks.

Working interpretation to preserve, **not yet a verified architecture**:

```text
Devices contribute affordable, useful work
                  ↓
Pooled work builds / improves shared lexicon resources
                  ↓
Other devices and projects reuse those resources
                  ↓
Lower repeated work and delivery costs; smaller devices can participate

Demand → allocation of preparation / caching / distribution work
Adapters → use within independently built systems and connected networks
```

Do not collapse “lexicon” into tags, an acronym dictionary, or a searchable notebook. The code contains a broader concept of versioned shared priors, dictionaries, and adapters, but the concrete representation and useful construction algorithm remain unresolved. Likewise, do not silently interpret demand scaling as video bitrate adaptation: the user has not specified exactly which combination of preparation, replication, broadcast, or other mechanisms they mean.

Hashes identify/verify resources; they do not reconstruct arbitrary missing information on their own. Any efficiency demonstration must account for the shared resource's construction and distribution cost, cold versus warm clients, verification overhead, and reuse. Device capability labels alone do not establish useful performance on weak hardware.

## Repository state to preserve

- Workspace: `C:\Users\msunw\Downloads\TheFoundationProtocol`.
- Branch: `main`; unchanged HEAD: `42b31829dc8623a38a5c30ffffd4e37173ed671f`.
- Remote: `https://github.com/Bittermun/TheFoundationProtocol.git`.
- There are substantial **uncommitted tracked changes and untracked source files** from this session. The initial checkout was clean. Inspect `git status` before proceeding; do not reset or discard them.
- No session changes have been committed or pushed. GitHub CLI was unauthenticated. Git credential manager may still permit a normal push; public `ls-remote` succeeded but does not prove write access. Never force-push.
- Root and nested Python trees coexist. Root `tfp_cli` is now the packaged CLI; the running server is `tfp-foundation-protocol/tfp_demo/server.py`. Root `setup.py` collects both trees and gives root packages precedence.
- Python 3.11 is available via `py -3.11`. Default `python` is 3.14 and produces extensive dependency warnings. `.dist_verify/runtime/Scripts/python.exe` is an existing 3.11 test environment, no longer an empty runtime-only environment.
- A preview was started at `http://127.0.0.1:8765/` before later backend edits. Check whether it is still running and restart the owned preview before demonstrating current behavior. A visible page is not evidence that its backend is current.

## What changed and should generally stay

| Change | Purpose / boundary |
| --- | --- |
| Browser UI rebuilt in `demo/index.html` and new `demo/assets/` under the nested tree | Working library, publishing, search, reading, download, draft recovery, mobile layout, actual API errors and counts. Its current framing is too narrow. |
| Device enrollment fixes in `tfp_demo/server.py` | Re-enrollment preserves identity/balance; a different secret cannot replace an existing identity. Software identity only. |
| Credit fixes in server, `tfp_client/lib/core/tfp_engine.py`, and `lib/credit/ledger.py` | Reads actually debit, partial spending preserves usable change, receipts/replay state persist, concurrent reads cannot overspend the local balance. Not a proven distributed economy. |
| Explicit demo allowance | Arbitrary demo grants are labeled as test credits and disabled outside demo mode. They do not represent computation. Demo mode still accepts legacy unsigned reads; restricted mode requires signatures. |
| Service worker rewritten | Cache shell and successful content reads; identify saved offline copies; keep balances, listings, and mutations live. |
| Retrieval authentication fix | Shard verification now uses the HMAC algorithm used by the encoder; a focused test covers real encoded content and a forged MAC. |
| Root packaging, launcher, smoke check | Include server/static assets in the wheel; launch an isolated loopback demo without external services; verify a real HTTP round trip. No fake fallback success. |
| Browser/reliability tests, CI, Docker configuration, documentation | Improve repeatability and remove unsupported readiness claims. Workflow edits and final distribution still need final validation. Docker runtime was not tested. |

Some broad lint cleanup removed unused imports/variables. No major pooled-compute, lexicon, demand-scheduling, or network subsystem was intentionally removed. Compare with HEAD if investigating a regression. Do not restore fabricated success or unsupported “production ready” claims to recover the original ambition.

## Code map: intention versus implementation

Paths below are relative to the repository root; `protocol/` in this table means `tfp-foundation-protocol/`.

| Read | What was actually observed |
| --- | --- |
| `tfp_core/compute/task_mesh.py`, `device_safety.py` | In-memory microtask coordination and scoring using supplied battery/load/trust metrics. No demonstrated live weak-device fleet or automatic sensor integration; connection to the server pool is not established. |
| `protocol/tfp_client/lib/compute/task_executor.py`; server task endpoints | Real deterministic hash-preimage, matrix-verification, and content-verification tasks. No demonstrated lexicon-building task or useful-output installation path. Expected output hashes are exposed; hash agreement alone must not be claimed as proof that useful work was performed. |
| `protocol/tfp_client/lib/lexicon/hlt/tree.py` | Hierarchical version/hash structure for shared lexicon domains and adapters; not itself a learned compression implementation. |
| `protocol/tfp_client/lib/lexicon/adapter_real.py` | Reconstruction returns the original bytes with metadata; semantic search is a placeholder. |
| `protocol/tfp_client/lib/lexicon/dict_lexicon_adapter.py` | Deterministic abbreviation expansion. This does not prove pooled lexicon efficiency and can increase text size. |
| `protocol/tfp_client/lib/publish/mesh_aggregator.py`; `protocol/tfp_broadcaster/src/gateway/scheduler.py` | Demand counting and scheduling components, including `schedule_from_aggregator`. Their presence does not demonstrate an end-to-end demand-scaled video system. Trace actual callers. |
| `protocol/tfp_broadcaster/src/ldm_semantic_mapper/__init__.py` | Maps dictionary keys to structural/enhanced groups; not a video codec or measured broadcast deployment. |
| `tfp_plugin_sdk/adapters/web_bridge.py` | Handler registration, URL parsing, and integration scaffolding. Example video handler returns placeholder bytes. |
| `tfp_core_v4/` | Separate chunking, Merkle, fountain, and node research implementation. Do not infer lexicon integration from its tests. |

Historical architecture/completion documents contain inflated or stale claims. Treat code and reproducible behavior as evidence. The README rewrite corrected some claims but now understates the mission; it also links to a **not-yet-created `docs/PROJECT_REVIEW.md`**.

## Minimal steps with the greatest impact

### 1. Finish and preserve the existing repair work

First resolve the full-suite timeout, review the credit reward path, and run the final package/browser checks. Avoid another UI rewrite or monolithic-server refactor.

- `pytest.ini` gained a global 30-second timeout during this session. The fresh 3.11 run timed out in `tests/fuzz/test_adversarial_mutation_runner_stress.py::TestAdversarialAuditRunnerStress::test_mutant_isolation_zero_disk_side_effects`, which runs five subprocess mutations. `scripts/run_adversarial_audit.py::run_mutant` has no subprocess timeout. Determine whether this is an insufficient parent budget or a stuck child; use bounded subprocess handling and an appropriate test budget. Do not suppress a real failure or count a timeout as successful mutation detection.
- Review `server.py::submit_task_result`: automatic credit issuance is not yet guarded as one operation by the same shared lock used for demo grants and read debits. Check supply, receipt, balance, retry, and concurrent-submission consistency. Add a targeted test for an actual discovered defect.
- Rebuild the final distribution after changes; install into a new empty environment and run outside the checkout. The earlier successful wheel predates some later source edits.

Done means a reproducible installation, accurate spending/restart behavior, successful browser journey, and an honestly reported complete test result. A passing unit suite does not establish network-scale claims.

### 2. Restore the intended project story with a small edit

Revise the README opening and the UI's “How it works” copy around the user's mechanism chain above. Present the notebook as a local content demonstration. Add one short status table separating **demonstrated**, **component only**, and **intended** behavior. Create the missing review document or repair the link. Reconcile misleading architecture claims without expanding the documentation jungle.

Done means a visitor understands why pooled compute, the lexicon, demand, and network integration matter, and can see which links remain unproved.

### 3. Prove one missing causal link

Choose one bounded, useful task that produces a reusable lexicon-related artifact, is verifiable, and can be consumed by another client. Reuse existing task and manifest interfaces where suitable. If choosing the artifact requires a material interpretation of the user's lexicon concept, ask one focused question before inventing an algorithm.

The smallest credible demonstration should show: a modest worker completes bounded work → an invalid result is rejected → accepted output creates a versioned shared artifact → a second client actually uses it → a baseline comparison shows benefit or honestly shows no benefit. Report setup/verification/distribution costs and what was simulated. A toy shared dictionary can be a labeled experiment, but must not be passed off as the original full lexicon design.

Do not begin with video transcoding, model training, a new consensus system, a token economy, or multiple bridge integrations. Preserve demand-scaled video and federated networks as explicit next goals. The first useful connection is more valuable than another collection of disconnected modules.

### 4. Deliver a reviewable checkpoint, then push

Document exactly what the checkpoint demonstrates and what remains experimental. Include source/assets/tests, exclude local databases, credentials, environments, and generated logs. Inspect the diff, commit coherent changes, and perform a normal push using the user's existing authorization. If authentication blocks the push, keep the local commit and report the exact obstacle. Never describe a push as completing the full research vision.

## Evidence and practical commands

Evidence already obtained (historical; rerun only where final changes require it):

- Initial baseline: 1,379 tests passed on Python 3.14, with roughly 189,000 dependency warnings. It missed the accounting defects.
- Subsequent full run: 1,388 passed, one obsolete packaging-manifest assertion failed. That assertion was updated; its containing 13-test file passed afterward. This was not a subsequent full-suite pass.
- Eleven focused reliability tests passed after the final MAC test was added. The saved `reliability-tests.log` records the earlier ten-test version.
- Eight browser check groups passed: real assets/samples, debit and refresh, draft persistence, publish failure recovery, exact UTF-8 download/inert HTML, filtering, offline/reconnect, and four views at 390px width.
- An earlier wheel installed and completed the HTTP smoke check from outside the checkout in a fresh 3.11 environment.
- Latest fresh 3.11 full run terminated on the timeout described above. No final all-green claim is justified.
- Scoped Ruff passed. A prior Bandit invocation incorrectly used `--ini` for the YAML-formatted `bandit.ini`; rerun with `-c bandit.ini` before claiming that configured check. Docker Engine was not running; no remote CI result has been obtained.

Useful commands, from repository root unless noted:

```powershell
# Existing 3.11 environment; create/reinstall if absent or stale.
.\.dist_verify\runtime\Scripts\python -m pytest tests/test_demo_reliability.py tests/test_tooling_isolation.py -q
.\.dist_verify\runtime\Scripts\python -m pytest -q --tb=short

# Uses a temporary server and shuts it down; browser package/Chromium required.
python scripts/check_demo_browser.py
python demo_30sec.py

# Build package, then pass the exact wheel path to the check.
python -m build
python scripts/check_distribution.py dist/<actual-wheel-name>.whl

# Run this using the newly installed wheel's interpreter OUTSIDE the checkout,
# with PYTHONPATH cleared, to avoid accidentally importing repository files.
python -m tfp_cli.smoke --json

# User-facing demo; restart the old preview if using its port.
python -m tfp_cli.main demo --ephemeral --no-browser --port 8765
```

Ignored local evidence: `.dist_verify/{baseline-tests,full-tests,python311-tests,browser-check,build}.log`. Screenshots: `output/playwright/`; selected showcase image: `docs/images/content-commons.png`. These local logs/environments do not transfer through Git. The eight-group browser script does not yet exercise pagination beyond six notes or every network integration.

Before reporting completion: verify current status, scoped lint, relevant/full tests, final installed-wheel smoke, browser journey, documentation links, and `git diff --check`. Report remaining limitations rather than converting test counts into claims about security, compression, weak-device usefulness, or deployment readiness.
