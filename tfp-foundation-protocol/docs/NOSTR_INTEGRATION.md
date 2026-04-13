# RAGGraph + Nostr Integration Guide

> **Decentralized semantic search index gossip for TFP v3.1+**

## Overview

RAGgraph integrates with the Nostr protocol to enable decentralized semantic search index gossip. This allows peer nodes to detect index drift, verify content freshness, and coordinate distributed knowledge graphs without central coordination.

## Architecture

### Event Kinds

RAGgraph uses three custom Nostr event kinds:

| Kind | Name | Purpose |
|------|------|---------|
| 30078 | `TFP_CONTENT_KIND` | HLT Merkle-root gossip for semantic tree state |
| 30079 | `TFP_SEARCH_INDEX_KIND` | Semantic search index summary (published after reindex) |
| 30080 | `TFP_CONTENT_ANNOUNCE_KIND` | Content availability announcements |

### The Reindex-to-Gossip Lifecycle

When a node performs a reindex operation via `POST /api/admin/rag/reindex`:

1. **Trigger**: Admin invokes reindex endpoint with valid device signature
2. **Computation**: ChromaDB collections are rebuilt; vectors are embedded using CodeBERT
3. **Local Commit**: New chunks are committed to the local ChromaDB store
4. **Fingerprint Generation**: A canonical index fingerprint is computed from:
   - Collection ID and total chunk count
   - Sorted file paths with modification times
   - SHA3-256 hash of combined metadata
5. **Event Construction**: `NostrBridge.publish_search_index_summary()` builds a Kind-30079 event containing:
   - `domain`: Content domain (e.g., "general", "code")
   - `index_hash`: Deterministic fingerprint of index state
   - `chunk_count`: Total indexed chunks
   - `schema_version`: Index schema version for compatibility
6. **Signing**: Event is signed using BIP-340 Schnorr signatures with the node's identity key
7. **Broadcast**: Event is pushed to all configured relays

Peer nodes subscribing to these events can detect when their local index diverges from the network consensus and trigger synchronization.

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `TFP_ENABLE_NOSTR` | Enable Nostr integration (1/0) | `0` | No |
| `NOSTR_RELAY` or `NOSTR_RELAY_URL` | WebSocket URL of primary Nostr relay | `wss://relay.damus.io` | No* |
| `TFP_NOSTR_TRUSTED_PUBKEYS` | Comma-separated hex pubkeys for trusted peers. If set, index updates from unknown keys are ignored for drift calculation. | `*` (Accept All) | No |

\* Required if `TFP_ENABLE_NOSTR=1`

### Trust Boundaries

**Critical Security Note**: The `TFP_NOSTR_TRUSTED_PUBKEYS` variable defines your trust boundary for federated operations:

- **Empty or `*`**: Accept index gossip from any pubkey (suitable for public testnets)
- **Specific pubkeys**: Only accept drift detection signals from known, verified peers (recommended for production)

Example configuration for a trusted cluster:
```bash
export TFP_ENABLE_NOSTR=1
export NOSTR_RELAY=wss://nostr.bitcoiner.social
export TFP_NOSTR_TRUSTED_PUBKEYS=abc123...,def456...
```

## Operational Workflows

### Monitoring Index Gossip

Check logs for gossip publication after reindex:
```bash
grep "Search index gossip" /var/log/tfp/server.log
```

Expected output on success:
```
INFO - Search index gossip published: domain=general, chunks=1247, hash=a1b2c3...
```

On failure (relay unreachable):
```
WARNING - Search index gossip publish failed (relay=wss://relay.damus.io): Connection timeout
```

### Detecting Index Drift

Remote peers can compare their local index hash against received Kind-30079 events:

```python
# Pseudo-code for drift detection
def check_drift(local_hash, remote_event):
    if remote_event['pubkey'] not in TRUSTED_PUBKEYS:
        return "untrusted_source"

    remote_hash = remote_event['tags']['index_hash']
    if local_hash != remote_hash:
        return {
            "drift_detected": True,
            "local_chunks": local_stats['chunks'],
            "remote_chunks": remote_event['tags']['chunk_count'],
            "divergence_ratio": abs(local_chunks - remote_chunks) / max(local_chunks, remote_chunks)
        }
    return "synchronized"
```

### Troubleshooting

#### Symptom: No gossip events published after reindex

**Checks:**
1. Verify `TFP_ENABLE_NOSTR=1` is set
2. Ensure `NOSTR_RELAY` or `NOSTR_RELAY_URL` is configured
3. Check that `websockets` library is installed: `pip install websockets>=11.0`
4. Review logs for "Nostr publish failed" warnings

#### Symptom: Events published but not visible on relay

**Checks:**
1. Test relay connectivity: `wscat -c $NOSTR_RELAY`
2. Verify relay accepts kind-30079 events (some relays filter custom kinds)
3. Check event signature validity using [nostr-tools](https://github.com/nbd-wtf/nostr-tools) verification
4. Try alternative relay (e.g., `wss://relay.damus.io`, `wss://nostr.bitcoiner.social`)

#### Symptom: Drift detection false positives

**Cause**: Different schema versions or embedding models between nodes.

**Resolution:**
1. Ensure all nodes use same `schema_version` tag
2. Verify consistent embedding model (CodeBERT v1) across cluster
3. Use `TFP_NOSTR_TRUSTED_PUBKEYS` to limit comparison to homogeneous nodes

## API Reference

### POST /api/admin/rag/reindex

Triggers reindex and automatically publishes Kind-30079 gossip event.

**Request:**
```json
{
  "device_id": "admin-node-01",
  "patterns": "*.py,*.md"
}
```

**Response:**
```json
{
  "indexed_chunks": 1247,
  "directory": "/data/codebase",
  "rag_stats": {"total_chunks": 1247, "collection_name": "tfp"}
}
```

**Side Effects:**
- Local ChromaDB index rebuilt
- Kind-30079 event published to configured relays
- Peer nodes receive drift notification (if subscribed)

## Security Considerations

1. **Replay Protection**: Each Kind-30079 event includes a timestamp (`created_at`). Nodes should reject events older than a configurable threshold (default: 24 hours).

2. **Rate Limiting**: The bridge maintains a bounded history (max 10,000 events) to prevent memory exhaustion. Failed publishes are logged but do not block reindex operations.

3. **Trust Model**: By default, all pubkeys are accepted. For production deployments, always configure `TFP_NOSTR_TRUSTED_PUBKEYS` with verified peer identities.

## Example Deployment

```bash
# Production single-node deployment
export TFP_ENABLE_RAG=1
export TFP_ENABLE_NOSTR=1
export TFP_RAG_SOURCE_DIR=/data/knowledge_base
export TFP_RAG_DIR=/var/lib/tfp/chroma
export NOSTR_RELAY=wss://nostr.bitcoiner.social
export TFP_NOSTR_TRUSTED_PUBKEYS=$(cat /etc/tfp/trusted_peers.txt)

# Start server
uvicorn tfp_demo.server:app --host 0.0.0.0 --port 8000
```

## Further Reading

- [NIP-01: Basic Protocol Flow Description](https://github.com/nostr-protocol/nips/blob/master/01.md)
- [NIP-78: Parameterized Replaceable Events](https://github.com/nostr-protocol/nips/blob/master/78.md)
- [BIP-340: Schnorr Signatures for secp256k1](https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki)
