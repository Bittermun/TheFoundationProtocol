# The Foundation Protocol (TFP): Multi-Phase Architecture Master Plan (Phases 1–4)

Historical architecture proposal: its approval/readiness labels and performance descriptions are not evidence of current behavior. The current execution order and evidence gates are in [Foundation execution megaplan](../FOUNDATION_MEGAPLAN.md). Retain the phase intentions below as design inputs and reconcile them with measured requirements before implementation.

**Document Classification:** Publication-Grade Architectural Specification & Master Engineering Blueprint  
**Document Version:** 4.0.0-PROD-SPEC  
**Target Platform:** The Foundation Protocol (TFP) Next-Generation Architecture (v3.x Legacy to v4.x Next-Gen)  
**Security & Architecture Working Group:** Protocol Engineering, Security Research, & Systems Architecture Teams  
**Date of Release:** August 2026  
**Status:** Approved for Autonomous Phased Implementation  

---

## 1. Executive Strategic Vision & Architectural Roadmap

The Foundation Protocol (TFP) is a decentralized, post-quantum-resilient content routing, rateless erasure-coded broadcast, and verifiable edge-compute protocol. TFP is engineered to provide uninterrupted global information dissemination, zero-trust data verification, and verifiable edge computation across extreme, high-loss, and adversarial network topologies—spanning Low Earth Orbit (LEO) satellite constellations, terrestrial broadcast spectrum (ATSC 3.0, DVB-T2, 5G MBSFN), ad-hoc wireless mesh swarms, tactical radio channels, intermittent local area networks, and adversarial peer-to-peer (P2P) swarms.

To transition TFP from an advanced research prototype to an enterprise-grade, mission-critical decentralized infrastructure, this Master Plan establishes the definitive technical specifications, system layers, state machines, end-to-end data flows, and migration lifecycle across four sequential phases:

```
===================================================================================================
                             TFP MULTI-PHASE ARCHITECTURE ROADMAP (V3 -> V4)
===================================================================================================
[ PHASE 1: Cryptographic Agility & Mathematical Verification ]
  - Tiered Post-Quantum Cryptography (ML-DSA/Dilithium5, SPHINCS+, ML-KEM/Kyber768)
  - Dual-Signing Hybrid (Ed25519 fallback) + Governance Signed Broadcasts
  - Authenticated Deterministic PRNG Repair Seed Schedules (Anti-Droplet Pollution)
  - Standardized 128/256-bit BIP-39 Hardware Root-of-Trust & SLIP-0010 HD Keypaths
                                  │
                                  ▼
[ PHASE 2: Transport & Resilience Hardening ]
  - SIMD-Accelerated Rateless Fountain Codecs (AVX-512 / AVX2 / ARM NEON)
  - Incremental Upper-Triangular Row Echelon Reduction & Fault-Tolerant Shard Ingestion
  - MTU-Optimized Mesh Wire Framing & ATSC 3.0 LCT Spectrum Encapsulation
  - Dynamic Rateless Swarm Droplet Synthesis & Partition-Tolerant CRDT State Sync
                                  │
                                  ▼
[ PHASE 3: Modular Architecture Decomposition ]
  - Deconstruction of 4,500-line Monolithic Server into Decoupled Microservices:
      * tfp-routed    : Content routing, NDN engine, Nostr/IPFS bridges, spectrum multicast
      * tfp-fountaind : High-throughput SIMD erasure codec daemon & shared-memory ring buffers
      * tfp-authd     : Device enrollment, HABP consensus, CreditLedger & spend nullifiers
  - Isolated SQLite WAL Worker Pools & Dedicated Transaction Serialization
                                  │
                                  ▼
[ PHASE 4: Unified SDK & Sandboxed Runtime ]
  - Typed Isomorphic tfp-sdk Client Library (Sync TFPClient & Async AsyncTFPClient)
  - Capability-Gated Sandboxed Plugin Runtime (tfp_plugin_engine) via Wasmtime & gRPC
  - Memory Quotas (64MB), Strict Execution Timeouts (250ms), Syscall Traps
===================================================================================================
```

