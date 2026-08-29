# The Foundation Protocol (TFP): Autonomous Roadmap & Architectural Add-ons Specification

**Document Classification:** Publication-Grade Architectural Specification & Strategic Engineering Roadmap  
**Document Version:** 4.0.0-PROD-SPEC  
**Target Platform:** The Foundation Protocol (TFP) v3.x Legacy to v4.x Next-Gen  
**Security & Architecture Working Group:** Protocol Engineering, Security Research, & Systems Architecture Teams  
**Date of Release:** August 2026  
**Status:** Approved for Autonomous Phased Implementation  

---

## 1. Executive Strategic Vision & Architecture Roadmap

### 1.1 Strategic Mission & Evolution Vision

The Foundation Protocol (TFP) is an autonomous, post-quantum-resilient content routing, rateless erasure-coded broadcast, and decentralized edge-compute protocol. TFP is engineered to provide uninterrupted global information dissemination, zero-trust data verification, and verifiable edge computation across extreme network topographies—spanning low-earth-orbit (LEO) satellite constellations, terrestrial broadcast spectrum (ATSC 3.0, DVB-T2, 5G MBSFN), ad-hoc mesh radios, intermittent local area networks, and adversarial peer-to-peer (P2P) swarms.

To transition TFP from an advanced research prototype to an enterprise-grade, mission-critical decentralized infrastructure, this document establishes the definitive **Autonomous Execution Roadmap** and **Code Add-ons Architectural Blueprint**.

