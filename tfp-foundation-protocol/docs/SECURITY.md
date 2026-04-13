# TFP v3.1 — Security Model & Verification Checklist

> **Second-opinion review performed 2026-04-11.**
> All claims below have been verified against live source code in
> `tfp-foundation-protocol/tfp_demo/server.py` and
> `tfp-foundation-protocol/tfp_client/lib/credit/ledger.py`.

---

## 1. Verified Security Properties

### 1.1 Device Authentication
**Claim:** Every mutating endpoint requires a valid HMAC-SHA-256 signature.
**Status:** ✅ Verified
**Evidence:** `_verify_device_sig()` in `server.py:229-240` uses `hmac.compare_digest()` for constant-time comparison, eliminating timing oracles. Unenrolled devices receive `401 Unauthorized`.

Signature message format:
- `/api/publish` — `HMAC(puf_entropy, "device_id:title")`
- `/api/earn` — `HMAC(puf_entropy, "device_id:task_id")`
- `/api/task/{id}/result` — `HMAC(puf_entropy, "device_id:task_id")`

### 1.2 Credit Replay Protection
**Claim:** Each `(device_id, task_id)` pair can only earn credits once.
**Status:** ✅ Verified
**Evidence:** `EarnLog` class (`server.py:247-283`) uses a SQLite table with `PRIMARY KEY (device_id, task_id)`. A second insert raises `IntegrityError` → HTTP 409.

### 1.3 Supply Cap Enforcement
**Claim:** Total credits minted never exceed 21,000,000.
**Status:** ✅ Verified
**Evidence:** `CreditLedger.mint()` (`ledger.py:55-70`) checks `network_total_minted + credits > MAX_SUPPLY` and raises `SupplyCapError`. `TaskStore.increment_total_minted()` holds a threading lock during the SQLite update.

### 1.4 Rate Limiting
**Claim:** Per-device sliding-window rate limits prevent DoS on earn, result-submission, and semantic search endpoints.
**Status:** ✅ Verified
**Evidence:** `_RateLimiter` (`server.py:836-864`) is a sliding-window deque. Applied to:
- `/api/earn` — default 10 calls / 60 s (env: `TFP_EARN_RATE_MAX`, `TFP_EARN_RATE_WINDOW`)
- `POST /api/task/{id}/result` — default 30 calls / 60 s (env: `TFP_RESULT_RATE_MAX`, `TFP_RESULT_RATE_WINDOW`)
- `POST /api/search/semantic` — default 20 calls / 60 s (not configurable via env in v3.2)

### 1.5 HABP Consensus — Self-Mint Prevention
**Claim:** A single device cannot mint credits by submitting 3 fake proofs.
**Status:** ✅ Verified
**Evidence:** `task_results` SQLite table has `UNIQUE(task_id, device_id)` — `INSERT OR IGNORE` means each device can submit exactly one proof per task. Consensus requires 3 **distinct** `device_id` values.

### 1.6 Request Validation
**Claim:** Inputs are validated before processing.
**Status:** ✅ Verified
**Evidence:** Pydantic models (`server.py:871-898`) enforce field bounds on all POST bodies (e.g. `puf_entropy_hex` is exactly 64 hex chars, `output_hash` is exactly 64 hex chars, `difficulty` is 1–10).

### 1.7 Content Integrity
**Claim:** Stored content is addressable by its SHA3-256 hash; retrieval validates the hash.
**Status:** ✅ Verified
**Evidence:** `ContentStore.put()` computes `root_hash = SHA3-256(content_bytes)` as the primary key. Retrieval via `/api/get/{hash}` looks up by that hash.

---

## 2. Known Limitations

The following limitations are **not vulnerabilities** in the current single-node demo configuration, but become relevant at scale or in multi-node deployments.