---

## 2. Layered System Architecture & Interface Contracts

The Foundation Protocol is organized into six strictly isolated conceptual and operational layers. Each layer communicates with adjacent layers via typed, versioned, and cryptographically verified interface contracts.

```
+----------------------------------------------------------------------------------------------------+
|                                    TFP LAYERED PROTOCOL STACK                                      |
+----------------------------------------------------------------------------------------------------+
| Layer 6: Application & Client SDK Layer                                                            |
|   - Isomorphic tfp-sdk (Sync TFPClient & Async AsyncTFPClient)                                     |
|   - CLI Tooling (tfp_cli), Content Publisher, Local Identity Manager, Stream Player              |
+----------------------------------------------------------------------------------------------------+
| Layer 5: Extensibility & Edge-Compute Layer                                                        |
|   - Capability-Gated WASM Plugin Engine (tfp_plugin_engine via Wasmtime)                         |
|   - Out-of-Process gRPC Sandboxes with seccomp-bpf & cgroups v2 limits                             |
|   - Heterogeneous Attested Byzantine Proofs (HABP 3/5) Compute Verification Engine                 |
+----------------------------------------------------------------------------------------------------+
| Layer 4: Modular Services & Persistence Layer                                                      |
|   - Microservices: tfp-routed (Routing), tfp-fountaind (Codec), tfp-authd (Identity/Ledger)        |
|   - Storage Engine Protocol with Dedicated Write Queue & SQLite WAL Pool                           |
|   - Decoupled Content-Addressed BlobStore & Cryptographic CreditLedger Journal                     |
+----------------------------------------------------------------------------------------------------+
| Layer 3: Content Structure & Cryptographic Agility Layer                                           |
|   - 64-bit FastCDC Content-Defined Chunking & Deterministic ChunkRecipe Generation                 |
|   - Two-Tiered Cryptographic Agility Registry (ML-DSA, SPHINCS+, ML-KEM, Ed25519 Dual Sign)       |
|   - BIP-39 (128/256-bit) Root-of-Trust & SLIP-0010 HD Key Hierarchy                                |
+----------------------------------------------------------------------------------------------------+
| Layer 2: Transport, Codec & State Synchronization Layer                                            |
|   - SIMD-Accelerated GF(2) Rateless Fountain & RFC 6330 RaptorQ Codecs                             |
|   - Authenticated PRF-Driven Deterministic Seed Schedules (Anti-Pollution Gating)                  |
|   - Partition-Tolerant CRDT State Sync & Nostr Kind 30078/30079 Gossip Protocol                    |
+----------------------------------------------------------------------------------------------------+
| Layer 1: Physical & Spectrum Framing Layer                                                         |
|   - MTU-Optimized Binary Framing (1500B Ethernet, 2272B Wi-Fi, 256B Tactical Radio)                |
|   - ATSC 3.0 ROUTE/LCT & 5G MBSFN / DVB-T2 Multicast Spectrum Encapsulators                        |
|   - Zero-Copy POSIX Shared Memory Ring Buffers (/dev/shm)                                          |
+----------------------------------------------------------------------------------------------------+
```

---

## 3. End-to-End Data Flows

### 3.1 Content Ingest, FastCDC Chunking, and Tier 1 Manifest Signing

When raw data is ingested by the protocol, it undergoes content-defined chunking, hierarchical Merkle hashing, and post-quantum digital signing:

