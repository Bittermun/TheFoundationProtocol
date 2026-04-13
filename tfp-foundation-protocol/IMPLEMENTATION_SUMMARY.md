# TFP v3.1.1 - Implementation Summary

## What's Built

This document summarises the optional extension modules included in
`tfp-foundation-protocol/tfp_client/lib/`. These are **not required** for the
core demo node — the demo server (`tfp_demo/server.py`) uses only the core deps
listed in `requirements.txt`.

---

## Core (always available)

| Module | File | Description |
|--------|------|-------------|
| **Nostr publisher** | `bridges/nostr_bridge.py` | Pure-Python NIP-01 event publishing with BIP-340 Schnorr signatures. No external relay required — falls back gracefully when offline. |
| **Nostr subscriber** | `bridges/nostr_subscriber.py` | NIP-01 subscriber, daemon thread, auto-reconnect. Wired into demo server via `NOSTR_RELAY` env var. |
| **IPFS bridge** | `bridges/ipfs_bridge.py` | Kubo HTTP client for CID ↔ TFP hash mapping. Offline stub when IPFS is unavailable. |
| **Credit ledger** | `credit/ledger.py` | SHA3-256 hash-chain, 21M supply cap, `SupplyCapError`. |
| **Task executor** | `compute/task_executor.py` | Three task types: `HASH_PREIMAGE`, `MATRIX_VERIFY`, `CONTENT_VERIFY`. |
| **PUF enclave** | `identity/puf_enclave.py` | HMAC-SHA3 identity, Sybil gate. |
| **RaptorQ adapter** | `fountain/raptor_q.py` | GF(2) systematic erasure code with per-shard HMAC. |
| **ZKP adapter** | `zkp/zkp_adapter.py` | Schnorr proof (Fiat-Shamir). |
| **Tag overlay index** | `metadata/tag_overlay.py` | Merkle DAG + Bloom filters. |

---

## Optional Extension Modules

These modules are included in the repo but require additional dependencies
(installed separately via `pip install "tfp[distributed]"`, `tfp[rag]`,
or `tfp[tracing]`).

### 1. Distributed Rate Limiter — `lib/rate_limiter.py`

Sliding-window counter algorithm backed by Redis. Designed for **multi-node
deployments** where the built-in in-memory `_RateLimiter` in `server.py` is not
sufficient (it resets on restart and is not shared across replicas).

**Install:** `pip install "tfp[distributed]"` (requires `redis>=5.2.0`)

```python
from tfp_client.lib.rate_limiter import DistributedRateLimiter, create_rate_limit_middleware

limiter = DistributedRateLimiter(redis_url="redis://localhost:6379")
app.add_middleware(create_rate_limit_middleware(limiter))
```

Endpoints protected:
- Task submission: 30/min per device
- Shard verification: 50/min per device
- HABP consensus: 100/min per device
- General API: 100/min per client

> **Note:** The demo server uses the built-in in-memory `_RateLimiter`. This
> module is for production multi-node deployments only.

---

### 2. RAGGraph Semantic Search with Nostr Gossip — `lib/rag_search.py`

CodeBERT embeddings + ChromaDB vector store for semantic search over the TFP
codebase. Intended to accelerate contributor onboarding. Integrated with Nostr bridge
for decentralized index synchronization (Kind-30079 events).

**Install:** `pip install "tfp[rag]"` (requires `chromadb>=0.4.24`, `transformers>=4.39.0`)

```python
from tfp_client.lib.rag_search import RAGGraph

rag = RAGGraph()
rag.index_directory("./tfp_client", patterns=["*.py", "*.md"])
results = rag.search("HABP consensus logic", top_k=5)
for r in results:
    print(f"{r.metadata['file']}:{r.metadata['line_start']} — score: {r.score:.2f}")
```

> **See Also:** [Nostr Integration Guide](docs/NOSTR_INTEGRATION.md) for gossip protocol details, drift detection, and trust boundary configuration.

> **Note:** Requires ~500 MB for model + index. Intended as a dev tool, not
> included in the production demo image.

---

### 3. OpenTelemetry Tracing — `lib/otel_tracing.py`

Distributed tracing for multi-node debugging. Exports spans via OTLP HTTP to
any OpenTelemetry-compatible backend (Jaeger, Grafana Tempo, Honeycomb, etc.).

**Install:** `pip install "tfp[tracing]"`

```python
from tfp_client.lib.otel_tracing import setup_otel_tracing

app = FastAPI()
setup_otel_tracing(app, service_name="tfp-node-1", otlp_endpoint="http://localhost:4318")
```

Observability stack (optional):

```bash
docker-compose -f docker-compose.observability.yml up -d
# Grafana:    http://localhost:3000
# Prometheus: http://localhost:9090
```

> **Note:** Only needed when running 3+ nodes and debugging cross-node latency.
> Not required for single-node demo.

---

## Nostr Bridge — Already Built In

The Nostr publisher and subscriber are part of the **core package** at
`tfp_client/lib/bridges/`. There is no separate `tfp-nostr-bridge` PyPI package
or external repository — all bridge functionality ships with the main package.

---

## Quick Reference: What Installs What

| Use Case | Install Command |
|----------|----------------|
| Core demo node | `pip install -r requirements.txt` |
| Full package (no extras) | `pip install -e .` |
| Multi-node with Redis rate limiting | `pip install -e ".[distributed]"` |
| Developer semantic search | `pip install -e ".[rag]"` |
| Distributed tracing | `pip install -e ".[tracing]"` |
| Everything | `pip install -e ".[all]"` |

---

## Testing

```bash
cd tfp-foundation-protocol
TFP_DB_PATH=:memory: PYTHONPATH=. python -m pytest tests/ -q
# 491 passed, 1 warning
```

Tests for the optional modules require their extra dependencies and are marked
with `@pytest.mark.skipif` when the optional dep is missing.


---
