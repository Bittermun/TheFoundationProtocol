# TFP Architecture Overview (v3.2)

This document describes the design decisions and component interactions in The Foundation Protocol (TFP) v3.2.

## System Stack

The TFP architecture is split between the high-performance **v4 Core** and the **v3 Foundation Client**, providing a bridge between next-generation mesh transport and established protocol interfaces.

| Layer | Component | Evidence / Implementation |
|-------|-----------|---------------------------|
| **Core** | `tfp_core_v4` | Canonical engine featuring FastCDC, XOR-LDPC fountain coding, and Merkle verification. |
| **Identity** | `tfp_core` | BIP-39 Hardware Root-of-Trust with SLIP-0010 multi-subsystem derivation. |
| **Transport** | `tfp_transport` | Loss-tolerant fountain transport with deterministic seed schedules and Merkle integrity. |
| **Security** | `tfp_core/crypto` | Cryptographic agility registry supporting Dilithium5 (PQC) and dual-signature migration. |
| **Legacy API** | `tfp_client` | v3-compatible FastAPI node server, device auth, and content routing. |
| **Persistence** | SQLite (WAL) | Metadata, credit ledgers, and task store persistence. |
| **Discovery** | Nostr | Decentralised gossip for HLT state and content announcements. |

## Key Design Decisions

### 1. XOR-LDPC Fountain Coding
TFP utilizes a rateless fountain codec based on systematic XOR combinations (equivalent to binary LDPC) rather than standard RaptorQ. This allows for bit-exact reconstruction under extreme network conditions (up to 40% packet drop) without the overhead of heavy Reed-Solomon codes.
*   **Verification**: See [fountain_real.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp-foundation-protocol/tfp_client/lib/fountain/fountain_real.py) for the XOR-based Gaussian elimination implementation.

### 2. FastCDC & Merkle Integrity
Content is partitioned using 64-bit Content-Defined Chunking (FastCDC) to maximize deduplication. Each chunk is verified via constant-time SHA3-256 Merkle proofs, providing line-rate defense against Byzantine pollution attacks.
*   **Verification**: See [cdc.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp_core_v4/cdc.py) and [merkle.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp_core_v4/merkle.py).

### 3. Nostr Gossip Protocol
TFP uses Nostr as a decentralized pub/sub layer for network coordination:
- **Kind 30078**: HLT (Hierarchical Lexicon Tree) Merkle-root gossip for semantic drift detection.
- **Kind 30080**: Content-availability announcements (Hash + IPFS CID + Metadata).
- **Kind 30079**: Search index delta gossip.
- **Kind 30081**: Supply ledger gossip for multi-node credit coordination.
- **Kind 30082**: Peer announcements for P2P mesh discovery and route propagation.
*   **Verification**: Defined in [nostr_bridge.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp-foundation-protocol/tfp_client/lib/bridges/nostr_bridge.py).

### 5. P2P Mesh Networking
TFP implements a decentralized peer-to-peer mesh network for content distribution and resilience:
- **Peer Discovery**: Secure peer registration with capability exchange (compute, storage, bandwidth) and reputation scoring (0-100 scale).
- **Content Sharding**: Automatic RaptorQ-based content encoding with configurable redundancy (default 3x) for fault tolerance.
- **Mesh Routing**: Dijkstra's algorithm for optimal path finding based on latency, hop count, and route quality. Network self-healing from peer failures.
- **Gossip Protocol**: TTL-based message propagation for peer announcements, content availability, and route updates.
- **Admin Dashboard**: Real-time mesh topology visualization showing connected peers, capabilities, reputation, and routing statistics.
*   **Verification**: See [peer_repository.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp-foundation-protocol/tfp_client/lib/peer/peer_repository.py), [shard_manager.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp-foundation-protocol/tfp_client/lib/distribution/shard_manager.py), [mesh_router.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp-foundation-protocol/tfp_client/lib/routing/mesh_router.py), and [gossip_protocol.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp-foundation-protocol/tfp_client/lib/gossip/gossip_protocol.py).

### 4. PQC Agility & Tiered Manifests
The protocol supports cryptographic agility through a registry that negotiates between Post-Quantum (Dilithium5) and classical (Ed25519) algorithms. Manifests use a tiered approach:
- **Tier 1**: PQC digital signatures for long-term content integrity.
- **Tier 2**: Lightweight HMAC tokens for intra-mesh hop authentication.
*   **Verification**: See [agility_registry.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp_core/crypto/agility_registry.py) and [manifest_agility.py](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp_core/crypto/manifest_agility.py).

## Module Status

### Active Modules
- [tfp_core_v4](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp_core_v4/): Primary high-performance protocol engine.
- [tfp_core](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp_core/): Identity, crypto agility, and compliance wrappers.
- [tfp_transport](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp_transport/): Mesh-optimized fountain transport layer.
- [tfp_client](file:///c:/Users/msunw/Downloads/TheFoundationProtocol/tfp-foundation-protocol/tfp_client/): Legacy v3 integration library and API adapters.

### Inactive / Orphaned Modules
The following modules are currently orphaned and not maintained in the v3.2 release:
- `tfp_broadcaster`: Replaced by `tfp_core_v4` mesh gossip.
- `tfp_simulator`: Root-level simulator is inactive; use `tests/simulation` for network stress tests.
- `tfp_pilots`: Configuration stubs for legacy regional deployments.
- `tfp_testbed`: Legacy metrics collection; replaced by `docker-compose.testbed.yml` observability stack.
- `tfp_plugins`: Experimental access control stubs.
- `tfp_security`: Heuristic behavioral engines; replaced by `tfp_core/security` mutualistic defense.

## Runtime Modes

| Mode | Behaviour |
|------|-----------|
| `demo` (default) | Permissive defaults, in-memory DB allowed. |
| `production` | Fail-closed: persistent DB required, `TFP_PEER_SECRET` required, `TFP_ADMIN_DEVICE_IDS` enforced. |
