# TFP v3.1 — Known Technical Limitations

> This document catalogs non-security limitations in the current implementation.
> For security-related limitations, see [SECURITY.md](SECURITY.md).

---

## Overview

The Foundation Protocol demo server is designed for single-node deployments with a focus on correctness and restart safety. The following limitations are **not bugs** but design choices or areas identified for future improvement. They do not prevent open-sourcing or production use in the intended deployment model, but may require attention at scale or in specific configurations.

---

## Architecture & Design Patterns

### L1: In-Memory State Rebuild Pattern
**Description:** Many components (metrics, HABP proofs, rate limiters) are in-memory by design but explicitly rebuild state from SQLite on restart. This is intentional: the system uses ephemeral in-memory structures for performance while ensuring durability through database reconstruction.

**Impact:** In-memory caches reset on restart, but functional state is preserved. Metrics counters are re-seeded from SQL aggregates; HABP consensus rebuilds from `task_results` table.

**Mitigation:** This is a working design, not a bug. For multi-node deployments where state sharing is required, use Redis-backed rate limiters and consider distributed consensus for HABP.

---

### L2: Dual-Lock Pattern in TaskStore
**Description:** `TaskStore` uses two nested locks (`_db_lock` for SQLite, `_lock` for HABP state) to prevent self-mint attacks and race conditions. Lock ordering is enforced (db_lock first, then _lock).

**Impact:** The dual-lock pattern works correctly in the current codebase because lock ordering is consistent. However, if future code paths take locks in reverse order, deadlock could occur.

**Mitigation:** Document lock ordering in code comments. Consider refactoring to a single lock or using a lock hierarchy. Current implementation is functional.

---

### L3: Rate Limiter Fallback Chain
**Description:** Rate limiting has three tiers: Redis-backed (distributed), in-memory (per-process), or no limiting (if both fail). If Redis is configured but temporarily unavailable, the system silently degrades to in-memory rate limiting.

**Impact:** In multi-worker deployments with Redis configured, temporary Redis outages cause rate limit state to become per-process instead of distributed. This could allow burst attacks across workers until Redis recovers.

**Mitigation:** Monitor Redis connectivity. For critical deployments, consider failing fast if Redis is required but unavailable. Current graceful degradation is intentional for resilience.

---

## Data Storage & Persistence

### L4: SQLite WAL Mode No Checkpointing
**Description:** WAL mode is enabled for SQLite to improve concurrent read performance, but there is no periodic `PRAGMA wal_checkpoint` or WAL file size monitoring.

**Impact:** In high-write scenarios, the WAL file could grow unbounded until process restart. This is not a data corruption risk (SQLite handles this), but could consume disk space.

**Mitigation:** Add periodic checkpointing in maintenance tasks or monitor WAL file size. Not critical for typical demo deployments.

---

### L5: ContentStore Auto Schema Migration
**Description:** ContentStore detects legacy schema (when `blob_path` column is missing) and auto-migrates by creating a new table, moving BLOB data to BlobStore, dropping the old table, and renaming the new one.

**Impact:** Migration happens at runtime on first access. If migration fails mid-way (e.g., disk full), the database could be left in an inconsistent state, though SQLite transactions should provide rollback.

**Mitigation:** Backup database before major version upgrades. Consider adding a manual migration script for production deployments.

---

### L6: Task Result Data Not Persisted
**Description:** Task results store `output_hash` (hex string) but the actual output data is not persisted—only the hash is stored. For large compute tasks, the original result data is lost; only verification metadata remains.

**Impact:** Cannot retrieve original task outputs after completion. This is by design for the demo server (focus on verification, not result storage).

**Mitigation:** If task result persistence is needed, add a separate table for result payloads with TTL-based cleanup.

---

## Code Quality & Maintainability

### L7: Path Traversal Protection Duplication
**Description:** BlobStore's path traversal validation logic is duplicated across `get()`, `exists()`, `get_size()`, and `open_stream()` methods instead of using a shared helper function.

**Impact:** Maintenance risk—if validation rules change, all four methods must be updated consistently. Current implementation is correct.

**Mitigation:** Refactor to a shared `_validate_path()` method. Not urgent but recommended for maintainability.

---

### L8: Task State Machine Validation Brittleness
**Description:** Task state transitions are validated using a hardcoded `_VALID_TRANSITIONS` dict. Validation is called before DB updates but outside the SQL transaction in some paths, creating a potential TOCTOU (time-of-check to time-of-use) race condition.

**Impact:** In theory, the DB could change between validation and update. In practice, the dual-lock pattern in TaskStore serializes access, making this unlikely.

**Mitigation:** Move state validation inside the transaction or use database-level triggers. Current implementation is functional.

---

### L9: Clock Skew Tolerance Asymmetry
**Description:** Clock skew tolerance is added to the deadline when reaping expired tasks and checking submissions, but not subtracted when devices submit results. This creates asymmetry: devices with fast clocks see deadlines as passed earlier than the server.

**Impact:** Devices with clocks ahead of server time may submit results that the server rejects as "deadline passed," even though the device sees the task as still open.

**Mitigation:** Document this behavior. Consider symmetric tolerance or device clock synchronization recommendations. Current design favors server time as source of truth.

---

## Deployment Considerations

### L10: Nostr Bridge Pure-Python Crypto
**Description:** The Nostr bridge implements secp256k1 elliptic curve math from scratch in pure Python instead of using a crypto library (e.g., `cryptography`, `coincurve`).

**Impact:** Slower signature operations compared to native libraries. The nonce derivation uses SHA-256 instead of RFC 6979 (HMAC-SHA-256), which is safe for this use case but not cryptographically optimal for high-value assets.

**Mitigation:** For high-value production deployments, replace with a native crypto library. Current implementation is functional and dependency-free.

---

### L11: RAG Graph Drift Detection is Observability-Only
**Description:** The code receives search index gossip from peers and compares chunk counts to detect RAG index drift, but does not automatically reconcile differences—only logs warnings.

**Impact:** Operators must manually trigger reindex when drift is detected. No automatic remediation.

**Mitigation:** This is intentional to avoid automatic data loss. Document reindex procedures in operations guide.

---

## Future Work Areas

The following areas are identified for potential improvement but are not current limitations:

- **Chunk upload size limits:** Add configurable max bytes per upload_id to prevent OOM from malicious clients (hardening)
- **PostgreSQL store refactoring:** Complete database-agnostic SQL implementation for true multi-database support
- **Distributed HABP consensus:** Move from SQLite-rebuilt HABP to a distributed consensus mechanism for multi-node deployments
- **State machine externalization:** Move task state transitions to a configurable state machine library
- **Lock hierarchy formalization:** Document and enforce lock ordering rules to prevent future deadlocks

---

## Summary

None of the limitations above are blockers for open-sourcing or production deployment in the intended single-node model. They represent areas where the current implementation prioritizes simplicity and correctness over scalability or hardening. Future versions may address these based on deployment needs and community feedback.