```
[Raw Payload Stream (Size N)]
            │
            ▼
[FastCDC 64-bit Gear Rolling Hash]
 ├── Computes H_{t+1} = ((H_t << 1) + G[b_t]) mod 2^64
 ├── Dual-Mask Normalization (Region A: Strict Mask, Region B: Relaxed Mask)
 └── Splits into variable-length chunks C_0, C_1, ..., C_{M-1} (Avg 64KB)
            │
            ▼
[Chunk Processing & RFC 6962 Domain-Separated Hashing]
 ├── Leaf Hashes: h_i = SHA3-256(0x00 || C_i)
 ├── Recipe Root Hash: R = SHA3-256(h_0 || h_1 || ... || h_{M-1})
 └── Constructs Binary Merkle Tree: Node = SHA3-256(0x01 || Left || Right)
            │
            ▼
[Tier 1 Manifest Construction & Dual-Signing]
 ├── Encapsulates root_hash, total_size, chunk_hashes, chunk_sizes, metadata
 ├── Primary Signature: ML-DSA-87 (Dilithium5, 4,595 bytes)
 ├── Classical Fallback Signature: Ed25519 (64 bytes)
 └── Binds Fountain PRF Master Key: K_fountain = HKDF-SHA3-256(R, S_mesh)
            │
            ▼
[Signed ChunkRecipe Manifest Broadcast via Nostr Kind 30078 / NDN]
```

### 3.2 Transport Framing, Fountain Encoding, and Anti-Pollution Mesh Dissemination

For delivery over high-loss channels, chunks or whole payloads are partitioned into $K$ source symbols and expanded ratelessly into $M \ge K$ droplets:

```
[Source Symbols S_0, ..., S_{K-1} (Symbol Size S)]
            │
            ▼
[Deterministic PRF Seed Schedule Derivation]
 ├── For systematic symbol i in [0, K-1]: degree d=1, indices=[i], payload=S_i
 ├── For repair symbol i >= K:
 │    ├── Seed sigma_i = Trunc_64(HMAC-SHA3-256(K_fountain, uint64_be(i)))
 │    ├── Robust Soliton PRNG(sigma_i) samples degree d_i in [1, K]
 │    ├── Deterministically samples distinct indices I_i subset {0, ..., K-1}
 │    └── Vectorized GF(2) XOR: Payload D_i = XOR_{j in I_i} S_j (AVX-512 / NEON)
            │
            ▼
[Wire Framing & Tier 2 Hop Tokenization]
 ├── 16-Byte Header: [Payload Size (uint64) | Source K (uint32) | Symbol ID (uint32)]
 ├── Robust Soliton Indices Bitmask
 ├── Symbol Payload Data (S bytes)
 ├── RFC 6962 Merkle Leaf Inclusion Proof Path
 └── Lightweight Intra-Mesh Hop Tag: HMAC-SHA3-256(K_hop, FrameHeader || Payload)
            │
            ▼
[Physical Broadcast / LCT Encapsulation / Ad-Hoc Mesh Dissemination]
```

### 3.3 Zero-Trust Ingestion, Anti-Pollution Gating, and Gaussian Elimination

At the receiving node, incoming droplets are evaluated through an $O(1)$ pre-validation filter before allocating decoder matrix memory:

```
[Incoming Droplet Wire Frame]
            │
            ▼
[Tier 2 Hop Integrity & Rate-Limit Check]
 ├── Verify HMAC-SHA3-256 hop token against neighbor shared secret
 └── Reject malformed headers or replay sequence counters
            │
            ▼
[O(1) Anti-Pollution Pre-Validation Filter]
 ├── Compute expected seed: sigma_i' = Trunc_64(HMAC-SHA3-256(K_fountain, i))
 ├── Recompute expected degree d_i' and indices I_i' via Robust Soliton PRNG(sigma_i')
 ├── Assert received (sigma_i, d_i, I_i) == (sigma_i', d_i', I_i')
 └── IF MISMATCH: DROP IMMEDIATELY (Zero matrix pollution possible)
            │
            ▼
[Incremental Upper-Triangular Row Echelon Reduction]
 ├── Insert verified equation row into GF(2) active matrix
 ├── Perform SIMD-accelerated row XOR reduction against existing pivot rows
 ├── IF new pivot established: increment Rank (pivots_found += 1)
 └── IF Rank == K: Trigger Final Back-Substitution
            │
            ▼
[Source Symbols S_0, ..., S_{K-1} Reconstructed]
            │
            ▼
[Tier 1 Content Manifest Hash & PQC Verification]
 ├── Recompute SHA3-256(Reconstructed) == Manifest.root_hash
 ├── Verify ML-DSA-87 / Ed25519 manifest signature
 └── Commit verified blob to local BlobStore & notify upper applications
```

