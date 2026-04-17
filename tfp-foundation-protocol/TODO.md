# TFP v3.1 — Improvement Areas & TODO

> This document tracks specific improvement areas identified during code review.
> Items are prioritized by impact and effort. Pull requests welcome.

---

## High Priority (Security Hardening)

### [SEC-001] Chunk Upload Size Limit
**Location:** `tfp_demo/server.py` — `_ongoing_uploads` dict
**Issue:** No max bytes per upload_id enforced. Malicious client could upload many large chunks without completing, causing OOM.
**Solution:** Add configurable `TFP_MAX_UPLOAD_BYTES` environment variable. Reject chunks exceeding this limit. Track total bytes per upload_id in `_ongoing_uploads`.
**Effort:** Low
**Impact:** Medium (DoS prevention)

### [SEC-002] Path Traversal Helper Refactor
**Location:** `tfp_demo/server.py` — `BlobStore` class
**Issue:** Path traversal validation logic duplicated across `get()`, `exists()`, `get_size()`, `open_stream()`.
**Solution:** Extract to shared `_validate_path()` method. Add unit tests for path traversal edge cases.
**Effort:** Low
**Impact:** Low (maintainability)

### [SEC-003] Rate Limiter Failure Mode
**Location:** `tfp_demo/server.py` — Redis rate limiter initialization
**Issue:** If Redis configured but unavailable, system silently degrades to in-memory rate limiting. No alerting.
**Solution:** Add configuration option `TFP_REDIS_REQUIRED` to fail fast if Redis is unavailable. Add health check endpoint.
**Effort:** Low
**Impact:** Medium (multi-worker deployments)

---

## Medium Priority (Architecture)

### [ARCH-001] Dual-Lock Pattern Documentation
**Location:** `tfp_demo/server.py` — `TaskStore.submit_result()`
**Issue:** Dual-lock pattern (db_lock + _lock) works but lock ordering is not formally documented.
**Solution:** Add comprehensive docstring explaining lock ordering rationale. Add comment at top of file with lock hierarchy rules.
**Effort:** Low
**Impact:** Low (future-proofing)

### [ARCH-002] State Machine Externalization
**Location:** `tfp_demo/server.py` — `_VALID_TRANSITIONS` dict
**Issue:** Hardcoded state transitions. No way to extend without code modification. Validation outside transaction in some paths.
**Solution:** Consider using a state machine library (e.g., `transitions`) or move validation into database triggers.
**Effort:** Medium
**Impact:** Medium (correctness)

### [ARCH-003] SQLite WAL Checkpointing
**Location:** `tfp_demo/database.py` — `_init_sqlite()`
**Issue:** WAL mode enabled but no periodic checkpointing. WAL file could grow unbounded in high-write scenarios.
**Solution:** Add periodic `PRAGMA wal_checkpoint` in maintenance background task. Add WAL file size monitoring to metrics.
**Effort:** Low
**Impact:** Low (disk space)

---

## Medium Priority (Database)

### [DB-001] PostgreSQL Store Refactoring
**Location:** All store classes in `tfp_demo/server.py`
**Issue:** Database abstraction supports PostgreSQL, but stores use SQLite-specific SQL (`sqlite_master`, `PRAGMA`, `INSERT OR REPLACE`, `rowid`).
**Solution:** Refactor stores to use database-agnostic SQL. Replace `INSERT OR REPLACE` with upsert patterns. Replace `rowid` with auto-increment primary keys. Remove `PRAGMA` usage.
**Effort:** High
**Impact:** High (multi-database support)

### [DB-002] Schema Migration Script
**Location:** `tfp_demo/server.py` — `ContentStore._migrate_from_blob_schema()`
**Issue:** Auto-migration happens at runtime. If migration fails mid-way, database could be inconsistent.
**Solution:** Extract migration to separate script that can be run manually. Add pre-migration backup step. Add migration rollback capability.
**Effort:** Medium
**Impact:** Medium (deployment safety)

---

