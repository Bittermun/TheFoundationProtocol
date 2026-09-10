# The Foundation Protocol (TFP): Release Scorecard & Definition of Done (DoD)

**Document Classification:** Publication-Grade Release Governance & Compliance Standard  
**Document Version:** 4.0.0-RELEASE-SCORECARD  
**Target Platform:** The Foundation Protocol (TFP) Production Releases (v3.x to v4.x Next-Gen)  
**Working Group:** Protocol Governance, Security Assurance & Release Management Working Group  
**Date of Release:** August 2026  
**Status:** Approved for Phased Protocol Certification  

---

## 1. Executive Release Governance & Definition of Done (DoD)

The Definition of Done (DoD) defines the non-negotiable quality and security criteria required before any software version of The Foundation Protocol (TFP) is tagged, packaged, and deployed to production broadcast networks or distributed mesh nodes.

A release is officially certified as **DONE** if and only if **all five core dimensions** satisfy their target metrics simultaneously:

```
+----------------------------------------------------------------------------------------------------+
|                                  THE 5 CORE RELEASE DIMENSIONS                                     |
+----------------------------------------------------------------------------------------------------+
| Dimension               | Target Objective                               | Mandatory Threshold     |
+-------------------------+------------------------------------------------+-------------------------+
| 1. Functional           | Complete un-mocked end-to-end user journeys.   | 100% E2E Flow Pass      |
| 2. Reliability          | Zero state loss across crashes and 50% loss.   | 100% Recovery & Safety  |
| 3. Security Baseline    | Zero critical/high vulnerabilities (CVSS >= 4).| 0 Security Deficits     |
| 4. Operability          | Probes, metrics, and structured logs verified. | HTTP 200 on all probes  |
| 5. Quality Discipline   | Strict linting, mypy strict, 100% pytest pass. | 0 Errors, 0 Warnings    |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Formal Release Scorecard Matrix

```
## TFP Protocol Release Readiness Scorecard

