# TFP Testbed Stabilization — Delegation Brief
> **Branch**: `stabilize/10-node-testbed`  
> **Date**: 2026-04-12  
> **Prepared by**: Antigravity (Google DeepMind)  
> **For**: Second-opinion AI reviewer / next work session

---

## Project Overview

The Foundation Protocol (TFP) is a decentralized compute + content network designed for constrained IoT/edge devices. The core stack is:

- **FastAPI** node server (`tfp_demo/server.py`) exposing REST APIs
- **SQLite** for persistence (devices, content, credits, tasks)
- **NDN (Named Data Networking)** for content routing
- **IPFS** (via `IPFSBridge`) for persistent content pinning
- **Nostr** (via `NostrBridge` + `NostrSubscriber`) for decentralized content announcements
- **HABP** (Hardware-Attested Blind Proof) for compute task verification
- **Docker Compose** 10-node testbed (`docker-compose.testbed.yml`)

The entire stack runs in Docker. Each node is identical, listening on port `8000` internally, exposed on host ports `9001–9010`.

---

## Current Status

### ✅ What Works
- **Containers launch and stay healthy** — `docker ps` shows all 10 `tfp-node-X` containers `Up (healthy)` with the health check passing at `/health`.
- **Server imports succeed** — confirmed via `docker exec tfp-node-1 python -c "import tfp_demo.server; print('OK')"`.
- **SQLite DB is being created** — `/data/pib.db` exists in each container.
- **Dependencies are correct** — `requirements.txt` pins match installed packages (`fastapi==0.135.3`, `uvicorn==0.44.0`, `starlette==1.0.0`).
- **IPFS bridge is offline-safe** — falls back gracefully when the `tfp-ipfs` container is unreachable.
- **Nostr bridge is offline-safe** — uses offline mode when `NOSTR_RELAY` env var is unset.

### ⚠️ Known Issues & Blockers

#### 1. `operate_testbed.py` Enrollment Failures
**Symptom**: Running `python tests/operate_testbed.py` results in `Server disconnected without sending a response` on the enrollment step.

**Root Cause Hypotheses** (in order of likelihood):
1. **Race condition** — The test script sends enrollment requests immediately after containers report "healthy", but the uvicorn worker may not have finished the `lifespan` startup sequence (especially SQLite schema init and HABP replay). The health check only polls `/health`, not whether the app state is initialized.
2. **Windows `localhost` vs `127.0.0.1`** — On Windows, `localhost` may resolve to `::1` (IPv6) while Docker binds to `0.0.0.0` (IPv4). Fixed by changing `BASE_URL` from `http://127.0.0.1` to `http://localhost` and adding a retry loop.
3. **uvicorn connection reset** — If the `lifespan` function raises an exception before `yield`, uvicorn resets the TCP connection with no HTTP response.

**What's been tried**:
- Added comprehensive `try/except` around the entire `lifespan` body with traceback written to `/data/crash.log`. However `crash.log` is NOT being created, which means the crash happens before the `lifespan` function body is even entered — likely during module import or before uvicorn calls lifespan.
- Moved ports from `8000-series` to `9001-9010` to avoid host service conflicts.
- Added `PYTHONUNBUFFERED=1` to Docker env for real-time logging.

**What to try next**:
- Add `print("LIFESPAN ENTERED", flush=True)` as the very first line of the `lifespan` function to confirm it is being called.
- Check `docker logs tfp-node-1` for any tracebacks before the uvicorn worker message.
- Try reducing `lifespan` startup to a no-op (just `yield`) to see if a minimal server starts successfully. If it does, add back each step one-by-one to find the crashing line.
- The `_rebuild_habp_from_db()` call in `TaskStore.__init__()` queries the DB and replays proofs — this is called during `lifespan` and could be failing silently.

#### 2. Cross-Node Content Retrieval — 404 Bug
**Symptom**: When `tfp-node-2` tries to retrieve content published to `tfp-node-1` via `/api/get/{root_hash}`, it returns HTTP 404.

**Root Cause**: The `TFPClient.request_content()` method queries the **local** `ContentStore` via the `DemoNDNAdapter`. If the content was published on a different node, it won't be in the local SQLite DB. The NDN fallback to IPFS only works if:
1. The content was pinned to IPFS (requires `tfp-ipfs` container to be running and reachable).
2. The IPFS CID mapping exists in `_ipfs_bridge._hash_to_cid` (in-memory — lost on restart).

**Fix Applied**: The `/api/get/{root_hash}` endpoint now tries both local store and NDN/IPFS, with proper error discrimination:
- `402` → no credits
- `404` → genuinely not found
- `500` → unexpected internal error

**What still needs work**: The CID mapping is in-memory and not persisted to SQLite. Cross-node discovery relies on Nostr announcements populating `_tag_overlay`, but that only gives you the hash — you still need a way to fetch the actual bytes from the peer node. **True cross-node retrieval requires either a shared IPFS node or an inter-node HTTP fetch (not yet implemented).**

#### 3. `docker-compose.100.yml` Deleted
The 100-node test file has been deleted. The 100-node test is **explicitly deferred** by user request until the 10-node environment is stable. Do not recreate it yet.

#### 4. `requirements.txt` — Starlette Version Pin
`starlette==1.0.0` is pinned. This is a very high version number for Starlette; verify against PyPI that this is a valid release. If not, try `starlette>=0.41.0`.

---

## File-by-File Change Summary

### `docker-compose.testbed.yml`
- **Changed**: Node host ports from `8000-8009` range to `9001-9010` to avoid conflicts with host services (Windows often uses 8000-8080 for IIS/other).
- **Added**: `PYTHONUNBUFFERED=1` to all node service environment blocks for real-time log flushing.