---

## 4. Formal Protocol State Machines

### 4.1 Node Lifecycle & Swarm State Machine

A TFP node operates under an autonomous state machine managing identity provisioning, peer mesh discovery, recipe synchronization, and partition healing:

```
       +-------------------------------------------------------------+
       |                     UNINITIALIZED (0x00)                    |
       +-------------------------------------------------------------+
                                      │
                                      │  Load/Generate 128/256-bit BIP-39 Mnemonic
                                      │  Derive SLIP-0010 Keys (Ed25519 & Dilithium5)
                                      ▼
       +-------------------------------------------------------------+
       |                     PROVISIONED (0x01)                      |
       +-------------------------------------------------------------+
                                      │
                                      │  Bind local transport sockets (TCP/UDP/LCT)
                                      │  Broadcast Nostr Kind 30078 Hello beacon
                                      ▼
       +-------------------------------------------------------------+
       |                      DISCOVERY (0x02)                       |
       +-------------------------------------------------------------+
                                      │
                                      │  Peer Handshake verified (Tier 2 Hop Auth)
                                      │  Active Neighbors >= 1
                                      ▼
       +-------------------------------------------------------------+
       |                    SYNCHRONIZED (0x03)                      |
       +-------------------------------------------------------------+
                       │                             ▲
      Mesh Partition   │                             │  Gossip anti-entropy sync
      Detected         │                             │  Link re-established
      (Neighbors == 0) │                             │  Merkle diff resolved
                       ▼                             │
       +-------------------------------------------------------------+
       |                     ISOLATED (0x04)                         |
       |  - Continue local storage & HABP consensus                  |
       |  - Buffer outgoing receipts & gossip events                 |
       +-------------------------------------------------------------+
```

### 4.2 Fountain Codec Decoder State Machine

The rateless fountain decoder maintains an incremental decoding state machine to prevent $O(K^3 \cdot S)$ CPU exhaustion:

| State | State Code | Entry Condition | Action / Invariant | Exit Transition |
|---|---|---|---|---|
| **INIT** | `0x10` | Session created with $K$ source symbols and $R$ root hash | Allocate $K \times K$ pivot bitmask table and empty symbol buffer array | First valid droplet received $\to$ **INGESTING** |
| **INGESTING** | `0x11` | Droplet passes $O(1)$ anti-pollution check | Perform SIMD incremental row reduction against current pivot table | $\text{rank} < K \to$ **INGESTING**<br>$\text{rank} == K \to$ **SOLVING** |
| **SOLVING** | `0x12` | Matrix rank equals $K$ | Execute back-substitution across upper-triangular matrix | Matrix fully reduced $\to$ **VERIFYING**<br>Singular error $\to$ **FAILED** |
| **VERIFYING** | `0x13` | Back-substitution complete | Verify RFC 6962 Merkle tree root matches expected $R$ | Root match $\to$ **COMPLETE**<br>Hash mismatch $\to$ **FAILED** |
| **COMPLETE** | `0x14` | Reconstructed payload verified | Reconstruct payload stream; deliver to storage; free decoding buffers | Terminal state |
| **FAILED** | `0x1F` | Unrecoverable corruption / timeout | Flush corrupted session; log security audit event; notify routing daemon | Session reset $\to$ **INIT** |

### 4.3 HABP Task Verification & Economic Lifecycle State Machine

Edge compute tasks progress through a 5-stage Byzantine-fault-tolerant lifecycle ensuring economic conservation:

