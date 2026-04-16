# Multi-Node Testbed Benchmarks

This directory contains configurations and scripts for benchmarking TFP with real adapters on a multi-node testbed.

## Quick Start

### 1. Start the 10-node testbed with real adapters

```bash
cd tests/benchmarks
docker-compose -f docker-compose.10.yml up -d
```

This starts:
- 10 TFP nodes (ports 8001-8010) with `TFP_REAL_ADAPTERS=1`
- IPFS for content pinning
- Redis for rate limiting

### 2. Wait for nodes to be ready

```bash
# Check health status
curl http://localhost:8001/health
curl http://localhost:8002/health
# ... repeat for all nodes
```

### 3. Run the multi-node benchmark

```bash
cd ../../
python benchmark_multinode.py
```

This tests:
- P2P content distribution (publish to node 1, retrieve from all nodes)
- Multi-node retrieval latency
- Bandwidth savings from single upload, multi-node access

### 4. Stop the testbed

```bash
cd tests/benchmarks
docker-compose -f docker-compose.10.yml down
```

## What This Measures

**P2P Distribution:**
- Content published to one node is retrievable from all nodes via IPFS bridge
- Single upload, multi-node access = bandwidth savings

**Real Adapters:**
- `TFP_REAL_ADAPTERS=1` enables:
  - Real RaptorQ encoding (server-side chunking)
  - Real NDN adapter with blob_store fallback
  - Real Lexicon adapter with HLT integration

**Efficiency Gains:**
- Current setup measures IPFS-based P2P distribution
- Full RaptorQ shard-level efficiency requires NDN network deployment
- This is a stepping stone to full NDN-based efficiency

## Architecture

```
Node 1 (publish) → IPFS → Nodes 2-10 (retrieve)
                    ↓
              Blob Store (local shards)
                    ↓
              Real NDN Adapter (local retrieval)
                    ↓
              Real RaptorQ Decode
                    ↓
              Real Lexicon Reconstruct
```

## Next Steps

To measure full RaptorQ efficiency (shard-level P2P):
1. Deploy actual NDN network (python-ndn or ndn-cxx)
2. Enable NDN-based shard exchange between nodes
3. Benchmark partial reconstruction (k of n shards)
4. Measure bandwidth savings from shard-level distribution
