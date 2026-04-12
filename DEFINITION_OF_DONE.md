# TFP — Definition of Done

> **Version:** 1.0 (April 2026)
> **Status:** Active — all PRs and releases are measured against this document.

---

## North Star

TFP is production-operable as a decentralized content and verifiable compute protocol with secure credit economics, documented APIs, and reproducible quality gates.

---

## End Goals

Five named goals define when the project has arrived at its north star. **All five must be ✅ simultaneously** before a release is considered done.

### 1 — Functional Completeness

The core user journey works end-to-end without manual intervention:

```
enroll device
  → poll open tasks
  → execute task locally (HASH_PREIMAGE / MATRIX_VERIFY / CONTENT_VERIFY)
  → submit result via POST /api/task/{id}/result
  → HABP consensus reached (3 distinct devices, identical output hash)
  → credits minted to all participating devices
  → credits spent via GET /api/get/{hash}
  → content returned
```

**Done when:** The automated E2E test (`tests/test_e2e_flow.py`) exercises every step above and passes without mocking the consensus path.

---

### 2 — Reliability / Persistence

State survives a server restart with zero data loss:

- Open and completed tasks, HABP proofs, device enrollments, credit chains, and supply total are all reconstructed from SQLite on startup.
- Prometheus counters at `/metrics` reflect persisted history, not just the current process lifetime.
- Background maintenance (reaper + pool replenishment) restarts automatically with the process.

**Done when:** `tests/test_restart_safety.py` starts the server, populates state, kills and restarts the process, and asserts all values match.

---

### 3 — Security Baseline

Every verified security property in `tfp-foundation-protocol/docs/SECURITY.md` passes its corresponding test:

| Property | Test file |
|---|---|
| Mutating endpoints require `X-Device-Sig` (HMAC-SHA-256) | `tests/test_device_auth.py` |
| Constant-time signature comparison (no timing oracle) | `tests/test_device_auth.py` |
| Credit replay prevented (UNIQUE device+task in `EarnLog`) | `tests/test_credit_replay.py` |
| Self-mint blocked (UNIQUE device+task in `task_results`) | `tests/test_habp_consensus.py` |
| Supply cap enforced (`SupplyCapError` at 21 M) | `tests/test_supply_cap.py` |
| Rate limiting active on earn and result endpoints | `tests/test_rate_limiting.py` |
| Input validation rejects out-of-bounds fields | `tests/test_input_validation.py` |
| Secret scan passes (no credentials in version control) | CI `security.yml` job |

**Done when:** All tests listed above pass and the secret-scan job in `.github/workflows/security.yml` is green.

---

### 4 — Operability

A freshly deployed node and a restarted node both expose fully functional operational surfaces:

| Surface | Endpoint / command | Expected behaviour |
|---|---|---|
| Liveness | `GET /health` | `{"status": "ok"}` |
| Node status | `GET /api/status` | JSON with supply, task count, device count |
| Prometheus metrics | `GET /metrics` | Text exposition format, ≥ 12 named counters |
| Admin dashboard | `GET /admin` | HTML page with supply bar and device leaderboard |
| API explorer | `GET /docs` | OpenAPI Swagger UI |
| CLI pool join | `tfp join --device-id x` | Enrolls, polls tasks, executes, submits result |
| CLI inspect | `tfp tasks` / `tfp leaderboard` | Returns non-empty JSON/table output |
| Docker | `docker compose up --build` | All above surfaces reachable on `localhost:8000` |

**Done when:** The deployment smoke-test script (`scripts/smoke_test.sh`) exits 0 against both a fresh node and a restarted node.

---

### 5 — Quality Discipline

Every commit and PR satisfies the full quality gate:

| Gate | Tool / command | Requirement |
|---|---|---|
| Lint | `ruff check .` | Zero violations |
| Security scan | `bandit -r tfp-foundation-protocol -lll` | Zero medium/high issues |
| Type check | `mypy tfp-foundation-protocol --ignore-missing-imports` | Zero errors |
| Tests | `cd tfp-foundation-protocol && TFP_DB_PATH=:memory: PYTHONPATH=. python -m pytest tests/ -q` | All tests pass, 0 failures |
| Build | `pip install -e tfp-foundation-protocol[all]` | Exits 0 |
| README badge | CI `Docs freshness` step | Badge count == actual test count |