```
    [ Task Creation & Bid ]
               │
               ▼
    [ Assigned to 3+ Enclaves ]
               │
               ▼
    [ Execution & Output Attestation ]
               │
               ▼
    [ HABP 3/5 Consensus Gating ] ──(Proof Mismatch / Sybil)──► [ Slashed & Discarded ]
               │
               ▼
    [ Spend Nullifier Journaling ]
               │
               ▼
    [ Credit Minted (<= 21M DWCC Cap) ]
```

---

## 5. Architectural Sequence Diagrams

### 5.1 Content Publishing, PQC Manifest Signing, and Multi-Hop Mesh Transport

```
+--------+       +------------+       +---------------+       +------------+       +-----------+
| Client |       | tfp-routed |       | tfp-fountaind |       | tfp-authd  |       | Mesh Swarm|
+--------+       +------------+       +---------------+       +------------+       +-----------+
    │                   │                     │                     │                    │
    │ 1. Publish(Data)  │                     │                     │                    │
    ├──────────────────►│                     │                     │                    │
    │                   │ 2. FastCDC Chunks   │                     │                    │
    │                   │    & Merkle Root R  │                     │                    │
    │                   │─────────────────────│                     │                    │
    │                   │                                           │                    │
    │                   │ 3. SignManifest(R, PQC_ML_DSA_87)         │                    │
    │                   ├──────────────────────────────────────────►│                    │
    │                   │ 4. Signature(Dilithium5 + Ed25519)        │                    │
    │                   │◄──────────────────────────────────────────┤                    │
    │                   │                                           │                    │
    │                   │ 5. EncodeFountain(Chunks, K_fountain)     │                    │
    │                   ├────────────────────►│                     │                    │
    │                   │ 6. Droplet Stream   │                     │                    │
    │                   │    (Systematic+Rep) │                     │                    │
    │                   │◄────────────────────┤                     │                    │
    │                   │                                           │                    │
    │                   │ 7. Gossip Recipe (Nostr Kind 30078)       │                    │
    │                   ├───────────────────────────────────────────────────────────────►│
    │                   │ 8. Broadcast Droplet Frames (LCT / UDP Mesh)                  │
    │                   ├───────────────────────────────────────────────────────────────►│
    │ 9. Recipe & CID   │                                           │                    │
    │◄──────────────────┤                                           │                    │
    │                   │                                           │                    │
```

### 5.2 Byzantine Droplet Pollution Attack Mitigation Flow

```
+--------------------+       +---------------+       +------------------+       +---------------+
| Byzantine Adversary|       | Mesh Ingress  |       | Anti-Pollution   |       | Incremental   |
|                    |       | Rate-Limiter  |       | Pre-Validator    |       | GF(2) Matrix  |
+--------------------+       +---------------+       +------------------+       +---------------+
          │                          │                         │                        │
          │ 1. Transmit Poisoned     │                         │                        │
          │    Repair Droplet        │                         │                        │
          │    (Forged Equation)     │                         │                        │
          ├─────────────────────────►│                         │                        │
          │                          │ 2. Inspect Header & Hop │                        │
          │                          ├────────────────────────►│                        │
          │                          │                         │ 3. Compute expected    │
          │                          │                         │    sigma_i' from       │
          │                          │                         │    PRF(K_fountain, i)  │
          │                          │                         │                        │
          │                          │                         │ 4. Recompute expected  │
          │                          │                         │    Degree & Indices    │
          │                          │                         │                        │
          │                          │                         │ 5. Expected != Received│
          │                          │                         │    [ATTACK DETECTED]   │
          │                          │                         │                        │
          │                          │                         │ 6. DROP FRAME (O(1))   │
          │                          │                         │───┐                    │
          │                          │                         │   │ Log Threat         │
          │                          │                         │◄──┘                    │
          │                          │                         │                        │
          │                          │                         │ [NO INSERTION]         │
          │                          │                         │ ─────────────────────X │
          │                          │                         │                        │
```