| # | Limitation | Impact | Mitigation |
|---|-----------|--------|-----------|
| L1 | **In-memory rate limiters** — `_RateLimiter` state is not persisted to SQLite and is not shared across process replicas. | Rate limit windows reset on server restart; horizontal scaling bypasses per-device throttling. | For multi-worker or multi-node deployments: replace `_RateLimiter` with a Redis-backed implementation (e.g. `redis-py` sorted sets). |
| L2 | **Broad exception swallowing in auto-mint** — `except Exception as exc: log.warning(...)` at `server.py:1431` catches all failures (including supply-cap errors) and continues. | A mint failure is logged but not surfaced to the caller; the `credits_earned` field in the response may be non-zero even when the credit was not actually applied to the ledger. | Narrow the catch to known exceptions (`SupplyCapError`, `ValueError`) and return an explicit `credits_applied: false` field on failure. Consider this a known gap until addressed. |
| L3 | **HABP device identity is `device_id` string only** — In the demo server, Sybil resistance rests entirely on the UNIQUE(task_id, device_id) constraint. Any caller that can register N distinct `device_id` values can form their own consensus group. | Fake consensus with N devices under attacker control. | In production: couple `device_id` to hardware PUF/TEE attestation (the `PUFEnclave` module exists; it is not yet wired into the demo server's enroll → consensus path). |
| L4 | **SQLite is not safe for `--workers > 1`** | Concurrent writes will corrupt the database under multi-worker uvicorn. | Documented in the deployment runbook. Use `--workers 1` or migrate to PostgreSQL for horizontal scaling. |

---

## 3. Security Validation Checklist

Run this checklist against every release before publishing security claims.

### A. Authentication
- [ ] `POST /api/publish` with no `X-Device-Sig` header → HTTP 401
- [ ] `POST /api/earn` with invalid signature → HTTP 401
- [ ] `POST /api/task/{id}/result` with wrong device's signature → HTTP 401
- [ ] `_verify_device_sig` uses `hmac.compare_digest` (grep: `compare_digest` must appear at least once in `server.py`)

### B. Replay Protection
- [ ] Submit same `(device_id, task_id)` to `/api/earn` twice → second call returns HTTP 409
- [ ] `EarnLog` table has `PRIMARY KEY (device_id, task_id)` constraint (grep schema in `server.py`)

### C. Rate Limiting
- [ ] Exceed `TFP_EARN_RATE_MAX` earn calls in `TFP_EARN_RATE_WINDOW` seconds → HTTP 429
- [ ] Exceed `TFP_RESULT_RATE_MAX` result submissions → HTTP 429
- [ ] Rate limiter resets correctly after window expires

### D. Supply Cap
- [ ] Minting when `network_total_minted + credits > 21_000_000` raises `SupplyCapError`
- [ ] `/api/status` reports `total_minted` and `max_supply = 21000000`
- [ ] `CreditLedger.mint()` receives `set_network_total_minted()` call before every mint

### E. HABP Consensus
- [ ] Single device submitting 3 results for the same task → only 1 recorded (UNIQUE constraint)
- [ ] Three distinct devices with matching output hashes → `verified: true`, credits minted
- [ ] Three distinct devices with different output hashes → no consensus, task stays in `verifying`
- [ ] Task proofs survive server restart (rebuilt from `task_results` table on `_rebuild_habp_from_db()`)

### F. Persistence & Restart Safety
- [ ] Publish content, restart server, content is still retrievable
- [ ] Earn credits, restart server, balance is still correct
- [ ] HABP proofs survive restart (2/3 proofs persisted → 3rd after restart reaches consensus)
- [ ] Prometheus counters seeded from SQLite on startup (not reset to 0)

### G. Input Validation
- [ ] `puf_entropy_hex` shorter than 64 chars → HTTP 422
- [ ] `output_hash` not exactly 64 chars → HTTP 422
- [ ] `difficulty` outside [1, 10] → HTTP 422
- [ ] `title` longer than 120 chars → HTTP 422

### H. Semantic Search Rate Limiting
- [ ] `POST /api/search/semantic` without valid `X-Device-Sig` → HTTP 401
- [ ] Exceed 20 semantic search calls per 60 s per device → HTTP 429
- [ ] `POST /api/search/semantic` with `TFP_ENABLE_RAG=0` → HTTP 503

### I. Reindex Admin Gate
- [ ] `POST /api/admin/rag/reindex` without valid `X-Device-Sig` → HTTP 401
- [ ] `POST /api/admin/rag/reindex` with a device not in `TFP_ADMIN_DEVICE_IDS` (when var is set) → HTTP 403
- [ ] `POST /api/admin/rag/reindex` with `TFP_ENABLE_RAG=0` → HTTP 503

### J. Nostr Gossip Replay Protection
- [ ] Kind-30078 (HLT gossip) event with `created_at` older than 300 s → silently dropped
- [ ] Kind-30079 (search-index gossip) event with `created_at` older than 300 s → silently dropped
- [ ] Kind-30080 (content announce) event with `created_at` older than 300 s → silently dropped
- [ ] Duplicate event ID (same `id` field) within replay window → processed only once
- [ ] Nostr event from pubkey not in `TFP_NOSTR_TRUSTED_PUBKEYS` (when var is set) → silently dropped

---

## 4. Maintenance Policy

### Per-release checklist
Every pull request that changes a version number, API endpoint, test suite, or security claim **must** update all of the following before merge:

1. `pyproject.toml` — `version` field
2. Root `README.md` — version badge, test-count badge, "Current Status" section
3. `tfp-foundation-protocol/docs/v3.0-integration-guide.md` — "What Changed" table, Section 16 test count
4. This file (`SECURITY.md`) — if any security property is added, changed, or a known limitation is resolved

### Stale-claim rule
Any claim of the form "X tests passing" or "security hardened" must be:
- Derived from a reproducible command (`TFP_DB_PATH=:memory: PYTHONPATH=. python -m pytest tests/ -q`)
- Updated within the same PR that changes the test suite

### In-memory rate limiter caveat
Document in all deployment guides that `_RateLimiter` is per-process and does not survive restart. Operators deploying multi-node configurations must implement a shared rate-limit store before the rate-limiting claims apply to their deployment.
