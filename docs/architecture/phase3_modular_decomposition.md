# The Foundation Protocol (TFP): Phase 3 — Modular Architecture Decomposition Specification

**Document Classification:** Publication-Grade Architectural Specification & Systems Engineering Standard  
**Document Version:** 4.3.0-MODULAR-SPEC  
**Target Platform:** The Foundation Protocol (TFP) Microservices & Core Storage Architecture  
**Working Group:** Distributed Systems, Microservices & Database Infrastructure Working Group  
**Date of Release:** August 2026  
**Status:** Approved for Implementation  

---

## 1. Executive Summary & Decomposition Scope

The Foundation Protocol (TFP) v3.x prototype relied on a single 4,500-line monolithic server process (`tfp_demo/server.py`). While effective for initial concept demonstrations, this monolithic architecture exhibits critical bottlenecks in production:
1. **Thread Contention & Lock Serialization**: HTTP request handling, computationally intensive SIMD fountain coding, cryptographic verification, and SQLite database writes execute within a shared Python GIL process, leading to frequent lock timeouts and high tail latency under concurrent load.
2. **Failure Cascades**: An unexpected crash or memory fault in fountain decoding or external IPFS RPC bridges halts the entire node, including device authentication and routing.
3. **Rigid Resource Allocation**: High-performance CPU-bound tasks (fountain erasure coding) cannot be scaled independently from I/O-bound tasks (NDN routing and Nostr gossip sync).

Phase 3 decomposes the monolithic server into three isolated, independently scalable microservices communicating over zero-copy Inter-Process Communication (IPC) and gRPC, backed by an asynchronous connection-pooled storage engine with dedicated Write-Ahead Logging (WAL) queue workers:

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

## 2. Microservice Specifications & Subsystem Boundaries

### 2.1 `tfp-routed` (Content Routing, Discovery & Spectrum Ingress)
- **Role**: High-concurrency network ingress and routing daemon.
- **Key Responsibilities**:
  - Exposes external REST API endpoints (`/api/publish`, `/api/get`, `/api/tags`, `/api/stream`).
  - Implements Named Data Networking (NDN) Interest/Data packet pipeline, FIB (Forwarding Information Base), and PIT (Pending Interest Table).
  - Bridges with Nostr relays (NIP-01, NIP-77) and IPFS Kubo nodes via asynchronous HTTP/2 RPC.
  - Manages physical spectrum multicast encapsulation (ATSC 3.0 LCT and 5G MBSFN).
  - Executes client-side and edge FastCDC 64-bit chunking and `ChunkRecipe` manifest assembly.
- **Resource Profile**: Asynchronous I/O-bound (asyncio / epoll), lightweight memory footprint (< 128 MB RAM).

### 2.2 `tfp-fountaind` (High-Throughput SIMD Erasure Coding Engine)
- **Role**: Dedicated computational worker daemon for rateless erasure encoding and decoding.
- **Key Responsibilities**:
  - Implements vectorized GF(2) linear combination kernels (AVX-512, AVX2, ARM NEON).
  - Executes online incremental upper-triangular Gaussian elimination decoding.
  - Generates deterministic PRF repair droplet seed schedules ($seed \ge K$).
  - Operates over POSIX shared memory ring buffers (`/dev/shm`), eliminating IPC serialization and memory copy overhead (Fix for LOW-06).
- **Resource Profile**: CPU-bound, vectorized SIMD execution, lock-free ring buffer memory allocation.

### 2.3 `tfp-authd` (Identity Verification, HABP Consensus & Economic Ledger)
- **Role**: Trust anchor, device registry, Byzantine consensus, and cryptographic ledger daemon.
- **Key Responsibilities**:
  - Handles `/api/enroll`, `/api/tasks`, `/api/earn`, and `/api/habp/verify`.
  - Verifies BIP-39 / PUF device identity signatures and Tier 1 PQC manifest signatures.
  - Evaluates Heterogeneous Attested Byzantine Proofs (HABP 3/5 consensus) before credit minting (Fix for HIGH-03).
  - Maintains `CreditLedger` with cryptographic spend nullifiers (`_spent_receipts`) and hash-chain transaction journaling (Fix for HIGH-02).
  - Enforces the global supply ceiling ($21,000,000\text{ DWCC}$) and distributed sliding-window rate limiters.
