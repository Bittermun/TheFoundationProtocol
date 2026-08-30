# The Foundation Protocol (TFP): Phase 1 — Cryptographic Agility & Mathematical Verification Specification

**Document Classification:** Publication-Grade Architectural Specification & Cryptographic Engineering Standard  
**Document Version:** 4.1.0-CRYPTO-SPEC  
**Target Platform:** The Foundation Protocol (TFP) Core Layer & Cryptographic Subsystem  
**Working Group:** Security Engineering & Post-Quantum Cryptography Working Group  
**Date of Release:** August 2026  
**Status:** Approved for Implementation  

---

## 1. Executive Summary & Scope

Phase 1 of The Foundation Protocol (TFP) establishes the quantum-resistant, zero-trust cryptographic foundation and mathematical verification infrastructure. In adversarial, low-bandwidth, and high-loss environments (e.g., LEO satellite broadcast, ATSC 3.0 terrestrial spectrum, tactical wireless mesh, and peer-to-peer swarms), naive cryptographic designs fail:
1. Attaching heavy Post-Quantum Cryptography (PQC) signatures ($4.5\text{ KB} - 17\text{ KB}$) to every $256\text{ B} - 1.4\text{ KB}$ network droplet causes massive MTU packet fragmentation and exponential packet drop rates.
2. Unkeyed sequential PRNG seeds in fountain erasure codes allow Byzantine adversaries to inject single polluted droplets that mathematically destroy Gaussian elimination decoding across the entire payload.
3. Proprietary or non-standard identity seeds expose devices to entropy degradation and lack hardware root-of-trust interoperability.

To solve these foundational challenges, Phase 1 formalizes:
- **Two-Tiered Cryptographic Architecture**: Decoupling heavy Tier 1 Post-Quantum Content Manifest signatures from ultra-lightweight Tier 2 intra-mesh hop authentication tokens.
- **Dynamic Cryptographic Agility Engine (`CryptoAgilityRegistry`)**: Formal negotiation, deprecation schedules, dual-signing migration envelopes, and authenticated Governance Manifest broadcasts.
- **Authenticated Deterministic PRNG Seed Schedules**: PRF-driven seed pools ($seed \ge K$) bound to manifest root hashes, enabling $O(1)$ pre-validation filtering before decoder memory allocation.
- **Standardized 128/256-Bit BIP-39 Hardware Root-of-Trust**: Standard 2,048-word mnemonic entropy generation, PBKDF2-HMAC-SHA512 seed derivation, and SLIP-0010 hierarchical deterministic (HD) key trees.

---

## 2. Two-Tiered Cryptographic Architecture

```
========================================================================================
TIER 1: CONTENT & GOVERNANCE MANIFEST LAYER (Asymmetric & Post-Quantum Secure)
========================================================================================
- Frequency: Sent ONCE per published document / chunk recipe
- Scope: End-to-End authenticity, copyright provenance, long-term integrity (10+ years)
- Primitives:
  * Hybrid Dual Signatures: ML-DSA (Dilithium5, 4595B) + Ed25519 (64B)
  * Confidentiality: ML-KEM-768 Encapsulation of Content Symmetric Keys
  * Commitments: SHA3-256 Merkle Root (R) & PRF Fountain Schedule Seed (K_fountain)
- Overhead: ~7 KB total manifest header (amortized over entire file)

                                        │
                         Binds Merkle Root (R) & PRF Seed (K_fountain)
                                        ▼

========================================================================================
TIER 2: INTRA-MESH TRANSPORT & FOUNTAIN CODEC LAYER (Lightweight & Symmetric Secure)
========================================================================================
- Frequency: Sent with EVERY fountain droplet / network frame (thousands/sec)
- Scope: Hop-by-hop authentication, packet loss recovery, anti-pollution, low latency
- Primitives:
  * Merkle Proof Verification: Constant-time log2(K) SHA3-256 path checking against R
  * Deterministic Seed Schedule: PRF-derived (degree, indices) from (R, seed)
  * Hop Auth: 16/32-byte BLAKE3 / HMAC-SHA3-256 MAC or ephemeral 64-byte Ed25519 sig
- Overhead: 10–34 bytes per droplet (Zero MTU fragmentation, microsecond validation)
========================================================================================
```