```
+-----------------------------------------------------------------------------------------------------------------------+
|                                        THE FOUNDATION PROTOCOL EVOLUTION MATRIX                                       |
+-----------------------------------------------------------------------------------------------------------------------+
|  CAPABILITY                     | PROTOCOL V3.1 / V3.2 (CURRENT)        | PROTOCOL V4.0 / V4.1 (TARGET ARCHITECTURE)   |
+---------------------------------+---------------------------------------+---------------------------------------------+
|  Cryptographic Agility          | Mixed classical/PQC with test stubs   | Full PQC (ML-KEM/Kyber, ML-DSA/Dilithium)   |
|                                 | and unauthenticated suite broadcast.  | Dual-signing hybrid, authenticated state.   |
+---------------------------------+---------------------------------------+---------------------------------------------+
|  Erasure Coding & Transport     | Pure-Python GF(2) or static Rust FFI  | SIMD-accelerated GF(2) (AVX-512/NEON),     |
|                                 | prone to single-shard DoS and rank    | streaming rateless droplet synthesis        |
|                                 | starvation under loss.                | ($seed \in [K, \infty)$), robust filtering. |
+---------------------------------+---------------------------------------+---------------------------------------------+
|  Server Architecture            | 4,500-line monolithic God Module      | Layered micro-services (`tfp_server/*`),    |
|                                 | with SQLite lock contention.          | async connection pooling, isolated WAL.     |
+---------------------------------+---------------------------------------+---------------------------------------------+
|  Developer SDK Experience       | Raw HTTP requests or internal imports | Unified, typed `tfp-sdk` (sync & async)     |
|                                 | with fragmented implementations.      | with connection pooling and auto-failover.  |
+---------------------------------+---------------------------------------+---------------------------------------------+
|  Plugin Runtime & Extensibility | Ad-hoc unshielded class loading       | Capability-gated WASM/gRPC sandbox runtime  |
|                                 | without syscall or memory isolation.  | (`tfp_plugin_engine`) with strict quotas.   |
+---------------------------------+---------------------------------------+---------------------------------------------+
|  Identity & Root of Trust       | Software-simulated PUF (`os.urandom`) | Hardware-backed HSM/TPM 2.0/Secure Enclave  |
|                                 | and weak 60-bit mnemonic seeds.       | provider with BIP-39 (128-256 bit) entropy. |
+-----------------------------------------------------------------------------------------------------------------------+
```

---

### 1.2 Phased Strategic Execution Timeline

The roadmap is organized into four sequential, mutually reinforcing phases. Each phase establishes strict architectural invariants and operational readiness gates before subsequent phases initiate.

```
2026 Q3                                                                                             2027 Q2
[================== PHASE 1 ==================>]
(Critical Security & Mathematical Hardening)
          [================== PHASE 2 ==================>]
          (Transport, Erasure & Resilience Hardening)
                    [================== PHASE 3 ==================>]
                    (Monolith Decomposition & Code Quality)
                              [================== PHASE 4 ==================>]
                              (Production SDK & Architectural Add-ons)
```

```
+-----------------------------------------------------------------------------------------------------------------------+
| PHASE 1: CRITICAL SECURITY & MATHEMATICAL HARDENING (Sprint 1 - 4 | 4 Weeks)                                         |
+-----------------------------------------------------------------------------------------------------------------------+
| Objectives:                                                                                                           |
| 1. Eliminate all P0 critical vulnerabilities and signature bypass vulnerabilities across the core protocol.          |
| 2. Mathematically correct the Shannon entropy calculations and structural payload inspection engines.                |
| 3. Enforce cryptographic integrity across mutualistic defense gossip and cryptographic agility negotiation.            |
| Key Deliverables:                                                                                                     |
| - Verified fix for Behavioral Engine magic byte scanning (CRIT-01).                                                   |
| - True Shannon entropy formula ($H(X) = -\sum p \log_2 p$) in Mutualistic Defense (CRIT-02).                         |
| - Asymmetric signature enforcement (Ed25519/Dilithium5) on all HeuristicPack and Gossip signals (CRIT-03).           |
| - Eradication of stub signature bypasses with production fallback to classical Ed25519 (CRIT-04).                    |
| - Signed suite broadcast imports authenticated against Governance Manifest (HIGH-06).                                |
+-----------------------------------------------------------------------------------------------------------------------+
| PHASE 2: TRANSPORT, ERASURE & RESILIENCE HARDENING (Sprint 5 - 8 | 4 Weeks)                                          |
+-----------------------------------------------------------------------------------------------------------------------+
| Objectives:                                                                                                           |
| 1. Harden broadcast, multicast, and mesh transport layers against Denial of Service and poisoning attacks.           |
| 2. Eliminate rank starvation in lossy swarms through dynamic rateless droplet synthesis.                             |
| 3. Prevent economic credit minting exploits, spent-receipt double spending, and simulation crashes.                   |
| Key Deliverables:                                                                                                     |
| - Fault-tolerant RaptorQ shard filtering that drops corrupted HMAC tags without aborting decoding (HIGH-01).         |
| - Cryptographic spend nullifiers and hash-chain transaction journaling in CreditLedger (HIGH-02).                     |
| - HABP verifiable execution proof gating on `/api/earn` endpoint (HIGH-03).                                           |
| - Industry-standard BIP-39 mnemonic seed generation with PBKDF2-HMAC-SHA512 (HIGH-04).                               |
| - Localized random-target crash injection in Chaos Orchestrator (HIGH-05).                                           |
| - Dynamic rateless droplet generation ($seed \in [K, \infty)$) in Mesh Swarm (MED-05).                              |
| - Deterministic ATSC 3.0 spectrum encapsulation with millisecond timestamp modulo bitmasking (MED-02).               |
+-----------------------------------------------------------------------------------------------------------------------+
| PHASE 3: MONOLITH DECOMPOSITION & CODE QUALITY (Sprint 9 - 14 | 6 Weeks)                                             |
+-----------------------------------------------------------------------------------------------------------------------+
| Objectives:                                                                                                           |
| 1. Decompose the 4,500-line `tfp_demo/server.py` monolith into cleanly isolated modular services (`tfp_server/*`).   |
| 2. Eliminate 223+ static type errors and enforce strict Mypy compliance repository-wide.                             |
| 3. Implement RFC 6962 domain separation across all Merkle tree implementations.                                       |
| 4. Wire orphaned compliance, privacy, and transport modules into active protocol execution paths.                   |
| Key Deliverables:                                                                                                     |
| - Modular `tfp_server` package: `storage/`, `consensus/`, `api/`, `bridges/`, `observability/` (LOW-01).             |
| - Clean `mypy --strict` compliance across root and inner packages (LOW-02).                                          |
| - RFC 6962 leaf (`\x00`) and node (`\x01`) domain separation in Merkle trees (MED-09).                              |
| - Integration of `MetadataShield`, `SpectrumEncapsulator`, and `TaskMeshGates` into core daemon (LOW-03).             |
| - Unified packaging with standardized `__init__.py` exports and cleanup of empty placeholder packages (MED-08, LOW-08).|
+-----------------------------------------------------------------------------------------------------------------------+
| PHASE 4: PRODUCTION SDK & ARCHITECTURAL ADD-ONS (Sprint 15 - 22 | 8 Weeks)                                           |
+-----------------------------------------------------------------------------------------------------------------------+
| Objectives:                                                                                                           |
| 1. Deliver the unified `tfp-sdk` Python client with typed async/sync interfaces and automatic failover.               |
| 2. Implement the Sandboxed Plugin Runtime (`tfp_plugin_engine`) with WebAssembly/gRPC capability security.           |
| 3. Deploy the SIMD-accelerated High-Throughput Erasure & Acceleration Engine.                                        |
| 4. Provide the Hardware Security Module (HSM/TPM/Secure Enclave) provider for hardware-rooted identity.              |
| Key Deliverables:                                                                                                     |
| - Extension 1: Complete `tfp-sdk` distribution package with connection pooling and PQC crypto agility.                |
| - Extension 2: Production-hardened `tfp_server` microservice architecture with SQLite WAL isolation.                  |
| - Extension 3: `tfp_plugin_engine` with Wasmtime host bindings, capability gates, and event hooks.                   |
| - Extension 4: Vectorized SIMD GF(2) linear algebra engine and memory-mapped shared buffer pipeline.                 |
| - Extension 5: Pluggable PKCS#11, TPM 2.0, and Apple Secure Enclave adapters.                                        |
+-----------------------------------------------------------------------------------------------------------------------+
```

---

### 1.3 Key Performance Indicators & Readiness Gates

To ensure objective evaluation, every phase requires meeting specific, mathematically verifiable Readiness Gates before graduation:

```
+-----------------------------------------------------------------------------------------------------------------------+
| DOMAIN                     | BASELINE (CURRENT)                     | TARGET KPI (PHASE 4 GRADUATION)                 |
+----------------------------+----------------------------------------+-------------------------------------------------+
| RaptorQ Decode Speed       | 1,592 MB/s (C-FFI) / 0.8 MB/s (Python) | >= 2,000 MB/s (SIMD FFI) / >= 25 MB/s (Python)  |
| Loss Tolerance Threshold   | Fails at >33% loss (rank starvation)   | 100% reconstruction at 50% packet loss           |
| Static Type Deficits       | 223+ mypy errors (suppressed)          | 0 mypy errors under strict mode repository-wide |
| Unit & Integration Tests   | 993 tests (fragmented discovery)       | >= 1,350 tests with 100% automated CI pass      |
| Code Modularity Metric     | 1 God Module (4,500+ LOC in server.py) | Max module size < 500 LOC; clean DI architecture|
| Signature Verification     | Stubs permitted; pseudo-hashes allowed | 100% cryptographically bound (Dilithium/Ed25519)|
| False Positive Rate        | 100% false positive on media/text      | 0.0% false positive on valid media/documents    |
| Memory Pickling Overhead   | 1.0 GB per 50MB file encode            | Zero-copy shared memory (< 60 MB peak RAM)      |
+-----------------------------------------------------------------------------------------------------------------------+
```

---

### 1.4 Comprehensive Risk Matrix & Mitigation Strategies

```
+-----------------------------------------------------------------------------------------------------------------------+
| RISK IDENTIFICATION               | SEVERITY | LIKELIHOOD | MITIGATION STRATEGY                                      |
+-----------------------------------+----------+------------+----------------------------------------------------------+
| R-01: PQC Library Unavailability  | HIGH     | HIGH       | Dynamic crypto agility engine falls back to standard     |
| (liboqs / pqcrypto missing on OS) |          |            | Ed25519/ECDSA cryptography; never accept mock stubs.     |
+-----------------------------------+----------+------------+----------------------------------------------------------+
| R-02: SQLite WAL Lock Contention  | HIGH     | MEDIUM     | Decompose server into isolated service workers; route    |
| under high concurrent writes      |          |            | write transactions through dedicated queue with retries. |
+-----------------------------------+----------+------------+----------------------------------------------------------+
| R-03: Breaking Wire-Format Format | HIGH     | MEDIUM     | Versioned protocol headers (v3.2 vs v4.0); dual-reader   |
| in Swarm Merkle & Droplet Specs   |          |            | compatibility during transitional migration phase.       |
+-----------------------------------+----------+------------+----------------------------------------------------------+
| R-04: WASM Host Call Overhead     | MEDIUM   | MEDIUM     | Batch memory-mapped event delivery; restrict WASM hooks  |
| on High-Throughput Packet Paths   |          |            | to content lifecycle and access control boundaries.      |
+-----------------------------------+----------+------------+----------------------------------------------------------+
| R-05: Hardware HSM Portability    | MEDIUM   | HIGH       | Abstract provider interface (`HardwareEnclaveProvider`)  |
| across diverse OS environments    |          |            | with software-encrypted AES-256 fallback for dev setups. |
+-----------------------------------------------------------------------------------------------------------------------+
```

---

## 2. Categorized and Prioritized Fix Backlog

This section provides complete technical specifications, work breakdown structures (WBS), acceptance criteria, and regression assertions for all 29 audit findings identified in `docs/audit/TFP_PROTOCOL_SECURITY_AUDIT.md`.

---

### 2.1 Critical Severity Findings (P0 — Immediate Protocol / Security Failures)

#### [CRIT-01] False Positive Heuristic Flagging of 100% Non-Executable Payloads
- **Subsystem:** `tfp_security` (Heuristic Behavioral Engine)
- **Affected File:** `tfp_security/heuristic/behavioral_engine.py` (Lines 489–505)
- **Problem Statement & Root Cause:**
  `_analyze_structural_bytes` iterates across `patterns["executable"] + patterns["media"]` and increments threat score by `0.3` for every pattern that the payload *does not* match. Because a payload cannot match all magic signatures simultaneously, all valid PNG, JPEG, GIF, and plaintext payloads accumulate a score of $1.2 \ge 1.0$, triggering `ThreatCategory.STRUCTURAL_ANOMALY` across 100% of honest network traffic. Additionally, ASCII strings (`"MZ"`, `"PK"`, `"7z"`) were checked against hexadecimal strings (`actual_hex = content[:8].hex()`).
- **Detailed Technical Remediation:**
  1. Refactor `_analyze_structural_bytes` to check byte prefixes directly against categorized raw byte signatures (`media_magic`, `archive_magic`, `exec_magic`).
  2. Implement positive classification: if the payload matches any media or archive magic signature, or decodes as valid UTF-8/JSON text, assign a structural score of `0.0`.
  3. Apply threat score penalties ($\ge 0.8$) only when executable signatures (`MZ`, `ELF`, `Mach-O`) are detected in non-executable transfer contexts.
- **Work Breakdown Structure (WBS):**
  - `WBS-CRIT-01.1`: Update `_analyze_structural_bytes` in `behavioral_engine.py` with byte signature tables (2 hrs).
  - `WBS-CRIT-01.2`: Implement UTF-8 decoding fallback for plaintext/JSON documents (1 hr).
  - `WBS-CRIT-01.3`: Construct unit test suite verifying zero false positives on PNG, JPEG, PDF, ZIP, TXT, and JSON files (2 hrs).
- **Test & Verification Acceptance Criteria:**
  - `pytest tests/test_behavioral_engine.py` passes.
  - Assert `engine.analyze_content(png_bytes).threat_score == 0.0`.
  - Assert `engine.analyze_content(elf_bytes).threat_score >= 0.8`.

---

#### [CRIT-02] Broken Shannon Entropy Formula Disabling Anomaly & Ransomware Detection
- **Subsystem:** `tfp_core` (Security / Mutualistic Defense)
- **Affected File:** `tfp_core/security/mutualistic_defense.py` (Lines 404–409)
- **Problem Statement & Root Cause:**
  `MutualisticAuditor._calculate_entropy` computed `-sum((c/L) * ((c/L) * 0.693147))`, confusing $\ln(2) \approx 0.693147$ with probability multiplication. The function computed $-0.693147 \sum p^2$, yielding negative numbers in range $[-0.693, 0.0]$. Downstream checks for `entropy > 7.8` (high-entropy encrypted malware / ransomware detection) were mathematically unreachable.
- **Detailed Technical Remediation:**
  1. Implement true Shannon entropy using `math.log2`:
     $$H(X) = -\sum_{i=1}^{n} p(x_i) \log_2 p(x_i)$$
  2. Handle boundary conditions ($L = 0 \implies H = 0.0$).
- **Work Breakdown Structure (WBS):**
  - `WBS-CRIT-02.1`: Refactor `_calculate_entropy` to use `collections.Counter` and `math.log2` (1 hr).
  - `WBS-CRIT-02.2`: Add invariant assertions for uniform random bytes ($H \in [7.95, 8.0]$) and single-byte strings ($H = 0.0$) (1 hr).
- **Test & Verification Acceptance Criteria:**
  - `assert 7.95 <= auditor._calculate_entropy(os.urandom(100000)) <= 8.0`.
  - `assert auditor._calculate_entropy(b"\x00" * 1000) == 0.0`.
  - High-entropy alert triggers on random payload streams.

---

#### [CRIT-03] Cryptographic Signature Bypass in `HeuristicPack` and `GossipVerifier`
- **Subsystem:** `tfp_core` (Security / Mutualistic Defense)
- **Affected File:** `tfp_core/security/mutualistic_defense.py` (Lines 129–137 & 256–267)
- **Problem Statement & Root Cause:**
  `HeuristicPack.verify_signature` checked if `self.signature == sha3_256(json_content)[:16]`, completely ignoring the provided `public_key`. `GossipVerifier._verify_signal` verified unkeyed SHA3-256 string hashes. Any network adversary could forge rules and gossip signals without holding private keys.
- **Detailed Technical Remediation:**
  1. Replace unkeyed hash checks with true asymmetric Ed25519 digital signature signing and verification via `cryptography.hazmat.primitives.asymmetric.ed25519`.
  2. Maintain backward compatibility with PQC Dilithium5 keys where registered in `CryptoAgilityRegistry`.
- **Work Breakdown Structure (WBS):**
  - `WBS-CRIT-03.1`: Update `HeuristicPack` to sign serialized JSON with Ed25519 private keys (2 hrs).
  - `WBS-CRIT-03.2`: Update `GossipVerifier` to verify Ed25519 signatures on `AnomalySignal` structures (2 hrs).
  - `WBS-CRIT-03.3`: Construct adversarial test verifying signature rejection on forged public keys (2 hrs).
- **Test & Verification Acceptance Criteria:**
  - `pack.verify_signature(valid_pubkey)` returns `True`.
  - `pack.verify_signature(adversary_pubkey)` returns `False`.
  - Tampering with any field in `rules` invalidates signature.

---

#### [CRIT-04] Stub Signature Verification Bypass in Agility Registry & PQC Adapter
- **Subsystem:** `tfp_core` (Crypto Agility & Post-Quantum Adapter)
- **Affected Files:** `tfp_core/crypto/agility_registry.py` (Lines 449–451) & `tfp_core/crypto/pqc_adapter.py` (Lines 242–254)
- **Problem Statement & Root Cause:**
  `CryptoAgilityRegistry.verify_signature` returned `True` unconditionally for any signature formatted as `b"<...>"`. `PQCAdapter.verify` returned `True` unconditionally if `"stub"` was in `signature.algorithm`. Remote attackers could bypass all signature validation by enclosing arbitrary fake signatures in brackets.
- **Detailed Technical Remediation:**
  1. Remove all unconditional `return True` branches for stub signatures in production execution paths.
  2. When PQC C-libraries (`liboqs`) are not available, dynamically instantiate real classical cryptography (Ed25519 for signatures, X25519 for key encapsulation).
  3. Restrict mock stub verification strictly to unit test mocks explicitly decorated with `@pytest.mark.mock_crypto`.
- **Work Breakdown Structure (WBS):**
  - `WBS-CRIT-04.1`: Remove `<...>` and `"stub"` checks from `agility_registry.py` and `pqc_adapter.py` (1 hr).
  - `WBS-CRIT-04.2`: Wire standard `cryptography` Ed25519 fallback into `PQCAdapter` (3 hrs).
  - `WBS-CRIT-04.3`: Update all test cases to use valid Ed25519 keypairs in non-PQC environments (3 hrs).
- **Test & Verification Acceptance Criteria:**
  - `registry.verify_signature(b"data", b"<fake_sig>", pubkey)` returns `False`.
  - Fallback classical signature verification passes with valid Ed25519 keys and fails on corrupted payloads.

---

### 2.2 High Severity Findings (P1 — Economic, Transport & Resilience Breaches)

#### [HIGH-01] Denial of Service via Single-Shard HMAC Poisoning in RaptorQ Decoder
- **Subsystem:** `tfp_client` (Fountain Codecs / RaptorQ Transport)
- **Affected Files:** `tfp_client/lib/fountain/raptorq_ffi.py` (Lines 151–153) & `fountain_real.py` (Lines 255–257)
- **Problem Statement & Root Cause:**
  When decoding an erasure-coded payload, encountering a single shard with an invalid HMAC raised `IntegrityError`, terminating decoding of all shards. A remote attacker injecting 1 corrupted symbol could permanently DoS the entire multicast broadcast.
- **Detailed Technical Remediation:**
  1. Modify `decode()` in `raptorq_ffi.py` and `fountain_real.py` to inspect per-shard HMACs, log and drop corrupted shards, and accumulate valid frames.
  2. Only raise `IntegrityError` if the total count of valid frames is strictly less than source symbols $K$.
- **Work Breakdown Structure (WBS):**
  - `WBS-HIGH-01.1`: Refactor shard ingestion loop in `raptorq_ffi.py` to filter invalid HMACs (2 hrs).
  - `WBS-HIGH-01.2`: Refactor shard ingestion in `fountain_real.py` (2 hrs).
  - `WBS-HIGH-01.3`: Add fuzz test with 20% poisoned shards injected into 50 valid shards (2 hrs).
- **Test & Verification Acceptance Criteria:**
  - Decoder successfully recovers original data when poisoned shards are present, provided $N_{\text{valid}} \ge K$.

---

#### [HIGH-02] Double Spending & Spent Receipt Non-Invalidation in `CreditLedger`
- **Subsystem:** `tfp_client` (Credit & Ledger Accounting)
- **Affected File:** `tfp_client/lib/credit/ledger.py` (Lines 91–108)
- **Problem Statement & Root Cause:**
  `CreditLedger.spend()` verified that a receipt was in `self._chain`, but did not record the receipt into a spent nullifier set or write a spend block to the chain. A single earned receipt could be presented repeatedly to spend credits.
- **Detailed Technical Remediation:**
  1. Add `self._spent_receipts: set[str] = set()` to `CreditLedger`.
  2. Enforce `if receipt.chain_hash in self._spent_receipts: raise ValueError("Receipt already spent")`.
  3. Append an explicit `SPEND` transaction block into `self._chain` committing to the spent receipt hash.
- **Work Breakdown Structure (WBS):**
  - `WBS-HIGH-02.1`: Implement spent receipt set and spend block appending in `ledger.py` (2 hrs).
  - `WBS-HIGH-02.2`: Update ledger state export and Merkle root calculation to include spend transactions (2 hrs).
  - `WBS-HIGH-02.3`: Write double-spend replay unit tests (1 hr).
- **Test & Verification Acceptance Criteria:**
  - Second invocation of `ledger.spend(credits, receipt)` raises `ValueError("Receipt already spent")`.

---

#### [HIGH-03] Unauthenticated Free Credit Minting via `/api/earn`
- **Subsystem:** `tfp_demo` (Server API Gateway)
- **Affected File:** `tfp_demo/server.py` (Lines 3505–3549)
- **Problem Statement & Root Cause:**
  `/api/earn` verified device request signatures, but never verified whether `task_id` was a genuine compute task scheduled in `TaskStore` or validated `HABPExecutionProof`. Any node could mint 10 DWCC credits per request with random task IDs.
- **Detailed Technical Remediation:**
  1. Require `HABPExecutionProof` payload in `EarnRequest`.
  2. Verify that `task_id` exists in `TaskStore` with status `ASSIGNED` to `payload.device_id`.
  3. Execute `HABPVerifier.verify_proof()` before awarding DWCC credits.
- **Work Breakdown Structure (WBS):**
  - `WBS-HIGH-03.1`: Update `EarnRequest` schema with `execution_proof: Dict[str, Any]` (1 hr).
  - `WBS-HIGH-03.2`: Wire `HABPVerifier` and `TaskStore` validation into `/api/earn` (3 hrs).
  - `WBS-HIGH-03.3`: Construct test suite asserting 400 Bad Request on synthetic unassigned task IDs (2 hrs).
- **Test & Verification Acceptance Criteria:**
  - Submitting unassigned or forged task proofs returns HTTP 400.
  - Submitting verified HABP proof awards credits and marks task `COMPLETED`.

---

#### [HIGH-04] Insufficient Entropy & Insecure Seed Derivation in Mnemonic Generation
- **Subsystem:** `tfp_cli` (Identity & Key Derivation)
- **Affected File:** `tfp_cli/identity.py` (Lines 117–160)
- **Problem Statement & Root Cause:**
  Custom 32-word list provided only $12 \times 5 = 60$ bits of entropy. `mnemonic_to_seed` used a single-round unsalted SHA-256 hash. Private keys could be brute-forced on consumer GPUs.
- **Detailed Technical Remediation:**
  1. Integrate standard BIP-39 2048-word English dictionary (providing 128 to 256 bits of entropy).
  2. Implement PBKDF2-HMAC-SHA512 key stretching with salt `"mnemonic" + passphrase` and 2,048 iterations.
- **Work Breakdown Structure (WBS):**
  - `WBS-HIGH-04.1`: Import BIP-39 wordlist and implement standard checksum verification (2 hrs).
  - `WBS-HIGH-04.2`: Update `mnemonic_to_seed` with PBKDF2-HMAC-SHA512 (2 hrs).
  - `WBS-HIGH-04.3`: Write BIP-39 vector test suite (1 hr).
- **Test & Verification Acceptance Criteria:**
  - Generated mnemonics pass BIP-39 checksum verification with $\ge 128$ bits of entropy.

---

#### [HIGH-05] Chaos Orchestrator `NODE_CRASH` Global Network Outage Bug
- **Subsystem:** `tfp_simulator` (Chaos Engineering Engine)
- **Affected File:** `tfp_simulator/core.py` (Lines 254–259 & 275–276)
- **Problem Statement & Root Cause:**
  When `add_chaos_event(ChaosEvent.NODE_CRASH)` was called without explicit `target_ids`, `targets` defaulted to `list(self.devices.keys())`, instantly taking 100% of network nodes offline in a single step.
- **Detailed Technical Remediation:**
  1. Update target selection: when `target_ids` is None, sample a single random active online device (`random.sample(online_devices, 1)`).
  2. Support percentage-based crash configurations (e.g. 10% of active nodes).
- **Work Breakdown Structure (WBS):**
  - `WBS-HIGH-05.1`: Fix default target selection in `tfp_simulator/core.py` (1 hr).
  - `WBS-HIGH-05.2`: Add automated node reboot/recovery timers (2 hrs).
  - `WBS-HIGH-05.3`: Verify multi-step chaos demo runs without network collapse (1 hr).
- **Test & Verification Acceptance Criteria:**
  - Running `python tfp_simulator/run_chaos_demo.py` leaves $\ge 80\%$ of nodes online during random crash events.

---

#### [HIGH-06] Unauthenticated Suite Broadcast Import in Crypto Agility Registry
- **Subsystem:** `tfp_core` (Crypto Agility Registry)
- **Affected File:** `tfp_core/crypto/agility_registry.py` (Lines 338–364)
- **Problem Statement & Root Cause:**
  `import_suite_broadcast()` parsed unauthenticated JSON payloads from gossip and immediately changed the active cryptographic suite without verifying maintainer signatures. Attackers could broadcast cipher downgrade directives.
- **Detailed Technical Remediation:**
  1. Require governance cryptographic signature on suite broadcast messages.
  2. Verify signature against authorized maintainer keys defined in `GovernanceManifest`.
- **Work Breakdown Structure (WBS):**
  - `WBS-HIGH-06.1`: Add signature verification to `import_suite_broadcast` (2 hrs).
  - `WBS-HIGH-06.2`: Write unit tests for valid maintainer signature and rejected adversary broadcast (2 hrs).
- **Test & Verification Acceptance Criteria:**
  - Unsigned or adversary-signed cipher suite broadcasts are rejected.

---

### 2.3 Medium Severity Findings (P2 — Transport, Concurrency, Parsing & Tooling Deficits)

#### [MED-01] WebBridge URL Query Parsing Failure on `tfp://tag/...`
- **Subsystem:** `tfp_plugin_sdk` (Web Bridge Adapter)
- **Affected File:** `tfp_plugin_sdk/adapters/web_bridge.py` (Lines 160–186)
- **Problem & Root Cause:** `urllib.parse.urlparse` sets `netloc = "tag"` on `tfp://tag/music`. The first `if` branch checks `len(netloc) == 64` which fails and completely skips the `elif path.startswith("/tag/")` branch.
- **Remediation:** Check `if parsed.netloc == "tag" or parsed.path.startswith("/tag/"):` prior to content hash parsing.
- **WBS:** Update parser logic in `web_bridge.py` (1 hr), add URL test vectors for tag and hash schemes (1 hr).
- **Acceptance Gate:** `parse_tfp_url("tfp://tag/music/ambient").tag_query == "music/ambient"`.

#### [MED-02] Non-Deterministic Hash & Timestamp Clamping in Spectrum Encapsulation
- **Subsystem:** `tfp_transport` (Spectrum Encapsulation)
- **Affected File:** `tfp_transport/spectrum_encap.py` (Lines 103 & 281)
- **Problem & Root Cause:** `hash(content_hash)` uses Python randomized per-process salt; `min(int(t*1000), 0xFFFFFFFF)` permanently clamps millisecond timestamps to `4294967295`.
- **Remediation:** Compute `payload_id` using `int(sha3_256(content_hash)[:8], 16)`; use bitmask `int(t*1000) & 0xFFFFFFFF`.
- **WBS:** Refactor hash and timestamp in `spectrum_encap.py` (1 hr), verify deterministic packet headers across restarts (1 hr).
- **Acceptance Gate:** Identical `ATSC3LCTHeader` binary serialization across separate Python daemon processes.

#### [MED-03] Concurrency Race Condition in `MerkleizedRaptorQ._log_dropped_shard`
- **Subsystem:** `tfp_transport` (Merkleized RaptorQ)
- **Affected File:** `tfp_transport/merkleized_raptorq.py` (Lines 420–433)
- **Problem & Root Cause:** `_log_dropped_shard()` mutates `self._dropped_shards` without acquiring `self._lock` during multi-threaded shard verification.
- **Remediation:** Enclose all `self._dropped_shards` operations in `with self._lock:`.
- **WBS:** Add lock context to `_log_dropped_shard` (0.5 hr), run concurrent shard verification stress test (1 hr).
- **Acceptance Gate:** Zero race condition exceptions under 50-thread concurrent verification.

#### [MED-04] Undefined `Tuple` NameError in Scholo Radio Audio Server
- **Subsystem:** `tfp_ui` (Scholo Radio Pilot)
- **Affected File:** `tfp_ui/scholo_radio/server.py` (Lines 29 & 193)
- **Problem & Root Cause:** Line 193 annotates `-> Tuple[Dict[str, Any], bytes]:`, but `Tuple` is missing from typing imports.
- **Remediation:** Add `Tuple` to typing imports or use Python 3.10+ native `tuple[...]`.
- **WBS:** Fix import in `server.py` (0.5 hr), run type checking and runtime inspection (0.5 hr).
- **Acceptance Gate:** `python tfp_ui/scholo_radio/server.py` imports without `NameError`.

#### [MED-05] Swarm Fountain Droplet Pool Rank Exhaustion Under Packet Loss
- **Subsystem:** `tfp_core_v4` (Mesh Swarm)
- **Affected File:** `tfp_core_v4/mesh.py` (Lines 98–158)
- **Problem & Root Cause:** Peers only store and forward a static pre-generated list of droplets. High-loss multi-hop relays result in $rank < K$ and decode failure.
- **Remediation:** Implement on-demand rateless droplet synthesis ($seed \in [K, \infty)$) dynamically upon receiver request.
- **WBS:** Refactor `SwarmNetwork.request_droplet()` to generate dynamic seeds (3 hrs), add multi-hop loss test (2 hrs).
- **Acceptance Gate:** 100% reconstruction on 5-node swarm under 40% packet loss.

#### [MED-06] Pytest Discovery Configuration Disconnect
- **Subsystem:** Test Infrastructure
- **Affected File:** `pytest.ini`
- **Problem & Root Cause:** `pytest.ini` lacks `testpaths`, skipping 139 root tests in `tests/` during standard `pytest` run.
- **Remediation:** Add `testpaths = tests tfp-foundation-protocol/tests tfp_core tfp_simulator` to `pytest.ini`.
- **WBS:** Update `pytest.ini` (0.5 hr), verify test count increases from 993 to 1,132+ (0.5 hr).
- **Acceptance Gate:** Plain `pytest` command executes all root and nested test suites.

#### [MED-07] Windows Console Unicode Encoding Failures
- **Subsystem:** CLI & Benchmarks
- **Affected Files:** `tfp_simulator/run_chaos_demo.py` (Line 201) & `benchmark_raptorq.py` (Line 140)
- **Problem & Root Cause:** Raw Unicode emojis trigger `UnicodeEncodeError: 'charmap'` on default Windows cp1252 consoles.
- **Remediation:** Replace emojis with ASCII status tags (`[OK]`, `[FAIL]`, `[+]`) or configure UTF-8 output streams.
- **WBS:** Replace emoji characters across CLI and benchmark scripts (1 hr).
- **Acceptance Gate:** `python tfp_simulator/run_chaos_demo.py` executes cleanly on Windows PowerShell.

#### [MED-08] Missing Package `__init__.py` Boundaries Across Subsystems
- **Subsystem:** Packaging & Module Resolution
- **Affected Directories:** `tfp_core/`, `tfp_security/`, `tfp_transport/`, `tfp_plugins/`, `tfp_ui/`
- **Problem & Root Cause:** Missing `__init__.py` files prevent standard package resolution and static analysis.
- **Remediation:** Create `__init__.py` files with clean `__all__` exports across all subdirectories.
- **WBS:** Generate `__init__.py` files with proper export declarations (2 hrs).
- **Acceptance Gate:** All packages import successfully via standard `import tfp_core.*`.

#### [MED-09] Second Preimage and Merkle Tree Domain Separation Deficit
- **Subsystem:** `tfp_core_v4` / `tfp_transport` (Merkle Verification)
- **Affected Files:** `tfp_core_v4/merkle.py`, `tfp_transport/merkleized_raptorq.py`, `ledger.py`
- **Problem & Root Cause:** Merkle hashing lacks RFC 6962 domain prefixes, risking second-preimage attacks.
- **Remediation:** Prefix leaf hashes with `\x00` and internal node hashes with `\x01`.
- **WBS:** Update `MerkleTree` in `merkle.py` and `merkleized_raptorq.py` (2 hrs), update proof verification tests (2 hrs).
- **Acceptance Gate:** Merkle tree proofs conform to RFC 6962 standard test vectors.

#### [MED-10] Insecure Substring TEE Attestation Check in HABP Verifier
- **Subsystem:** `tfp_core` (Compute Consensus / HABP)
- **Affected File:** `tfp_core/compute/verify_habp.py` (Lines 167–175)
- **Problem & Root Cause:** `_verify_tee_quote` performs substring check `quote.startswith(...) and "VALID" in quote`.
- **Remediation:** Implement cryptographic quote validation with root certificate verification.
- **WBS:** Refactor `_verify_tee_quote` to parse quote signatures (2 hrs), write test vectors for valid/forged quotes (1 hr).
- **Acceptance Gate:** Synthetic quote strings like `"node_VALID_TEE"` are rejected.

#### [MED-11] Signature Scope Replay Vulnerability in `/api/publish`
- **Subsystem:** `tfp_demo` (Server API Gateway)
- **Affected File:** `tfp_demo/server.py` (Lines 3353–3365)
- **Problem & Root Cause:** `X-Device-Sig` only signs `{device_id}:{title}`, allowing payload substitution.
- **Remediation:** Bind message: `{device_id}:{title}:{sha3_256(body)}:{timestamp}`.
- **WBS:** Update signature check in `/api/publish` (1 hr), update client signing logic (1 hr).
- **Acceptance Gate:** Altering content body with original signature returns HTTP 401.

---

### 2.4 Low Severity & Code Quality Deficits (P3 — Code Health & Modularity)

#### [LOW-01] The "God Module" Anti-Pattern in `tfp_demo/server.py`
- **Subsystem:** `tfp_demo`
- **Remediation:** Modularize into `tfp_server/storage/`, `tfp_server/api/`, `tfp_server/consensus/`, and `tfp_server/bridges/`.
- **WBS:** Split into 5 modular service packages (80 hrs).

#### [LOW-02] Static Type Deficits & 223+ Mypy Errors
- **Subsystem:** Repository-Wide
- **Remediation:** Resolve implicit optionals, replace `builtins.any` with `typing.Any`, fix proof typing, and enforce `mypy --strict`.
- **WBS:** Type annotation overhaul across 56 files (24 hrs).

#### [LOW-03] Orphaned & Disconnected Subsystems
- **Subsystem:** `tfp_core` / `tfp_transport`
- **Remediation:** Wire `MetadataShield`, `SpectrumEncapsulator`, and `TaskMeshGates` into daemon request lifecycle.
- **WBS:** Wire into client session and server bootstrap (12 hrs).

#### [LOW-04] Fragmented & Duplicate Subsystem Implementations
- **Subsystem:** Root vs Inner Package
- **Remediation:** Standardize on canonical 64-bit FastCDC, unified HABP, and `prometheus_client` exporter.
- **WBS:** Consolidate duplicate modules into `tfp_core_v4` and `tfp-sdk` (16 hrs).

#### [LOW-05] Unprotected Concurrency in `TaskMeshGates.slash_stake`
- **Subsystem:** `tfp_core` (Economy)
- **Remediation:** Wrap `slash_stake` operations with `with self._lock:`.
- **WBS:** Add lock synchronization (0.5 hr).

#### [LOW-06] Inefficient IPC Serialization in Parallel Pure-Python Fountain Encoder
- **Subsystem:** `tfp_client` (Fountain Codecs)
- **Remediation:** Use `multiprocessing.shared_memory` to avoid copying payloads across processes.
- **WBS:** Refactor `_encode_repair_parallel` to use shared memory buffers (6 hrs).

#### [LOW-07] Deprecated `datetime.utcnow()` Usage
- **Subsystem:** `tfp_core` (Audit Tools)
- **Remediation:** Replace with `datetime.datetime.now(datetime.timezone.utc)`.
- **WBS:** Replace deprecated calls (1 hr).

#### [LOW-08] Dead Code & Empty Subpackages
- **Subsystem:** `tfp_common` & `tfp_broadcaster`
- **Remediation:** Prune 6 empty placeholder packages containing only `__init__.py`.
- **WBS:** Remove empty package directories (0.5 hr).

---

### 2.5 Master Work Breakdown Structure (WBS) & Sprint Resource Plan

```
+-----------------------------------------------------------------------------------------------------------------------+
| SPRINT | FOCUS AREAS                                       | ASSIGNED FINDINGS              | ESTIMATED HOURS         |
+--------+---------------------------------------------------+--------------------------------+-------------------------+
| S-01   | Core Cryptography & Entropy Corrections           | CRIT-02, CRIT-03, CRIT-04      | 32 Engineering Hours    |
| S-02   | Behavioral Inspection & Transport HMAC Hardening  | CRIT-01, HIGH-01, HIGH-06      | 36 Engineering Hours    |
| S-03   | Economic Accounting, Earn Auth & Identity Seeds   | HIGH-02, HIGH-03, HIGH-04      | 40 Engineering Hours    |
| S-04   | Simulator Chaos, Spectrum & Concurrency Fixes     | HIGH-05, MED-02, MED-03, MED-07| 30 Engineering Hours    |
| S-05   | Transport Swarm Codec & Merkle Separation         | MED-01, MED-04, MED-05, MED-09 | 34 Engineering Hours    |
| S-06   | Packaging, Test Discovery & TEE/Signature Gating  | MED-06, MED-08, MED-10, MED-11 | 28 Engineering Hours    |
| S-07   | Monolith Server Decomposition (Phase 1: Storage)  | LOW-01, LOW-05                 | 44 Engineering Hours    |
| S-08   | Monolith Server Decomposition (Phase 2: API/Cons) | LOW-01, LOW-03                 | 44 Engineering Hours    |
| S-09   | Strict Static Typing & Shared Memory Optimization | LOW-02, LOW-06, LOW-07, LOW-08 | 38 Engineering Hours    |
| S-10   | Unified `tfp-sdk` Implementation & Final Sign-off | Extension 1-5 Integration      | 60 Engineering Hours    |
+-----------------------------------------------------------------------------------------------------------------------+
| TOTAL RESOURCE ALLOCATION: 10 Sprints | 386 Dedicated Protocol Engineering Hours                                      |
+-----------------------------------------------------------------------------------------------------------------------+
```

---

## 3. Code Add-ons & Architectural Extensions

This section delivers complete technical specifications, data flow architectures, API schemas, and dependency graphs for the 5 core architectural extensions.

---

### 3.1 Extension 1: Unified `tfp-sdk` (Modern Python Client SDK)

#### 3.1.1 Architectural Rationale & Component Design
The current client experience is fragmented across `tfp_client.lib.*` internal modules, raw HTTP calls in `tfp_demo`, and isolated CLI commands. The `tfp-sdk` delivers a unified, production-grade Python SDK featuring:
- Typed asynchronous (`AsyncTFPClient`) and synchronous (`TFPClient`) interfaces.
- Automatic connection pooling, circuit breaking, and peer failover.
- Embedded client-side FastCDC chunking, Merkle proof validation, and Fountain decoding.
- Full cryptographic agility with transparent post-quantum signature verification.

```
+----------------------------------------------------------------------------------------------------+
|                                    UNIFIED TFP-SDK ARCHITECTURE                                    |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   +--------------------------------------------------------------------------------------------+   |
|   |                        High-Level Application Layer (Async & Sync APIs)                    |   |
|   |   - client.publish()           - client.get_stream()         - client.submit_task()        |   |
|   |   - client.enroll_device()     - client.verify_receipt()     - client.get_balance()        |   |
|   +--------------------------------------------------------------------------------------------+   |
|                                                  │                                                 |
|                                                  ▼                                                 |
|   +--------------------------------------------------------------------------------------------+   |
|   |                           SessionManager & Resilient Transport Pool                        |   |
|   |   - Connection Pooling (HTTP/2, WebSocket, UDP)    - Circuit Breaker (Half-Open / Open)   |   |
|   |   - Multi-Node Failover & Peer Discovery           - Exponential Backoff & Jitter Retry    |   |
|   +--------------------------------------------------------------------------------------------+   |
|                         │                                                │                         |
|                         ▼                                                ▼                         |
|   +------------------------------------------+     +-------------------------------------------+   |
|   |      Client-Side Streaming Pipeline      |     |        PQC Cryptographic Agility Core     |   |
|   |   - FastCDC 64-bit Chunk Boundary Slicer |     |   - Dilithium5 / Kyber768 Key Enclave     |   |
|   |   - Merkle Tree Hash Validator (RFC 6962)|     |   - Dual-Signing Hybrid (Ed25519 fallback)|   |
|   |   - Rateless Fountain / RaptorQ Assembler|     |   - Automatic Nonce & Timestamp Binding   |   |
|   +------------------------------------------+     +-------------------------------------------+   |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

#### 3.1.2 Interface & Type Definitions

```python
"""tfp_sdk/client.py - Unified Python Client Interface."""

from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Union
import httpx

class NodeHealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"

@dataclass(frozen=True)
class ContentRecipe:
    root_hash: str
    total_size: int
    chunk_count: int
    symbol_size: int
    content_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    author_pubkey: Optional[str] = None
    signature: Optional[str] = None

@dataclass
class SDKConfig:
    node_endpoints: List[str]
    device_id: str
    private_key_path: Optional[str] = None
    connection_timeout_sec: float = 10.0
    max_retries: int = 4
    enable_pqc: bool = True
    max_connections: int = 100

class AsyncTFPClient:
    """Production asynchronous client for The Foundation Protocol."""

    def __init__(self, config: SDKConfig) -> None:
        self.config = config
        self._pool: Optional[httpx.AsyncClient] = None
        self._active_endpoint_idx: int = 0
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> AsyncTFPClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def connect(self) -> None:
        """Initialize connection pool with circuit breaking."""
        limits = httpx.Limits(
            max_connections=self.config.max_connections,
            max_keepalive_connections=20
        )
        self._pool = httpx.AsyncClient(
            timeout=self.config.connection_timeout_sec,
            limits=limits,
            http2=True
        )

    async def close(self) -> None:
        if self._pool:
            await self._pool.aclose()

    async def publish(
        self,
        data: bytes,
        title: str,
        content_type: str = "application/octet-stream",
        tags: Optional[List[str]] = None
    ) -> ContentRecipe:
        """Publish payload with client-side FastCDC chunking and signed Merkle root."""
        ...

    async def get_stream(
        self,
        root_hash: str,
        max_loss_tolerance: float = 0.40
    ) -> AsyncIterator[bytes]:
        """Stream and assemble rateless erasure droplets into decoded byte stream."""
        ...

    async def submit_compute_task(
        self,
        task_id: str,
        execution_proof: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Submit verified HABP compute execution proof to earn DWCC credits."""
        ...
```

---

### 3.2 Extension 2: Modular Node Server Decomposition (`tfp_server/*`)

#### 3.2.1 Target Layered Architecture
The monolithic 4,500-line `tfp_demo/server.py` is decomposed into isolated, single-responsibility modules under `tfp_server/`:

```
tfp_server/
├── __init__.py
├── main.py                        # Server bootstrap, CLI flags & dependency injection
├── config.py                      # Strongly typed Pydantic v2 server settings
├── api/                           # FastAPI Router Modules
│   ├── __init__.py
│   ├── dependencies.py            # Authentication, rate limiting & DB injection
│   ├── routes_content.py          # /api/publish, /api/get, /api/tags, /api/stream
│   ├── routes_compute.py          # /api/tasks, /api/earn, /api/habp/verify
│   ├── routes_identity.py         # /api/enroll, /api/device/status
│   └── routes_admin.py            # Dashboard HTML & admin telemetry
├── storage/                       # Storage Engine Abstraction Layer
│   ├── __init__.py
│   ├── base.py                    # Abstract StorageEngine protocol
│   ├── sqlite/                    # Thread-safe SQLite WAL stores
│   │   ├── engine.py              # Connection pool & transaction manager
│   │   ├── content_store.py       # Recipes, manifests & chunk index
│   │   ├── device_store.py        # Device enrollment & PUF public keys
│   │   ├── credit_store.py        # Balance accounting & spend nullifiers
│   │   └── task_store.py          # Compute tasks, bids & assignments
│   └── blob/                      # Content-addressed filesystem / S3 blob store
├── consensus/                     # Consensus & Verification Subsystems
│   ├── __init__.py
│   ├── habp_engine.py             # Verifiable hardware benchmark proof engine
│   └── task_mesh_gate.py          # Stake management & anti-Sybil economic rules
├── bridges/                       # Decentralized Network Bridges
│   ├── __init__.py
│   ├── nostr_bridge.py            # BIP-340 Schnorr / NIP-01 relay client
│   ├── ipfs_bridge.py             # Kubo RPC client & CID multihash mapping
│   └── spectrum_bridge.py         # ATSC 3.0 LCT multicast encapsulator
└── monitoring/                    # Observability & Metrics
    ├── __init__.py
    ├── prometheus.py              # Official prometheus_client metrics collectors
    └── health.py                  # Liveness and readiness probe checks
```

#### 3.2.2 Storage Engine Protocol Interface

```python
"""tfp_server/storage/base.py - Pluggable Storage Protocol."""

from typing import Protocol, Optional, List, Dict, Any
from dataclasses import dataclass

@dataclass
class StoredContent:
    content_hash: str
    title: str
    content_type: str
    total_bytes: int
    chunk_count: int
    published_at: float
    author_id: str
    metadata_json: str

class StorageEngine(Protocol):
    """Abstract interface decoupling database persistence from HTTP handlers."""

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...

    # Content Operations
    async def put_content(self, content: StoredContent) -> bool: ...
    async def get_content(self, content_hash: str) -> Optional[StoredContent]: ...
    async def list_content_by_tag(self, tag: str, limit: int = 50) -> List[StoredContent]: ...

    # Credit & Ledger Operations
    async def get_balance(self, device_id: str) -> int: ...
    async def record_earn(self, device_id: str, task_id: str, amount: int) -> bool: ...
    async def record_spend(self, device_id: str, receipt_hash: str, amount: int) -> bool: ...
```

---

### 3.3 Extension 3: Sandboxed Plugin Runtime (`tfp_plugin_engine`)

#### 3.3.1 Capability Security Model & Isolation Architecture
The `tfp_plugin_engine` introduces a secure runtime for executing untrusted third-party plugins (e.g. customized paywalls, DRM decoders, indexing agents, and transcoders). Plugins execute within a WebAssembly (WASM) sandbox via `wasmtime` or as isolated gRPC worker processes.

```
+----------------------------------------------------------------------------------------------------+
|                                    SANDBOXED PLUGIN RUNTIME                                        |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|    TFP Node Core Event Bus                                                                         |
|    (Events: ON_CONTENT_INGEST, ON_SHARD_RECEIVED, ON_TASK_BID, ON_PAYMENT_REQUEST)                |
|               │                                                                                    |
|               ▼                                                                                    |
|    +------------------------------------------------------------------------------------------+    |
|    |                             Capability Gatekeeper & Policy Filter                        |    |
|    |   - Validates plugin.yaml manifest permissions against node security policy              |    |
|    |   - Enforces memory quotas (max 64 MB), execution timeouts (max 500 ms), and syscall caps|    |
|    +------------------------------------------------------------------------------------------+    |
|               │                                                    │                               |
|               ▼ (In-Process WASM Isolation)                        ▼ (External gRPC Isolation)     |
|    +--------------------------------------+     +---------------------------------------------+    |
|    |     Wasmtime Sandboxed Instance      |     |        Isolated Subprocess Worker           |    |
|    |  - Linear memory isolation           |     |  - gRPC over Unix Domain Socket / Named Pipe|    |
|    |  - Zero ambient filesystem access    |     |  - Restricted seccomp-bpf / AppArmor profile|    |
|    |  - Exported C-ABI: tfp_hook_invoke() |     |  - CPU cgroup limits (0.5 core max)         |    |
|    +--------------------------------------+     +---------------------------------------------+    |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

#### 3.3.2 Plugin Manifest Specification (`plugin.yaml`)

```yaml
# tfp_plugins/manifest_schema.yaml
schema_version: "1.0.0"
plugin_id: "com.foundation.license_paywall"
name: "Threshold Credit Paywall"
version: "1.2.0"
runtime: "wasm" # Options: wasm, grpc, native_sandboxed
entrypoint: "paywall.wasm"

capabilities:
  network:
    allow_outbound: false
    allowed_hosts: []
  storage:
    max_storage_bytes: 10485760 # 10 MB KV quota
  system:
    allow_time_read: true
    allow_random_read: true
    allow_subprocess: false

event_hooks:
  - event: "ON_CONTENT_INGEST"
    priority: 100
    timeout_ms: 250
  - event: "ON_ACCESS_REQUEST"
    priority: 10
    timeout_ms: 100
```

---

### 3.4 Extension 4: High-Throughput Erasure & Acceleration Engine

#### 3.4.1 SIMD Vectorization & Zero-Copy Memory Pipeline
To achieve extreme throughput across 100GbE backhauls and broadcast modulators, the Erasure Acceleration Engine combines:
1. **SIMD-Accelerated Galois Field Arithmetic**: AVX-512 / AVX2 (x86_64) and ARM NEON (aarch64) vector instructions executing 64 bytes of XOR operations per single CPU cycle.
2. **On-The-Fly Incremental Row Reduction**: Eliminates repetitive $O(K^3)$ batch Gaussian elimination by maintaining an upper-triangular matrix state as droplets arrive.
3. **Zero-Copy Memory-Mapped Ring Buffer**: Eliminates IPC serialization overhead during multi-core processing via `multiprocessing.shared_memory`.

```
+----------------------------------------------------------------------------------------------------+
|                                HIGH-THROUGHPUT ERASURE PIPELINE                                    |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   Source Payload (e.g. 100 MB Video)                                                               |
|        │                                                                                           |
|        ▼                                                                                           |
|   [Memory-Mapped Shared Ring Buffer (POSIX shm_open / Windows SharedMemory)]                       |
|        │                                                                                           |
|        ├──► Worker Thread 0 [SIMD AVX-512 XOR] ──► Droplets 0..N/4                                 |
|        ├──► Worker Thread 1 [SIMD AVX-512 XOR] ──► Droplets N/4..N/2                               |
|        ├──► Worker Thread 2 [SIMD AVX-512 XOR] ──► Droplets N/2..3N/4                             |
|        └──► Worker Thread 3 [SIMD AVX-512 XOR] ──► Droplets 3N/4..N                               |
|                                                                                                    |
|   Dynamic Rateless Droplet Generator:                                                              |
|   $Droplet(seed) = \bigoplus_{i \in Neighbors(seed)} Symbol_i \quad \text{for } seed \in [K, \infty)$|
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

#### 3.4.2 Benchmark Acceleration Projections

```
+----------------------------------------------------------------------------------------------------+
| PAYLOAD SIZE | PURE-PYTHON BASELINE | MULTI-CORE SHM PIPELINE | SIMD-ACCELERATED C-FFI | SPEEDUP   |
+--------------+----------------------+-------------------------+------------------------+-----------+
| 100 KB       | 4.8 MB/s             | 18.2 MB/s               | 95.0 MB/s              | 19.8x     |
| 1 MB         | 0.8 MB/s             | 14.5 MB/s               | 120.0 MB/s             | 150.0x    |
| 10 MB        | 0.1 MB/s             | 12.0 MB/s               | 1,650.0 MB/s           | 16,500x   |
| 100 MB       | OOM / Timeout        | 9.8 MB/s                | 2,100.0 MB/s           | >20,000x  |
+----------------------------------------------------------------------------------------------------+
```

---

### 3.5 Extension 5: Hardware Security Module (HSM/TPM) Provider

#### 3.5.1 Architecture & Pluggable Provider Model
The HSM Provider establishes a hardware-rooted identity and secure cryptographic keystore for node authentication, HABP benchmark attestation, and PQC key protection.

```python
"""tfp_security/hsm/provider.py - Abstract Hardware Trust Anchor."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class KeyType(Enum):
    ED25519 = "ed25519"
    DILITHIUM5 = "dilithium5"
    KYBER768 = "kyber768"
    SECP256K1 = "secp256k1"

@dataclass
class HardwareAttestationQuote:
    pcr_digest: bytes
    quote_signature: bytes
    enclave_public_key: bytes
    timestamp_epoch: int

class HardwareEnclaveProvider(ABC):
    """Abstract interface for Hardware Security Modules, TPM 2.0, and Enclaves."""

    @abstractmethod
    def initialize(self, slot_id: Optional[int] = None, pin: Optional[str] = None) -> bool:
        """Initialize connection to physical cryptographic hardware."""
        ...

    @abstractmethod
    def sign(self, key_alias: str, payload: bytes) -> bytes:
        """Sign payload using non-exportable hardware private key."""
        ...

    @abstractmethod
    def get_public_key(self, key_alias: str) -> bytes:
        """Export hardware public key."""
        ...

    @abstractmethod
    def generate_attestation_quote(self, nonce: bytes) -> HardwareAttestationQuote:
        """Generate verifiable hardware attestation quote for HABP consensus."""
        ...
```

#### 3.5.2 Supported Hardware Adapters

1. **PKCS#11 Adapter (`PKCS11Provider`)**:
   - Interfaces with enterprise Hardware Security Modules (YubiKey 5 FIPS, Thales Luna, AWS CloudHSM).
   - Secures root authority certificates and maintainer governance keys.
2. **TPM 2.0 Adapter (`TPM2Provider`)**:
   - Communicates with platform TPM 2.0 chips via `tss2-tcti` and `/dev/tpmrm0` on Linux servers.
   - Seals node identity keys to Platform Configuration Registers (PCRs 0–7), ensuring keys are inaccessible if firmware/boot chain is compromised.
3. **Apple Secure Enclave Adapter (`SecureEnclaveProvider`)**:
   - Utilizes macOS/iOS `CryptoKit` and Secure Enclave coprocessor.
   - Provides hardware-backed biometric (Touch ID / Face ID) key authorization for client wallets.

---

## 4. Dependency Graph, Compatibility Matrix, and Migration Path

### 4.1 System-Wide Component Dependency Graph (DAG)

```
                                  +-----------------------+
                                  |   GovernanceManifest  |
                                  +-----------------------+
                                              │
                                              ▼
                                  +-----------------------+
                                  |  CryptoAgilityRegistry|
                                  +-----------------------+
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼                                             ▼
            +--------------------+                        +--------------------+
            | HardwareEnclave    |                        | PQCAdapter         |
            | (HSM / TPM 2.0)    |                        | (Dilithium/Kyber)  |
            +--------------------+                        +--------------------+
                       │                                             │
                       └──────────────────────┬──────────────────────┘
                                              │
                                              ▼
                                  +-----------------------+
                                  |      tfp_core_v4      |
                                  | (CDC, Fountain, Merkle|
                                  +-----------------------+
                                              │
                       ┌──────────────────────┴──────────────────────┐
                       ▼                                             ▼
            +--------------------+                        +--------------------+
            | tfp_transport      |                        | tfp_plugin_engine  |
            | (RaptorQ, Spectrum)|                        | (WASM Sandbox)     |
            +--------------------+                        +--------------------+
                       │                                             │
                       └──────────────────────┬──────────────────────┘
                                              │
                                              ▼
                                  +-----------------------+
                                  |      tfp_server       |
                                  | (Storage, API, HABP)  |
                                  +-----------------------+
                                              │
                                              ▼
                                  +-----------------------+
                                  |       tfp-sdk         |
                                  | (Async/Sync Client)   |
                                  +-----------------------+
```

---

### 4.2 Protocol & Cipher Suite Compatibility Matrix

```
+----------------------------------------------------------------------------------------------------+
| PROTOCOL VERSION | SUPPORTED CIPHER SUITES              | WIRE FORMAT       | STATUS & SUPPORT     |
+------------------+--------------------------------------+-------------------+----------------------+
| TFP v3.1         | Ed25519, SHA-256, HMAC-SHA256        | JSON / Struct !BB | Deprecated (Phase 1) |
| TFP v3.2         | Ed25519 + Dilithium5 Dual-Sign, SHA3 | Binary Droplet v1 | Transitional Active  |
| TFP v4.0         | Dilithium5, Kyber768, BLAKE3, SHA3   | Binary Droplet v2 | Target Standard      |
| TFP v4.1 (Next)  | SPHINCS+, Kyber1024, Hardware Enclave| Binary Stream v3  | Future Extension     |
+----------------------------------------------------------------------------------------------------+
```

---

### 4.3 Database Schema & Storage Migration Path

To migrate from the monolithic SQLite database in `server.py` to the modular `tfp_server/storage` schema without data loss:

```sql
-- Migration Script: V001__migrate_v3_to_v4_storage.sql
BEGIN TRANSACTION;

-- 1. Create versioned schema migration tracking table
CREATE TABLE IF NOT EXISTS schema_version (
    version_id INTEGER PRIMARY KEY,
    installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT NOT NULL
);

-- 2. Migrate Content Store with RFC 6962 Domain Separation
ALTER TABLE content ADD COLUMN rfc6962_merkle_root TEXT;
ALTER TABLE content ADD COLUMN pqc_signature TEXT;

-- 3. Upgrade Credit Ledger with Spend Nullifier Table
CREATE TABLE IF NOT EXISTS spent_receipt_nullifiers (
    nullifier_hash TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    spent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    spend_tx_block INTEGER NOT NULL,
    FOREIGN KEY(device_id) REFERENCES devices(device_id)
);

-- 4. Create Index on Nullifiers
CREATE INDEX IF NOT EXISTS idx_nullifiers_device ON spent_receipt_nullifiers(device_id);

INSERT INTO schema_version (version_id, description) VALUES (400, 'TFP v4.0 Modular Storage Migration');

COMMIT;
```

---

### 4.4 Cluster & Node Rollout Execution Runbook

```
+----------------------------------------------------------------------------------------------------+
| STEP | ACTION               | COMMAND / SCRIPT                       | VERIFICATION GATE           |
+------+----------------------+----------------------------------------+-----------------------------+
| 1    | Pre-Migration Backup | `sqlite3 tfp.db ".backup tfp_v3.bak"`   | Verify backup SHA3 integrity|
| 2    | Schema Migration     | `python -m tfp_server.storage.migrate` | Confirm schema_version=400  |
| 3    | Core Security Gates  | `pytest tests/ -v -m "not slow"`       | 100% tests pass (0 failures)|
| 4    | Service Activation   | `systemctl restart tfp-server`         | Health probe `/health`=200  |
| 5    | Swarm Mesh Reconnect | `tfp-cli mesh status --json`           | >= 5 active peer links      |
+----------------------------------------------------------------------------------------------------+
```

---

*Authored and certified by the Protocol Engineering & Architecture Group.*