- **Resource Profile**: High-security, constant-time cryptographic execution, transactional persistence.

---

## 3. Inter-Process Communication (IPC) & gRPC Interface Contracts

Microservices communicate locally via Unix Domain Sockets (UDS) using Protocol Buffers v3 and high-performance gRPC streams.

### 3.1 Protocol Buffer Definitions

```protobuf
syntax = "proto3";

package tfp.protocol.v4;

// ============================================================================
// Service 1: tfp-routed Interface
// ============================================================================
service RoutedService {
  rpc PublishContent (PublishRequest) returns (PublishResponse);
  rpc GetContent (GetContentRequest) returns (stream ContentChunk);
  rpc QueryTags (TagQueryRequest) returns (TagQueryResponse);
}

message PublishRequest {
  bytes payload = 1;
  string content_type = 2;
  string author_did = 3;
  bytes author_signature = 4;
}

message PublishResponse {
  string cid = 1;
  string root_hash = 2;
  uint64 total_size = 3;
  uint32 total_chunks = 4;
  repeated string chunk_hashes = 5;
}

message GetContentRequest {
  string root_hash = 1;
  uint32 max_hops = 2;
}

message ContentChunk {
  string chunk_hash = 1;
  uint32 chunk_index = 2;
  bytes data = 3;
  bytes merkle_proof = 4;
}

message TagQueryRequest {
  string tag = 1;
  uint32 limit = 2;
}

message TagQueryResponse {
  repeated string matching_cids = 1;
}

// ============================================================================
// Service 2: tfp-fountaind Interface (Zero-Copy Shared Memory)
// ============================================================================
service FountainService {
  rpc EncodeFountainJob (FountainEncodeRequest) returns (FountainEncodeResponse);
  rpc IngestDropletStream (stream DropletFrame) returns (FountainDecodeResponse);
}

message FountainEncodeRequest {
  string shm_buffer_key = 1;       // Key to POSIX /dev/shm ring buffer
  uint64 payload_length = 2;
  uint32 symbol_size = 3;
  float redundancy_ratio = 4;
  bytes root_hash = 5;
  bytes session_nonce = 6;
}

message FountainEncodeResponse {
  uint32 source_symbols_k = 1;
  uint32 total_droplets = 2;
  string output_shm_key = 3;
}

message DropletFrame {
  uint64 original_size = 1;
  uint32 source_k = 2;
  uint32 symbol_id = 3;
  uint32 degree = 4;
  repeated uint32 source_indices = 5;
  bytes payload = 6;
  bytes merkle_proof = 7;
}

message FountainDecodeResponse {
  bool success = 1;
  uint32 rank = 2;
  string reconstructed_shm_key = 3;
  bytes computed_root_hash = 4;
}

// ============================================================================
// Service 3: tfp-authd Interface (Identity & Ledger)
// ============================================================================
service AuthdService {
  rpc EnrollDevice (EnrollRequest) returns (EnrollResponse);
  rpc VerifyExecutionProof (HABPProofSubmission) returns (HABPConsensusResult);
  rpc TransferCredits (CreditTransferRequest) returns (CreditTransferResponse);
}

message EnrollRequest {
  string device_id = 1;
  string bip39_pubkey = 2;
  bytes attestation_quote = 3;
  int64 timestamp = 4;
  bytes signature = 5;
}

message EnrollResponse {
  bool enrolled = 1;
  string session_token = 2;
  uint64 initial_balance = 3;
}

message HABPProofSubmission {
  string task_id = 1;
  string device_id = 2;
  bytes execution_output_hash = 3;
  bytes enclave_attestation = 4;
  bytes signature = 5;
}

message HABPConsensusResult {
  string task_id = 1;
  bool consensus_reached = 2;
  uint32 matching_proofs = 3;
  uint64 reward_minted_dwcc = 4;
  repeated string rewarded_devices = 5;
}

message CreditTransferRequest {
  string sender_did = 1;
  string recipient_did = 2;
  uint64 amount_dwcc = 3;
  string receipt_nullifier = 4;
  bytes signature = 5;
}

message CreditTransferResponse {
  bool success = 1;
  string transaction_chain_hash = 2;
  uint64 sender_new_balance = 3;
}
```