| Dimension | Mandatory Criterion | Quantitative Target Metric | Exact Verification Command | Required Status |
|---|---|---|---|:---:|
| **1. Functional Completeness** | End-to-end user journey executes without mocking (Enrollment → Task Poll → Compute → Submit → HABP 3/5 Consensus → Mint → Content Ingest → FastCDC → PQC Sign → Fountain Stream → Retrieval). | **100%** Journey Completion | `pytest tests/test_e2e_flow.py tests/test_baseline_and_integration.py` | **[PASS]** |
| **2. Reliability & Persistence** | All protocol state survives server kill (`SIGKILL`) with zero data loss (devices, credits, tasks, Prometheus counters, SQLite WAL). Bit-exact reconstruction under $\le 50\%$ packet drop. | **100%** State Recovery<br>**100%** Bit-Exact Decoding | `pytest tests/test_restart_safety.py tests/test_fountain_erasure_loss.py` | **[PASS]** |
| **3. Security Baseline** | All cryptographic invariants verified: ML-DSA/Dilithium5 PQC agility, BIP-39 root-of-trust, $O(1)$ anti-pollution seed schedule pre-filter, constant-time compares, anti-replay, 21M DWCC supply cap. | **0** Security Deficits<br>**0** CVSS $\ge 4.0$ Findings | `pytest tests/test_bip39_root_of_trust.py tests/test_deterministic_seed_schedule.py tests/test_pqc_tiered_manifest.py` | **[PASS]** |
| **4. Operability & Monitoring** | Fresh and restarted nodes pass all operational endpoints (`/health`, `/api/status`, `/metrics`, `/admin`, `/docs`). Prometheus metric export format conforms to OpenMetrics. | **100%** HTTP 200 Probes<br>Prometheus Format Valid | `curl -f http://127.0.0.1:8000/health && curl -f http://127.0.0.1:8000/metrics` | **[PASS]** |
| **5. Quality Discipline** | Strict linting, static type checking, unit/integration test suites, package build, and documentation freshness verified. | **0** Lint Warnings<br>**0** Mypy Errors<br>**100%** Test Pass Rate | `ruff check . && mypy tfp_core --strict && pytest` | **[PASS]** |
```

---

## 3. Quantitative Metric Specifications

### 3.1 Functional Completeness Metrics
- **Enrollment to Minting Roundtrip**: $\le 150\text{ ms}$ on local node.
- **FastCDC Chunking Throughput**: $\ge 120\text{ MB/s}$ on standard x86_64 / ARM64.
- **HABP 3/5 Proof Verification**: Validates 3 matching execution proofs from distinct device IDs; rejects duplicate or corrupted proofs with HTTP 400 Bad Request.

### 3.2 Reliability & Persistence Metrics
- **Data Persistence**: Zero uncommitted transactions in WAL journal upon restart.
- **Loss Tolerance**:
  - $10\%$ packet loss: $100\%$ bit-exact recovery with $\le 1.15\times$ symbol overhead.
  - $33\%$ packet loss: $100\%$ bit-exact recovery with $\le 1.55\times$ symbol overhead.
  - $50\%$ packet loss: $100\%$ bit-exact recovery with dynamic rateless swarm synthesis.

### 3.3 Security Baseline Metrics
- **Anti-Pollution Gating**: Rejects $100\%$ of forged repair droplets prior to Gaussian elimination matrix allocation ($0$ poisoned rows admitted).
- **Mnemonic Entropy**: Full validation of 12-word (128-bit) and 24-word (256-bit) BIP-39 phrases with SHA-256 bitwise checksum verification.
- **PQC Agile Fallback**: Seamless fallback to classical Ed25519 in hybrid dual-signing envelopes when PQC hardware accelerators are uninitialized.
- **Timing Invariance**: $100\%$ of MAC comparisons use `hmac.compare_digest()`.

### 3.4 Operability & Monitoring Metrics
- **`/health` Probe**: Returns `{"status": "healthy", "version": "4.x", "database": "connected"}` in $\le 5\text{ ms}$.
- **`/metrics` Prometheus Endpoint**: Emits standard counters:
  - `tfp_droplets_received_total`
  - `tfp_droplets_rejected_pollution_total`
  - `tfp_fountain_decode_success_total`
  - `tfp_habp_consensus_minted_dwcc_total`
  - `tfp_wal_checkpoints_total`

### 3.5 Quality Discipline Metrics
- **Unit Test Coverage**: Tier 1 ($\ge 5$ test cases per feature), Tier 2 ($\ge 5$ edge/boundary cases), Tier 3 (Pairwise), Tier 4 (Real-world scenarios).
- **Static Typing**: `mypy --strict` passes across all core packages with zero `# type: ignore` suppressions on cryptographic routines.
- **Formatting & Style**: Conforms $100\%$ to PEP 8 / `ruff` formatting rules.

---

## 4. Release Sign-off Protocol & Governance Checklist

Before generating release tags or deploying protocol binaries:

1. **Lead Security Architect Sign-off**: Cryptographic inventory certified, zero PQC stubs, anti-pollution pre-validation verified.
2. **Transport Systems Engineer Sign-off**: 50% packet erasure resilience verified, SIMD vectorization benchmarks met.
3. **Database & Infrastructure Sign-off**: Concurrency tests pass with 0 SQLite lock timeouts, WAL checkpointing verified.
4. **Release Manager Sign-off**: All 5 scorecard dimensions display **[PASS]**, all 6 CI jobs green.

```
===================================================================================================
RELEASE VERIFICATION ATTESTATION:
Version: 4.0.0-RELEASE
Architecture Documentation: VERIFIED (docs/architecture/*)
Audit & Quality Gates: VERIFIED (docs/audit/*)
Phase 1 Core Primitives: IMPLEMENTED & TESTED (100% Pytest Pass)
Release Status: APPROVED FOR DEPLOYMENT
===================================================================================================
```

---
*Authored by the Protocol Architecture & Audit Working Group.*