### 2.1 Tier 1: Post-Quantum Content Manifest Agility

Tier 1 signatures protect immutable content recipes (`ChunkRecipe`), data manifests, and governance broadcasts.

#### 2.1.1 Supported PQC & Classical Primitives
- **ML-DSA-87 (Dilithium5 - NIST FIPS 204)**:
  - Security Level: Category 5 (AES-256 equivalent post-quantum security).
  - Public Key: $2,592\text{ bytes}$ | Private Key: $4,864\text{ bytes}$ | Signature: $4,595\text{ bytes}$.
  - Target: Primary digital signature for high-assurance document publication and enterprise manifests.
- **ML-DSA-65 (Dilithium3 - NIST FIPS 204)**:
  - Security Level: Category 3 (AES-192 equivalent).
  - Public Key: $1,952\text{ bytes}$ | Private Key: $4,032\text{ bytes}$ | Signature: $3,309\text{ bytes}$.
  - Target: Standard mesh node manifest signing.
- **SPHINCS+-SHA2-128f / 256f (NIST FIPS 205)**:
  - Security Level: Category 1 / 5 Stateless Hash-Based Signatures.
  - Public Key: $32 / 64\text{ bytes}$ | Signature: $17,088 / 49,856\text{ bytes}$.
  - Target: One-to-many broadcast streams (ATSC 3.0 / LEO satellite) with zero state retention requirements.
- **ML-KEM-768 / 1024 (Kyber - NIST FIPS 203)**:
  - Security Level: Category 3 / 5 Lattice-Based Key Encapsulation Mechanism (KEM).
  - Public Key: $1,088 / 1,568\text{ bytes}$ | Ciphertext: $1,088 / 1,568\text{ bytes}$.
  - Target: Encrypted broadcast payload symmetric key wrapping.
- **Ed25519 (Classical Fallback - RFC 8032)**:
  - Security Level: 128-bit classical security.
  - Public Key: $32\text{ bytes}$ | Signature: $64\text{ bytes}$.
  - Target: Constrained IoT edge nodes and legacy dual-signing envelopes.

#### 2.1.2 Hybrid Dual-Signing Envelope Structure
To ensure uninterrupted backward compatibility during the global cryptographic transition, TFP specifies a hybrid dual-signing envelope:

```python
@dataclass(frozen=True)
class HybridSignatureEnvelope:
    suite_id: str                      # e.g., "tfp_pqc_hybrid_v1"
    algorithm_pqc: str                 # "dilithium5" or "sphincs+-sha2-128f"
    algorithm_classical: str           # "ed25519"
    pqc_signature: bytes               # Primary PQC signature bytes
    classical_signature: bytes         # Fallback Ed25519 signature (64 bytes)
    message_digest: bytes              # BLAKE3-256 or SHA3-256 digest of payload
    signer_identity: str               # Author BIP-39 derived master DID
    timestamp_utc: int                 # Unix timestamp (seconds)
```

**Verification Rule**:
- A PQC-capable node verifies `pqc_signature` against `signer_pqc_pubkey`.
- A classical legacy node verifies `classical_signature` against `signer_classical_pubkey`.
- If dual-mode enforcement is flagged (`require_dual=True`), both signatures must validate.

---

## 3. Dynamic Cryptographic Agility Engine (`CryptoAgilityRegistry`)

The `CryptoAgilityRegistry` governs protocol-wide cipher suites, deprecation timelines, and algorithm negotiation:

```
+----------------------------------------------------------------------------------------------------+
|                                  CRYPTO AGILITY REGISTRY SUITES                                    |
+----------------------------------------------------------------------------------------------------+
| Suite ID             | Status       | Signature Scheme | Key Exchange / KEM | Hashing Primitive    |
+----------------------+--------------+------------------+--------------------+----------------------+
| tfp_pqc_v1           | ACTIVE (Def) | ML-DSA-87 (Dili5)| ML-KEM-768 (Kyber) | SHA3-256 / BLAKE3    |
| tfp_pqc_broadcast    | ACTIVE       | SPHINCS+-128f    | ML-KEM-1024        | SHA3-256             |
| tfp_pqc_hybrid_v1    | ACTIVE       | Dili5 + Ed25519  | ML-KEM-768         | SHA3-256 / BLAKE3    |
| tfp_classic_v1       | DEPRECATED   | Ed25519          | X25519             | SHA-256              |
| tfp_legacy_v0        | RETIRED      | ECDSA-P256       | ECDH-P256          | SHA-256              |
+----------------------------------------------------------------------------------------------------+
```

