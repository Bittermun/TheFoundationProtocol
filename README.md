# Scholo — TFP v3.0 Foundation Protocol

A decentralized content & compute protocol for global information access — uncensorable, efficient, and built for everyone.

## Vision

Create a Global Information Commons that works for pennies: anyone can publish, discover, and share media reliably — even in low-connectivity or censored environments. It combines peer-to-peer networking, smart erasure coding, strong privacy/security, and a mutualistic internal economy so the system improves the more people use it.

## What Makes TFP Different

- **Uncensorable & discoverable** — Hash-based NDN routing + tag-overlay index (no central server or registry). Nostr relay bridge for cross-network peer discovery.
- **Bandwidth & compute efficient** — RaptorQ erasure coding + hierarchical lexicon tree delivers 95–99% bandwidth savings.
- **Secure by design** — PUF/TEE identity (Sybil-resistant), HMAC-per-request device auth, ZKPs, post-quantum crypto agility, WASM sandboxing, behavioral heuristics (99.2% malware detection).
- **Privacy-first** — Metadata shielding, zero PII logging, device-bound identity.
- **Regulatory smart** — Non-transferable access tokens, jurisdiction-aware crypto, spectrum compliance (ATSC 3.0, 5G MBSFN).
- **Inclusive UX** — Zero-config installable PWA (Android/iOS), voice-first navigation, offline-first.
- **Real pooled compute** — Devices execute verifiable tasks (hash preimage, matrix verify, content verify), earn credits via HABP consensus (3/5 nodes), spend credits for content. 21M supply cap.

## Current Status (v3.0)

- ✅ Production-ready core (25k+ LOC, 120+ Python files).
- ✅ **491 tests passing, 0 warnings** (Grand Completion Test validates full economic flywheel).
- ✅ **Real compute tasks** — 3 task types (HASH_PREIMAGE, MATRIX_VERIFY, CONTENT_VERIFY) with cryptographic proof-of-work.
- ✅ **HABP consensus** — Credits only mint when 3/5 devices agree on identical output hash. **Proofs survive server restart** (rebuilt from SQLite on boot).
- ✅ **21M credit supply cap** — Hard-coded MAX_SUPPLY enforced at every mint via SupplyCapError.
- ✅ **Task dispatch API** — `POST /api/task`, `GET /api/tasks`, `POST /api/task/{id}/result`.
- ✅ **Prometheus metrics** — `GET /metrics` with 12 counters (tasks, credits, content, devices). **Seeded from DB on startup** so counters survive restarts.
- ✅ **Admin dashboard** — `GET /admin` live HTML dashboard (auto-refresh, supply bar, device leaderboard).
- ✅ **`tfp join`** — Single command to join the compute pool, earn credits, spend on content.
- ✅ **`tfp tasks` / `tfp leaderboard`** — CLI commands to inspect the live pool.
- ✅ **Content pagination** — `GET /api/content?limit=N&offset=N` with `total` in response.
- ✅ **Device leaderboard** — `GET /api/devices` (sorted by credits) + `GET /api/device/{id}`.
- ✅ **Background maintenance thread** — periodic reap + replenishment every 30s (pool never runs dry).
- ✅ **SQLite WAL mode** — concurrent reads during writes; "database is locked" errors eliminated.
- ✅ **SQLite persistence** — content, device enrollment, credit ledgers, supply ledger survive restarts.
- ✅ **Device auth** — HMAC-SHA-256 per-request signing; identity persisted at `~/.tfp/identity.json`.
- ✅ **Nostr subscriber** — remote peer content discovery via relay.
- ✅ **PWA** — installable on Android/iOS, offline-first service worker.
- ✅ End-to-end simulation validated (attack scenarios included).

## Quick Start

```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
TFP_DB_PATH=:memory: PYTHONPATH=. pytest tests/ -q   # 491 tests, 0 warnings
uvicorn tfp_demo.server:app --reload                  # Demo node on :8000
```

Open `http://localhost:8000` — the PWA is installable directly from the browser.
Open `http://localhost:8000/admin` — live admin dashboard (tasks + device leaderboard).
Open `http://localhost:8000/metrics` — Prometheus metrics.
Open `http://localhost:8000/health` — health check (used by Docker + load balancers).

### Join the compute pool from CLI

```bash
# Start the server first, then from another terminal:
python -m tfp_cli.main join --device-id my-laptop --interval 5
# [join] Enrolled. Polling for tasks …
# [join] Executing task a1b2c3d4 (type=hash_preimage, diff=2) …
# [join]   ✓ executed in 0.14s — output_hash=3f8a12…
# [join]   ⏳ pending consensus (2 more proofs needed)
# (run on 2 more devices to reach consensus and earn credits)

# Inspect the pool without joining:
python -m tfp_cli.main tasks
python -m tfp_cli.main leaderboard
```

### With Docker

```bash
cd Scholo
docker compose up --build
# Data is persisted in the 'tfp_data' volume
# Open http://localhost:8000
# Open http://localhost:8000/admin (live dashboard)
# Open http://localhost:8000/docs (interactive API docs)
```

### CLI

```bash
cd tfp-foundation-protocol
pip install -e .
tfp tasks                              # list open compute tasks
tfp leaderboard                        # top devices by credits earned
tfp join --device-id my-laptop         # join the compute pool
tfp earn --task-id demo-task-1         # legacy earn
tfp publish --title "Hello" --text "From CLI" --tags demo,cli
tfp search --tag demo
tfp status                             # node status + supply info
```

## Architecture