### 5.3 Partition-Tolerant Dynamic Rateless Droplet Synthesis

```
+-------------------+       +-------------------+       +-------------------+       +-------------------+
| Node A (Origin)   |       | Node B (Relay)    |       | Link Interruption |       | Node C (Consumer) |
+-------------------+       +-------------------+       +-------------------+       +-------------------+
          │                           │                                                       │
          │ 1. Transmit Droplets      │                                                       │
          │    (Seeds 0..K+10)        │                                                       │
          ├──────────────────────────►│                                                       │
          │                           │ 2. Gaussian Decode Complete                           │
          │                           │    Payload Reconstructed                              │
          │                           │                                                       │
          │                           │ ═════════════════════════════════════════════════════ │
          │                           │ [ PARTITION EVENT: Node A disconnected from Node C ] │
          │                           │ ═════════════════════════════════════════════════════ │
          │                           │                                                       │
          │                           │ 3. Request Content (R)                                │
          │                           │◄──────────────────────────────────────────────────────┤
          │                           │                                                       │
          │                           │ 4. Dynamic Synthesis:                                 │
          │                           │    Generate fresh seeds sigma_j (j >= K+20)           │
          │                           │    from K_fountain PRF                                │
          │                           │                                                       │
          │                           │ 5. Stream Fresh Droplets                              │
          │                           ├──────────────────────────────────────────────────────►│
          │                           │                                                       │
          │                           │                                                       │ 6. Full Recovery
          │                           │                                                       │    (100% Bit-Exact)
```

### 5.4 Microservice IPC Request Processing Pipeline

```
+------------+            +------------+            +---------------+            +------------+
| API Client |            | tfp-routed |            | tfp-fountaind |            | tfp-authd  |
+------------+            +------------+            +---------------+            +------------+
      │                         │                          │                            │
      │ 1. GET /api/stream/{cid}│                          │                            │
      ├────────────────────────►│                          │                            │
      │                         │ 2. Query Blob & Recipe   │                            │
      │                         │    (Storage Engine)      │                            │
      │                         │─────────────────────────┐│                            │
      │                         │                         ││                            │
      │                         │◄────────────────────────┘│                            │
      │                         │                                                       │
      │                         │ 3. Allocate Shared Ring Buffer (/dev/shm/fountain_01) │
      │                         │──────────────────────────────────────────────────────┐│
      │                         │                                                      ││
      │                         │◄─────────────────────────────────────────────────────┘│
      │                         │                                                       │
      │                         │ 4. gRPC EncodeJob(shm_key, K=64, redundancy=1.5)      │
      │                         ├─────────────────────────►│                            │
      │                         │                          │ 5. AVX-512 GF(2) Encode    │
      │                         │                          │    Write symbols to SHM    │
      │                         │                          │───────────────────────────┐│
      │                         │                          │                           ││
      │                         │                          │◄──────────────────────────┘│
      │                         │ 6. EncodeComplete(num_symbols=96)                     │
      │                         │◄─────────────────────────┤                            │
      │                         │                                                       │
      │                         │ 7. Authenticate Client Token                          │
      │                         ├──────────────────────────────────────────────────────►│
      │                         │ 8. Token Validated (Device OK)                        │
      │                         │◄──────────────────────────────────────────────────────┤
      │ 9. HTTP Chunked Stream  │                                                       │
      │    (Framed Droplets)    │                                                       │
      │◄────────────────────────┤                                                       │
```

### 5.5 WASM Plugin Execution Lifecycle with Capability Traps