### 3.1 Authenticated Governance Manifest Broadcasts
Cipher suite activation, deprecation, or emergency revocation cannot be executed via unsigned network broadcasts. All suite updates must be cryptographically signed by authorized maintainer keys defined in `GovernanceManifest.json`:

```json
{
  "manifest_version": "4.0.0",
  "governance_epoch": 142,
  "authorized_maintainer_keys": [
    {
      "key_id": "maint_alpha_dili5",
      "algorithm": "dilithium5",
      "public_key_hex": "7a8b...4f1e"
    },
    {
      "key_id": "maint_beta_ed25519",
      "algorithm": "ed25519",
      "public_key_hex": "e3b0...c49b"
    }
  ],
  "active_suites": ["tfp_pqc_v1", "tfp_pqc_broadcast", "tfp_pqc_hybrid_v1"],
  "deprecated_suites": ["tfp_classic_v1"],
  "retired_suites": ["tfp_legacy_v0"],
  "governance_signature": "5c9d...aa12"
}
```

### 3.2 Eradication of Mock Stub Bypasses
All bypass conditionals (`if "<...>" in sig: return True` or `if sig == "stub": return True`) are eradicated. In test or development modes without `liboqs` hardware acceleration, the engine falls back to pure-Python software PQC emulation or authenticated classical Ed25519 cryptography, maintaining strict mathematical integrity.

---

## 4. Authenticated Deterministic PRNG Seed Schedules

### 4.1 Vulnerability: Byzantine Droplet Pollution Attack

In rateless fountain erasure codes, $K$ source symbols $S_0, S_1, \dots, S_{K-1}$ are encoded into $M \ge K$ linear combinations:
$$D_i = \bigoplus_{j \in \mathcal{I}_i} S_j$$
Where $\mathcal{I}_i \subset \{0, \dots, K-1\}$ is the set of source symbol indices chosen for droplet $i$.

**The Vulnerability**:
In unauthenticated fountain codes, encoders generate repair droplets using sequential or unkeyed seeds (`seed = K, K+1, ...`). A Byzantine adversary in a mesh network can forge a single polluted droplet $D_{fake}$ containing arbitrary garbage payload $P_{fake}$ and a fabricated index set $\mathcal{I}_{fake}$.
When the receiver performs Gaussian elimination row reduction:
1. The fake equation is inserted into the decoding matrix: $\sum_{j \in \mathcal{I}_{fake}} x_j = P_{fake}$.
2. As row reduction proceeds, this poisoned row is XORed into multiple legitimate pivot rows.
3. **Every single decoded source symbol becomes corrupted.**
4. After solving, the reconstructed payload fails hash verification, causing complete Denial of Service (DoS) and forcing a full re-transmission.

```
[ Byzantine Attacker ] ──► Injects 1 Poisoned Repair Droplet ──► [ Gaussian Matrix ] ──► 100% Corruption
```

### 4.2 Mathematical Model of Authenticated Seed Schedules

To neutralize droplet pollution attacks, the generation of repair droplet seeds, degrees, and symbol indices is cryptographically bound to the manifest root hash and publisher identity.