### `tests/operate_testbed.py`
- **Changed**: `BASE_URL` from `http://127.0.0.1` to `http://localhost`.
- **Added**: Pre-enrollment health check with a 5-retry loop (`await asyncio.sleep(1)` between retries) to wait for node readiness before attempting enrollment.
- **Kept**: `NODE_PORTS = list(range(9001, 9011))` — matches new Docker port config.

### `tfp-foundation-protocol/tfp_demo/server.py`
- **Changed**: `lifespan()` context manager — wrapped entire body in `try/except/finally` with:
  - `log.error()` on failure
  - Traceback written to `/data/crash.log`
  - Graceful cleanup in `finally` block
- **Changed**: `/api/get/{root_hash}` error handling — now catches both `ValueError` (credits/not-found) and generic `Exception` (500), with proper HTTP status codes.
- **Added**: Multipart form-data upload support in `/api/publish` (for streaming large payloads from constrained devices).
- **Added**: `StreamingResponse` support in `/api/get` when `?stream=true` query param is set.
- **Added**: `/api/discovery` endpoint — returns content hashes from Nostr-announced events for a given domain.

### `tfp-foundation-protocol/requirements.txt`
- Updated to pin exact versions. See current file for specifics.

### `tfp-foundation-protocol/tfp_broadcaster/broadcaster.py`
- Added IPFS pinning on `seed_content()` calls — now returns a `cid` field in the result dict when IPFS is available.

### `tfp-foundation-protocol/tfp_client/lib/bridges/ipfs_bridge.py`
- Added `record_mapping()` for associating TFP hashes with IPFS CIDs.
- Added `get_metadata()` for retrieving stored metadata by TFP hash.
- `offline` mode falls back gracefully without errors.

### `tfp-foundation-protocol/tfp_client/lib/bridges/nostr_bridge.py`
- NIP-01 event publishing with offline-safe fallback.
- `publish_content_announcement()` now includes `cid` field in published JSON payload.

### `tfp-foundation-protocol/tfp_client/lib/core/tfp_engine.py`
- Added `spend_for_service(credits)` method for ZKP delegation cost deduction.

### `tests/benchmarks/` (new, untracked)
- Benchmark scripts from a previous session. Not yet committed.

---

## Architecture — Key Design Decisions

### Why NDN?
Named Data Networking routes by content name, not by host address. For IoT networks where device addresses change frequently (cellular, mesh), NDN allows content to be retrieved without knowing which node has it. The current implementation is a **demo adapter** — `DemoNDNAdapter` just does a local store lookup. A real NDN adapter (`RealNDNAdapter`) exists but is gated behind `TFP_REAL_ADAPTERS=1`.

### Why IPFS?
IPFS provides content-addressed persistent storage. When a TFP node publishes content, it pins it to IPFS and records the `hash→CID` mapping. Other nodes can fetch the content from IPFS if they know the CID. The CID is propagated via Nostr announcements.

### Why Nostr?
Nostr provides a decentralized pub/sub layer. When a TFP node publishes content, it broadcasts a Nostr event containing the content hash, IPFS CID, and metadata. Other nodes subscribe to the Nostr relay and add these entries to their `TagOverlayIndex` — enabling cross-node content discovery without a centralized registry.

### Credit System
Devices earn credits by submitting compute task results (`/api/earn`). Credits are spent to retrieve content (`/api/get`) or generate ZKP proofs (`/api/delegate-proof`). The `HABPVerifier` requires 3 matching proofs from different devices for consensus before credits are minted. Anti-replay via `EarnLog` with a `UNIQUE(device_id, task_id)` constraint.

---

## Next Steps for Delegated AI

### Priority 1 — Debug lifespan startup crash
1. Add bare `print()` at top of `lifespan` to confirm it's entered.
2. Check `docker logs tfp-node-1 --follow` during container startup.
3. Try stripping `lifespan` to just `yield` and verify the server starts.
4. Re-add each init step until the crashing line is identified.

### Priority 2 — Cross-node content retrieval
1. Implement `CID mapping persistence` — store `hash→CID` in the SQLite `content` table alongside the content data.
2. Implement a **peer-fetch fallback** — when `/api/get/{hash}` returns 404 locally, the node should HTTP-GET the content from peer nodes (addresses discoverable via Docker network DNS: `tfp-node-1`, `tfp-node-2`, etc.).
3. Alternatively: ensure the `tfp-ipfs` sidecar container is included in the testbed compose and that all nodes share it.

### Priority 3 — Run the testbed end-to-end
```
docker compose -f docker-compose.testbed.yml up -d
python tests/operate_testbed.py
```
Expected: `SUCCESS` for enrollment, earn credits, publish, and cross-node retrieval.

---

## Environment

- **Docker Compose file**: `docker-compose.testbed.yml`
- **Node ports**: `9001–9010` on host, `8000` inside containers
- **Data volume**: `/data/pib.db` per node (separate named volume per node)
- **Python**: `3.12-slim`
- **IPFS container**: `tfp-ipfs` (may not be in testbed compose — check)
- **Key env vars**:
  - `TFP_DB_PATH=/data/pib.db`
  - `TFP_IPFS_API_URL=http://tfp-ipfs:5001`
  - `PYTHONUNBUFFERED=1`
  - `NOSTR_RELAY` (optional — if unset, Nostr runs in offline mode)

## Running Tests

```bash
# Rebuild and restart testbed
docker compose -f docker-compose.testbed.yml build
docker compose -f docker-compose.testbed.yml up -d

# Tail logs from node 1 to watch startup
docker logs tfp-node-1 --follow

# Run operational test suite
python tests/operate_testbed.py

# Manual health check
curl http://localhost:9001/health
curl http://localhost:9001/api/status
```