```
+------------+            +-------------------+            +------------------+            +------------+
| Event Ingest|           | Plugin Gatekeeper |            | Wasmtime Sandbox |            | Host Engine|
+------------+            +-------------------+            +------------------+            +------------+
      │                             │                               │                             │
      │ 1. Trigger ON_CONTENT_INGEST│                               │                             │
      ├────────────────────────────►│                               │                             │
      │                             │ 2. Check plugin.yaml Manifest │                             │
      │                             │    - Memory quota <= 64MB     │                             │
      │                             │    - Timeout <= 250ms         │                             │
      │                             │    - System syscalls denied   │                             │
      │                             │───────────────────────────────│                             │
      │                             │                               │                             │
      │                             │ 3. Invoke handle_content(ptr) │                             │
      │                             ├──────────────────────────────►│                             │
      │                             │                               │ 4. Plugin attempts          │
      │                             │                               │    illegal file open()      │
      │                             │                               │────────────────────────────►│
      │                             │                               │                             │ 5. WASI Host Trap:
      │                             │                               │                             │    Access Denied!
      │                             │                               │◄────────────────────────────┤
      │                             │                               │                             │
      │                             │ 6. Trap Caught / Terminated   │                             │
      │                             │◄──────────────────────────────┤                             │
      │                             │                               │                             │
      │                             │ 7. Fallback to Safe Pipeline  │                             │
      │                             │───────────────────────────────│                             │
```

---

## 6. Microservice Decomposition Blueprint (Phase 3)

The monolithic node implementation (`tfp_demo/server.py`) is decoupled into three dedicated, highly optimized system daemons communicating over zero-copy IPC and gRPC:

```
+----------------------------------------------------------------------------------------------------+
|                                    TFP SYSTEM DAEMON TOPOLOGY                                      |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|    +-------------------------+    +-------------------------+    +-------------------------+       |
|    |       tfp-routed        |    |      tfp-fountaind      |    |        tfp-authd        |       |
|    +-------------------------+    +-------------------------+    +-------------------------+       |
|    | - FastCDC Chunker Engine|    | - AVX-512 / NEON GF(2)  |    | - BIP-39 / SLIP-0010 HD |       |
|    | - NDN Interest Router   |    | - Incremental Gaussian  |    | - PQC ML-DSA Agility    |       |
|    | - Nostr NIP-01/77 Sync  |    | - Shared-Memory Buffer  |    | - HABP 3/5 Consensus    |       |
|    | - ATSC 3.0 LCT Spectrum |    | - RaptorQ C-FFI Worker  |    | - CreditLedger Journal  |       |
|    | - IPFS Kubo RPC Bridge  |    | - Droplet Pool Cache    |    | - Spend Nullifier Set   |       |
|    +-------------------------+    +-------------------------+    +-------------------------+       |
|                 │                              │                              │                    |
|                 │ gRPC / Unix Domain Sockets   │ Zero-Copy Shared Memory Ring │ gRPC / UDS         |
|                 └──────────────────────────────┼──────────────────────────────┘                    |
|                                                ▼                                                   |
|                      +---------------------------------------------------+                         |
|                      |             Isolated Storage WAL Worker           |                         |
|                      | - Async SQLite Connection Pool (WAL Mode)         |                         |
|                      | - Dedicated Write Transaction Serializer Queue    |                         |
|                      | - Content-Addressed Sharded BlobStore             |                         |
|                      | - Automated PRAGMA wal_checkpoint(TRUNCATE)       |                         |
|                      +---------------------------------------------------+                         |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

## 7. Unified SDK & Sandboxed Runtime Blueprint (Phase 4)

### 7.1 Isomorphic Typed SDK Client

The `tfp-sdk` provides an isomorphic, typed interface supporting synchronous and asynchronous execution environments:

```
                  +--------------------------------------------------+
                  |                     tfp-sdk                      |
                  +--------------------------------------------------+
                                   /                \
                                  /                  \
                                 ▼                    ▼
               +--------------------+      +-----------------------+
               |     TFPClient      |      |     AsyncTFPClient    |
               | (Synchronous API)  |      |   (AsyncIO / Native)  |
               +--------------------+      +-----------------------+
                         │                             │
                         ▼                             ▼
               +---------------------------------------------------+
               |             Unified SDK Core Engine               |
               | - Client-side FastCDC 64-bit Chunking             |
               | - Transparent Tier 1 PQC Signature Validation     |
               | - Connection Pool & HTTP/2 Multiplexing           |
               | - Circuit Breaker & Exponential Jitter Retries    |
               | - Streaming Rateless Fountain Codec Assembler     |
               +---------------------------------------------------+