```
+----------------------------------------------------------------------------------------------------+
|                               DETERMINISTIC SEED SCHEDULE PIPELINE                                 |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   1. Master Manifest Root Hash (R)  +  Publisher Session Key (S_mesh)                              |
|                         │                                                                          |
|                         ▼                                                                          |
|       K_fountain = HKDF-SHA3-256(R, salt="TFP-V4-FOUNTAIN-SCHEDULE", info=S_mesh)                  |
|                         │                                                                          |
|        ┌────────────────┼────────────────┬────────────────┐                                        |
|        ▼                ▼                ▼                ▼                                        |
|   Droplet i=K      Droplet i=K+1    Droplet i=K+2    Droplet i=K+N                                 |
|        │                │                │                │                                        |
|   2. Seed Expansion:                                                                               |
|      sigma_i = Trunc_64(HMAC-SHA3-256(K_fountain, uint64_be(i)))                                  |
|        │                │                │                │                                        |
|        ▼                ▼                ▼                ▼                                        |
|   3. Robust Soliton Distribution Sampling: PRNG(sigma_i)                                           |
|      - Degree: d_i in [1, K] sampled from mu(d)                                                    |
|      - Indices: I_i subset {0, ..., K-1} deterministically sampled (|I_i| = d_i)                   |
|        │                │                │                │                                        |
|        ▼                ▼                ▼                ▼                                        |
|   4. Encoded Payload:                                                                              |
|      D_i = XOR_{j in I_i} S_j                                                                      |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

#### Step 1: PRF Master Key Derivation
Let $R$ be the $32$-byte SHA3-256 Root Hash from the verified `ChunkRecipe` manifest.  
Let $S_{mesh}$ be the publisher's authenticated identity key.  
The fountain PRF master key $K_{fountain}$ is derived via HKDF-SHA3-256:
$$K_{fountain} = \text{HKDF-SHA3-256}(\text{ikm}=R, \text{salt}=\text{"TFP-V4-FOUNTAIN-SCHEDULE"}, \text{info}=S_{mesh}, \text{length}=32)$$

#### Step 2: PRF Seed Expansion per Repair Index
For any repair droplet sequence index $i \ge K$:
$$\sigma_i = \text{Trunc}_{64}\left(\text{HMAC-SHA3-256}(K_{fountain}, \text{uint64\_be}(i))\right)$$
Where $\text{Trunc}_{64}$ extracts the first 8 bytes as an unsigned 64-bit integer seed.

#### Step 3: Robust Soliton Distribution Sampling
Using a cryptographically deterministic Mersenne / Xoshiro256** PRNG initialized with seed $\sigma_i$:
1. Sample degree $d_i \in [1, K]$ according to the Robust Soliton distribution $\mu(d)$:
   $$\rho(1) = \frac{1}{K}, \quad \rho(d) = \frac{1}{d(d-1)} \quad (\text{for } d = 2, \dots, K)$$
   $$\tau(d) = \begin{cases} \frac{S}{K \cdot d} & \text{for } d = 1, \dots, \frac{K}{S}-1 \\ \frac{S \cdot \ln(S/\delta)}{K} & \text{for } d = \frac{K}{S} \\ 0 & \text{for } d > \frac{K}{S} \end{cases} \quad \text{where } S = c \cdot \ln(K/\delta)\sqrt{K}$$
   $$\mu(d) = \frac{\rho(d) + \tau(d)}{\sum_{j=1}^K (\rho(j) + \tau(j))}$$
2. Sample $d_i$ distinct symbol indices $\mathcal{I}_i \subset \{0, 1, \dots, K-1\}$ by pseudo-random shuffling.

### 4.3 Receiver $O(1)$ Pre-Validation Filter

When a receiver receives a droplet frame $D = (i, \sigma_{recv}, d_{recv}, \mathcal{I}_{recv}, P_{recv})$:
1. The receiver executes the pre-validation predicate:
   $$\sigma_i' = \text{Trunc}_{64}(\text{HMAC-SHA3-256}(K_{fountain}, \text{uint64\_be}(i)))$$
   $$(d_i', \mathcal{I}_i') = \text{SampleDegreeAndIndices}(\sigma_i', K)$$
2. **Pre-Validation Invariant**:
   $$\text{Valid}(D) \iff (\sigma_{recv} == \sigma_i') \land (d_{recv} == d_i') \land (\mathcal{I}_{recv} == \mathcal{I}_i')$$
3. **Execution Guarantee**:
   - If $\text{Valid}(D) == \text{False}$, the droplet is **discarded immediately in $O(1)$ time**.
   - No matrix row is allocated, no Gaussian elimination is performed, and CPU/memory exhaustion is completely prevented.

---

## 5. Standardized BIP-39 Hardware Root-of-Trust

### 5.1 Standard Mnemonic Generation & Bitwise Checksum Validation

TFP adopts the official 2,048-word BIP-39 English standard dictionary (`bip39_words.txt`) for all device identities:

```
+----------------------------------------------------------------------------------------------------+
|                                    BIP-39 ENTROPY & CHECKSUM SPECIFICATION                         |
+----------------------------------------------------------------------------------------------------+
| Parameter             | 128-Bit Security Level (Standard)    | 256-Bit Security Level (High/Enterprise)     |
+-----------------------+--------------------------------------+--------------------------------------+
| Initial Entropy (ENT) | 128 bits (16 bytes CSPRNG)           | 256 bits (32 bytes CSPRNG)           |
| Checksum Length (CS)  | ENT / 32 = 4 bits (SHA-256)          | ENT / 32 = 8 bits (SHA-256)          |
| Total Length (ENT+CS) | 132 bits                             | 264 bits                             |
| Word Count            | 132 / 11 = 12 words                  | 264 / 11 = 24 words                  |
| Dictionary Size       | 2,048 words (11 bits per word)       | 2,048 words (11 bits per word)       |
+----------------------------------------------------------------------------------------------------+
```

#### Checksum Computation & Verification Formula:
$$\text{ChecksumBits} = \text{SHA256}(\text{Entropy})[0 \dots \lceil\text{CS}/8\rceil] \gg (8 - \text{CS})$$
$$\text{BitSequence} = \text{Entropy} \parallel \text{ChecksumBits}$$
$$\text{WordIndex}_k = \text{BitSequence}[11k \dots 11k + 10] \quad (\forall k \in [0, \text{WordCount}-1])$$

On recovery, `validate_mnemonic(mnemonic)` splits the phrase into $11$-bit integers, reconstructs the original entropy and checksum bits, and validates that $\text{SHA256}(\text{Entropy})$ matches the trailing bits. If invalid, it raises `InvalidMnemonicChecksumError`.

### 5.2 Key Stretching via PBKDF2-HMAC-SHA512
The master binary seed ($64\text{ bytes} / 512\text{ bits}$) is derived from the mnemonic and an optional user passphrase:
$$\text{MasterSeed} = \text{PBKDF2-HMAC-SHA512}(\text{password}=\text{NFKD}(\text{mnemonic}), \text{salt}=\text{"mnemonic"} \parallel \text{NFKD}(\text{passphrase}), \text{iterations}=2048, \text{dklen}=64)$$

### 5.3 Hierarchical Deterministic (HD) Key Derivation (SLIP-0010)

Using purpose coin-type `m/44'/9999'/0'/`, TFP derives isolated cryptographic keys across protocol subsystems:

