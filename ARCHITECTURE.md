# TFP Architecture Overview

This document describes the key design decisions and component interactions in the
TFP v3.1 Foundation Protocol node server.

## Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| API | FastAPI (Python 3.11+) | REST node server, device auth, content routing |
| Persistence | SQLite (WAL mode) | Devices, content metadata, credit ledgers, task store |
| Blob storage | `BlobStore` (filesystem or in-memory) | Raw content bytes — decoupled from SQLite for scalability |
| Content routing | NDN adapter (`DemoNDNAdapter` / `RealNDNAdapter`) | Hash-based content naming; real NDN gated by `TFP_REAL_ADAPTERS=1` |
| Pinning | IPFS (`IPFSBridge`) | Persistent content pinning with hash→CID mapping; offline-safe |
| Discovery | Nostr (`NostrBridge` + `NostrSubscriber`) | Decentralised pub/sub for content announcements and HLT gossip |
| Compute | HABP (`HABPVerifier`) | 3/5 proof consensus for credit minting |
| Credits | `CreditLedger` | SHA3-256 hash-chain, 21M supply cap |
| Rate limiting | `_RateLimiter` / `_RedisRateLimiterAdapter` | Sliding-window per-device; Redis for multi-worker deployments (`TFP_REDIS_URL`) |
| Semantic search | `RAGGraph` (optional) | ChromaDB + CodeBERT; gated by `TFP_ENABLE_RAG=1` |

## Key Design Decisions

### Why NDN?

Named Data Networking routes by content name, not host address. For IoT networks where device
addresses change frequently (cellular, mesh), NDN allows content to be retrieved without knowing
which node currently holds it. The current `DemoNDNAdapter` does a local store lookup; a
`RealNDNAdapter` exists and is activated with `TFP_REAL_ADAPTERS=1`.

### Why IPFS?

IPFS provides content-addressed persistent storage. When a TFP node publishes content, it pins
it to IPFS and records the `hash→CID` mapping. Other nodes can then fetch content from IPFS if
they know the CID, which is propagated via Nostr announcements.

### Why Nostr?

Nostr provides a decentralised pub/sub layer. When a node publishes content it broadcasts a
Nostr event containing the content hash, IPFS CID, and metadata. Subscribing nodes add these
entries to their `TagOverlayIndex`, enabling cross-node content discovery without a central
registry. The same channel carries HLT gossip (kind 30078) and index summaries (kind 30079).

### Credit System

Devices earn credits by submitting verified compute task results (`POST /api/task/{id}/result`).
Credits are spent to retrieve content (`POST /api/get`). The `HABPVerifier` requires 3 matching
proofs from different devices before credits are minted. Anti-replay is enforced via `EarnLog`
with a `UNIQUE(device_id, task_id)` SQLite constraint.

## Testbed

A 10-node testbed is provided via `docker-compose.testbed.yml` (ports 9001–9010).

To run it:
```bash
docker compose -f docker-compose.testbed.yml up -d
python tests/operate_testbed.py
```

The testbed uses a shared Nostr relay (`tfp-relay`), Redis (`tfp-redis`), and IPFS (`tfp-ipfs`)
service. Each node has its own persistent volume.

## Cross-node Content Retrieval

True cross-node content retrieval requires either:
1. A shared IPFS sidecar node so all nodes can pin/fetch the same CIDs, or
2. The `_PeerFallback` mechanism — when a hash is not found locally, the node HTTP-GETs raw
   bytes from configured `TFP_PEER_NODES`. Peer-to-peer authentication uses `TFP_PEER_SECRET`.

The `_PeerFallback` is automatically initialised when `TFP_PEER_NODES` is set.

## Runtime Modes

| Mode | Behaviour |
|------|-----------|
| `demo` (default) | Permissive defaults, in-memory DB allowed, no required secrets |
| `production` | Fail-closed: persistent DB required, `TFP_PEER_SECRET` required, `TFP_ADMIN_DEVICE_IDS` required, `TFP_NOSTR_PUBLISH_ENABLED` defaults to `0` |

Set `TFP_MODE=production` to activate production mode.