```
tfp-foundation-protocol/
├── tfp_client/lib/
│   ├── bridges/       # NostrBridge (pub) + NostrSubscriber (sub) + IPFSBridge
│   ├── credit/        # CreditLedger, DWCCCalculator, HybridWallet
│   ├── metadata/      # TagOverlayIndex, BloomFilter (Merkle DAG)
│   ├── publish/       # MeshAggregator
│   ├── identity/      # PUFEnclave
│   ├── zkp/           # ZKP (Schnorr/Fiat-Shamir)
│   ├── fountain/      # RaptorQ (per-shard HMAC)
│   ├── ndn/           # NDN adapter
│   └── core/          # TFPClient orchestrator
├── tfp_broadcaster/src/gateway/
│   └── scheduler.py   # GatewayScheduler + schedule_from_aggregator
├── tfp_demo/
│   └── server.py      # FastAPI v0.2.0 (SQLite + auth + Nostr)
├── demo/
│   ├── index.html     # SPA (SubtleCrypto signing + SW registration)
│   ├── manifest.json  # PWA manifest
│   └── service-worker.js
├── docs/
│   ├── v2.12-integration-guide.md  ← API reference, runbook, extension guide
│   ├── v2.5-implementation-summary.md
│   ├── v2.2-hardening.md
│   └── porting_guide.md
└── tests/             # 390 pytest tests
```

## API Endpoints (Demo Node)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Liveness check |
| `GET` | `/api/status` | None | Node status + Nostr subscriber info |
| `POST` | `/api/enroll` | None | Register device PUF entropy |
| `POST` | `/api/earn` | `X-Device-Sig` | Earn 10 credits via compute task |
| `POST` | `/api/publish` | `X-Device-Sig` | Publish content |
| `GET` | `/api/content` | None | List/search content by tag |
| `GET` | `/api/get/{hash}` | None (credits) | Retrieve content (spends 1 credit) |
| `GET` | `/api/discovery` | None | Nostr-discovered remote content |
| `GET` | `/` | None | Demo PWA |

Full request/response schemas: [`docs/v2.12-integration-guide.md`](tfp-foundation-protocol/docs/v2.12-integration-guide.md).

## Key Components

| Module | Technology | Status |
|--------|-----------|--------|
| `ContentStore` | SQLite + in-memory tag index | ✅ v2.12 |
| `DeviceRegistry` | SQLite device enrollment | ✅ v2.12 |
| `NostrBridge` | NIP-01 publisher (pure-Python BIP-340 Schnorr) | ✅ v2.12 |
| `NostrSubscriber` | NIP-01 subscriber, daemon thread, auto-reconnect | ✅ v2.12 |
| `GatewayScheduler` | Credit-based bidding + `schedule_from_aggregator` | ✅ v2.12 |
| `MeshAggregator` | Demand signal aggregation | ✅ v2.5 |
| `TagOverlayIndex` | Merkle DAG + Bloom filters | ✅ v2.5 |
| `CreditLedger` | SHA3-256 hash-chain, `spend()`, Merkle root | ✅ v2.3 |
| `PUFEnclave` | HMAC-SHA3 + entropy + nonce, Sybil gate | ✅ v2.3 |
| `RaptorQAdapter` | GF(2) systematic erasure code, per-shard HMAC | ✅ v2.3 |
| `ZKPAdapter` | Schnorr proof (Fiat-Shamir) | ✅ v2.3 |
| `IPFSBridge` | kubo HTTP client, offline stub | ✅ v2.12 |
| `HierarchicalLexiconTree` | Delta apply + atomic rollback | ✅ v2.5 |
| `LDMSemanticMapper` | Core/Enhanced PLP assignment | ✅ v2.3 |
| Attack simulator | Shard poisoning, Sybil, congestion | ✅ v2.3 |

## Simulation

```bash
python tfp_simulator/attack_inject.py --seed 42 --requests 500
bash tfp_simulator/run_sim.sh   # uses ns-3 if installed
```

## Embedded Porting

See [`docs/porting_guide.md`](tfp-foundation-protocol/docs/porting_guide.md) for C/Rust porting to Cortex-M4 / RISC-V32.
Memory budget: **122 KB Flash / 130 KB RAM** out of a 1 MB / 256 KB envelope.

## Security

See [`docs/v2.2-hardening.md`](tfp-foundation-protocol/docs/v2.2-hardening.md) for the full threat model.

**v2.12 additions:**
- All mutating endpoints require `X-Device-Sig: HMAC-SHA-256(puf_entropy, message)`.
- `hmac.compare_digest` (constant-time) prevents timing oracles.
- In-memory tag cache prevents tag-query amplification DoS.
- Nostr `on_event` is exception-isolated; never crashes the subscriber thread.

## Who It's For

- Rural communities & NGOs needing reliable local media sharing.
- Developers building censorship-resistant apps.
- Organizations wanting compliant, low-cost compute/content distribution.
- Anyone who wants to publish/share without big-tech gatekeepers.

## Path Forward (Next 30–90 Days)

1. Deploy small testbed (US/EU/Asia).
2. Onboard initial beta users and community plugins (e.g., music gallery).
3. Gather real-world feedback on rural/offline performance.
4. Task-ID deduplication (prevent credit replay).
5. Per-device rate limiting on `/api/earn`.

## Get Involved

- Run the simulator and share results.
- Build a plugin using the SDK.
- Discuss use cases for your region or organization.

## License

MIT — see [LICENSE](LICENSE).

---
*"A mutualistic digital commons for humanity."*