TDD workflow is enforced: new features require a test written before the implementation; bugs require a failing test reproducing the bug before the fix is written (Prove-It pattern).

**Done when:** The CI workflow (`.github/workflows/ci.yml`) is green on the release branch with all six gates above passing.

---

## Hard Acceptance Criteria

Each end goal maps to one or more concrete, falsifiable criteria. A criterion is **binary**: it either passes or it does not.

### CI proof
Every PR targeting `main` must pass all jobs in `.github/workflows/ci.yml` and `.github/workflows/security.yml` with no required checks skipped or bypassed. Any red job blocks the merge.

### Test proof
`cd tfp-foundation-protocol && TFP_DB_PATH=:memory: PYTHONPATH=. python -m pytest tests/ -q` must exit 0 with no failures and no skipped tests (excluding explicitly marked `xfail`). Run after every change. For bugs, the test must exist and fail *before* the fix is written, then pass *after*.

### Behavior proof
`scripts/smoke_test.sh` exercises the complete task lifecycle (create → execute × 3 → consensus → credit mint → content retrieve) against a running node and asserts each step succeeds. Must pass after both fresh start and restart.

### Security proof
All tests in `tests/test_device_auth.py`, `tests/test_credit_replay.py`, `tests/test_habp_consensus.py`, `tests/test_supply_cap.py`, `tests/test_rate_limiting.py`, and `tests/test_input_validation.py` pass. The secret-scan CI job reports no findings.

### Ops proof
`scripts/smoke_test.sh --ops-only` hits every endpoint in the Operability table above and asserts HTTP 200 (or the expected status) for each. Must pass on a cold-start node and again after `SIGTERM` + restart with the same data volume.

### Documentation proof
Every endpoint listed in the API table in `README.md` exists in the running server. The startup commands in `README.md` Quick Start and `tfp-foundation-protocol/docs/v3.0-integration-guide.md` Section 3 execute without error. The test-count badge in `README.md` matches the actual collected test count (enforced by the CI `Docs freshness` step).

---

## Release Definition of Done

A version is **released** only when **all** of the following are true simultaneously on the release branch:

- [ ] **Functional** — E2E flow test (`tests/test_e2e_flow.py`) passes.
- [ ] **Reliability** — Restart-safety test (`tests/test_restart_safety.py`) passes.
- [ ] **Security** — All security tests pass; secret-scan CI job is green; `SECURITY.md` accurately reflects the live implementation.
- [ ] **Operability** — `scripts/smoke_test.sh` exits 0 on fresh start and after restart.
- [ ] **Quality** — All CI jobs (lint, type check, tests, build, docs freshness, security scan) are green; README badge matches actual test count; no skipped required checks.

Any single ❌ means the release is **not done**, regardless of how many features are complete.

---

## Release Scorecard

Copy this checklist into every release PR. Check each item only when the corresponding CI job or automated test passes — not based on manual inspection.

```
## Release Readiness Scorecard

| Goal            | Criterion                                      | Status |
|-----------------|------------------------------------------------|--------|
| Functional      | tests/test_e2e_flow.py passes                  | [ ]    |
| Reliability     | tests/test_restart_safety.py passes            | [ ]    |
| Security        | Security tests + secret-scan CI job green      | [ ]    |
| Operability     | scripts/smoke_test.sh exits 0 (fresh+restart)  | [ ]    |
| Quality         | All CI gates green, badge matches test count   | [ ]    |

**Release gate:** all five rows must show ✅ before merging to main.
```

---

## Maintenance

This document is version-controlled alongside the code. Any change to an API endpoint, test file path, CI job name, or startup command that is referenced here must be accompanied by an update to this file in the same PR. The Documentation proof criterion is considered failed if this document diverges from the running system.