---

## 4. Asynchronous Connection Pooling & Database Storage Isolation

### 4.1 Storage Engine Protocol (`StorageEngine`)

The data access layer is cleanly decoupled from underlying database engines via an abstract Python protocol:

```python
from typing import Protocol, Optional, List, Dict, Any

class StorageEngine(Protocol):
    async def get_blob(self, content_hash: str) -> Optional[bytes]: ...
    async def put_blob(self, content_hash: str, data: bytes) -> bool: ...
    async def get_recipe(self, root_hash: str) -> Optional[Dict[str, Any]]: ...
    async def put_recipe(self, root_hash: str, recipe_data: Dict[str, Any]) -> bool: ...
    async def get_device(self, device_id: str) -> Optional[Dict[str, Any]]: ...
    async def append_ledger_tx(self, tx_data: Dict[str, Any]) -> str: ...
    async def check_and_nullify_receipt(self, receipt_hash: str) -> bool: ...
```

### 4.2 Dedicated Write Queue & SQLite WAL Pool

To eliminate SQLite lock timeouts (`sqlite3.OperationalError: database is locked`) under 100+ concurrent worker threads:

```
+----------------------------------------------------------------------------------------------------+
|                                  STORAGE ENGINE WORKER POOL                                        |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|    Concurrent Readers (100+ Threads) ───────► Read Pool (50 async read-only SQLite connections)   |
|                                                                                                    |
|    Concurrent Writers (100+ Threads) ───────► Dedicated FIFO Write Queue (asyncio.Queue)          |
|                                                              │                                     |
|                                                              ▼                                     |
|                                                  Single Serialized Writer Thread                   |
|                                                  (Exclusively holds BEGIN IMMEDIATE)               |
|                                                              │                                     |
|                                                              ▼                                     |
|                                                  SQLite WAL Journal File (state.db-wal)            |
|                                                              │                                     |
|                                                              ▼                                     |
|                                                  Periodic Background Worker:                       |
|                                                  PRAGMA wal_checkpoint(TRUNCATE)                   |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

### 4.3 Database Schema Migration (`V001__migrate_v3_to_v4_storage.sql`)

```sql
-- Migration V001: Normalize v3 tables into v4 indexed architecture
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    bip39_pubkey TEXT NOT NULL,
    puf_entropy_hash TEXT NOT NULL,
    enrolled_at INTEGER NOT NULL,
    reputation_score REAL DEFAULT 1.0,
    attestation_data BLOB
);

CREATE TABLE IF NOT EXISTS recipes (
    root_hash TEXT PRIMARY KEY,
    total_size INTEGER NOT NULL,
    chunk_count INTEGER NOT NULL,
    recipe_json TEXT NOT NULL,
    pqc_signature BLOB,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    reward_dwcc INTEGER NOT NULL,
    assigned_device_id TEXT,
    completed_at INTEGER
);

CREATE TABLE IF NOT EXISTS credit_ledger (
    chain_index INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash TEXT UNIQUE NOT NULL,
    prev_hash TEXT NOT NULL,
    device_id TEXT NOT NULL,
    amount_dwcc INTEGER NOT NULL,
    receipt_nullifier TEXT UNIQUE NOT NULL,
    timestamp INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recipes_created_at ON recipes(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_ledger_device ON credit_ledger(device_id);

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA mmap_size = 268435456; -- 256MB memory mapped I/O
PRAGMA busy_timeout = 10000;  -- 10s timeout

COMMIT;
```

---
*Authored by the Protocol Architecture & Audit Working Group.*