## Low Priority (Performance & Features)

### [PERF-001] Native Crypto Library for Nostr
**Location:** `tfp_client/lib/bridges/nostr_bridge.py` — `_schnorr_sign()`
**Issue:** Pure-Python secp256k1 implementation is slower than native libraries. Nonce derivation uses SHA-256 instead of RFC 6979.
**Solution:** Replace with `coincurve` or `secp256k1` library. Add feature flag to allow dependency-free mode.
**Effort:** Low
**Impact:** Low (performance, cryptographic hygiene)

### [PERF-002] Task Result Persistence
**Location:** `tfp_demo/server.py` — task result handling
**Issue:** Only `output_hash` is persisted, not actual result data. Cannot retrieve original task outputs.
**Solution:** Add optional `task_results_payload` table with TTL-based cleanup. Make configurable via `TFP_PERSIST_TASK_RESULTS`.
**Effort:** Medium
**Impact:** Low (feature)

### [PERF-003] RAG Drift Remediation
**Location:** `tfp_demo/server.py` — `_handle_search_index_gossip()`
**Issue:** RAG index drift detection only logs warnings. No automatic remediation.
**Solution:** Add automatic reindex trigger when drift exceeds threshold. Make configurable via `TFP_AUTO_REINDEX_ON_DRIFT`.
**Effort:** Medium
**Impact:** Low (operations)

---

## Low Priority (Code Quality)

### [CODE-001] Clock Skew Symmetry
**Location:** `tfp_demo/server.py` — deadline checking
**Issue:** Clock skew tolerance added to deadline asymmetrically (reap adds tolerance, submit adds tolerance, but no subtract for device clocks).
**Solution:** Document current behavior. Consider symmetric tolerance or device clock sync recommendations.
**Effort:** Low
**Impact:** Low (edge case behavior)

### [CODE-002] HABP Split-Brain Handling
**Location:** `tfp_client/lib/compute/verify_habp.py`
**Issue:** Not fully visible from code review: what happens if 2 devices submit proof A and 2 submit proof B, both reaching 3/5 threshold with different outputs?
**Solution:** Document consensus resolution logic. Add test for split-brain scenario.
**Effort:** Low
**Impact:** Low (correctness documentation)

### [CODE-003] Metrics Seeding Error Handling
**Location:** `tfp_demo/server.py` — `_Metrics.seed_from_db()`
**Issue:** If seeding fails, logs warning but continues with zero counters. Metrics may be incorrect until next increment.
**Solution:** Consider failing startup if critical metrics cannot be seeded. Add health check for metrics consistency.
**Effort:** Low
**Impact:** Low (observability)

---

## Future Work (Post-Open Source)

These items are not current TODOs but areas for future exploration based on community feedback:

- **Distributed HABP consensus:** Move from SQLite-rebuilt HABP to distributed consensus (e.g., libp2p GossipSub) for multi-node deployments
- **Multi-region deployment:** Add support for geographically distributed nodes with region-aware content routing
- **Enhanced PUF integration:** Wire PUFEnclave module into enroll → consensus path for stronger Sybil resistance
- **Streaming protocol improvements:** Add adaptive bitrate, DASH/HLS support for media streaming
- **Zero-knowledge compute:** Extend ZKP adapter to support more complex compute tasks beyond current hash preimage and matrix verification
- **Mobile client optimization:** Optimize for mobile devices with limited bandwidth and compute
- **Content licensing integration:** Add support for creative commons and other licensing models
- **Analytics dashboard:** Expand admin dashboard with historical trends, performance metrics, and anomaly detection

---

## Contribution Guidelines

When addressing items from this TODO:

1. Reference the TODO ID in commit messages (e.g., "SEC-001: Add chunk upload size limit")
2. Add tests for new functionality
3. Update relevant documentation (SECURITY.md, KNOWN_LIMITATIONS.md, README.md)
4. Update this TODO file when items are completed (move to COMPLETED section or remove)

---

## Completed Items

*(None yet - this is a new document)*