```
                                      [ 512-bit Master Seed ]
                                                 │
                                                 ▼  (SLIP-0010 Ed25519 / Dilithium)
                                      [ Master Root Key: m/ ]
                                                 │
                                                 ▼
                                     [ Purpose / Coin: m/44'/9999'/ ]
                                                 │
                                                 ▼
                                     [ Account Level: m/44'/9999'/0'/ ]
                                                 │
            ┌───────────────────┬────────────────┼───────────────────┬───────────────────┐
            ▼                   ▼                ▼                   ▼                   ▼
       m/44'/9999'/0'/0/0  m/44'/9999'/0'/1/0  m/44'/9999'/0'/2/0  m/44'/9999'/0'/3/0  m/44'/9999'/0'/4/0
      [ Device Identity ]  [ PQC Master Key ]  [ ML-KEM Keypair ]  [ PUF Root Seed ]  [ Mesh Hop PRF ]
        (Ed25519 DID)       (Dilithium5 Seed)   (Kyber768 Seed)     (Enclave Secret)    (Hop Token K_hop)
```

---

## 6. Lightweight Intra-Mesh Hop Authentication Tokens

### 6.1 Token Generation & Verification
For low-latency intermediate mesh forwarding without asymmetric signature overhead:
$$K_{hop} = \text{DeriveKey}(MasterSeed, \text{"m/44'/9999'/0'/4/0"})$$
$$\text{HopToken} = \text{Trunc}_{128}\left(\text{HMAC-SHA3-256}(K_{hop}, \text{Header} \parallel \text{Payload} \parallel \text{SeqCounter})\right)$$

### 6.2 Anti-Replay Protection
Relay nodes maintain a 10,000-element sliding bloom filter and monotonic sequence window. Duplicate `(DeviceID, SeqCounter)` tuples are rejected in $O(1)$ time, preventing broadcast replay attacks.

---
*Authored by the Protocol Architecture & Audit Working Group.*