```

### 7.2 WASM Capability-Gated Plugin Engine (`tfp_plugin_engine`)

Untrusted third-party edge-compute plugins execute inside a capability-gated WebAssembly sandbox powered by `wasmtime`:

```
+----------------------------------------------------------------------------------------------------+
|                                    WASM PLUGIN SANDBOX RUNTIME                                     |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   [ Plugin Manifest (plugin.yaml) ]                                                                |
|     ├── Declares required permissions: network, storage quota, compute timeout                     |
|     └── Node Security Policy verifies signature and capability bounds                              |
|                                                                                                    |
|   [ Wasmtime Linear Memory Sandbox ]                                                               |
|     ├── Hardware memory limit: strictly capped at 64 MB                                            |
|     ├── Execution timeout guard: interrupt trigger fires at 250 ms                                 |
|     └── Custom WASI Import Table: intercepts illegal syscalls & file system access                 |
|                                                                                                    |
|   [ Event Interception Pipeline ]                                                                  |
|     ├── ON_CONTENT_INGEST     : Transform / filter content blobs before indexing                   |
|     ├── ON_SHARD_RECEIVED     : Inspect / forward raw transport shards                             |
|     ├── ON_TASK_BID           : Autonomous bidding on HABP edge-compute tasks                      |
|     └── ON_ACCESS_REQUEST     : Evaluate dynamic zero-trust access control policies                |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

---

## 8. Cross-Phase Dependency & Migration Lifecycle

```
+----------------------------------------------------------------------------------------------------+
| PROTOCOL TRANSITION MATRIX                                                                         |
+----------------------------------------------------------------------------------------------------+
| PHASE 1: Cryptographic Agility & Mathematical Verification                                         |
|   - Output Artifacts: tfp_core/crypto/bip39.py, tfp_core/crypto/manifest_agility.py,               |
|                       tfp_core/fountain.py (Authenticated PRF Schedules)                           |
|   - Invariant Established: Zero droplet pollution, BIP-39 root-of-trust, PQC dual-signing.        |
|   - Backward Compatibility: Dual-signing envelope supports classical Ed25519 nodes.                |
|                                                                                                    |
| PHASE 2: Transport & Resilience Hardening                                                          |
|   - Dependencies: Phase 1 PRF seeds and Merkle trees.                                              |
|   - Output Artifacts: tfp_transport/simd_fountain.py, tfp_transport/spectrum_encap.py,             |
|                       tfp_core/crdt_sync.py                                                        |
|   - Invariant Established: 100% bit-exact recovery under 50% packet drop; 2GB/s SIMD decode.       |
|                                                                                                    |
| PHASE 3: Modular Architecture Decomposition                                                        |
|   - Dependencies: Phase 1 & 2 transport and cryptographic engines.                                 |
|   - Output Artifacts: tfp_server/routed/, tfp_server/fountaind/, tfp_server/authd/,               |
|                       tfp_storage/wal_pool.py                                                      |
|   - Invariant Established: Zero SQLite lock contention under 100 threads; microservice IPC.        |
|                                                                                                    |
| PHASE 4: Unified SDK & Sandboxed Runtime                                                           |
|   - Dependencies: Phase 3 microservices and gRPC schemas.                                         |
|   - Output Artifacts: tfp_sdk/, tfp_plugin_engine/                                                 |
|   - Invariant Established: Capability-gated WASM sandbox (64MB / 250ms), isomorphic SDK.           |
+----------------------------------------------------------------------------------------------------+
```

---
*Authored by the Protocol Architecture & Audit Working Group.*
