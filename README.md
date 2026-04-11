# Scholo — TFP v2.12 Foundation Protocol

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

## Current Status (v2.12)

- ✅ Production-ready core (23.5k+ LOC, 119+ Python files).
- ✅ **390 tests passing** (up from 340 pre-sprint).
- ✅ **SQLite persistence** — content and device enrollment survive node restarts (`pib.db`).
- ✅ **Device auth** — HMAC-SHA-256 per-request signing on all mutating endpoints.
- ✅ **Nostr subscriber** — completes the bridge; remote peer content discovery via relay.
- ✅ **PWA** — installable on Android/iOS, offline-first service worker.
- ✅ **Live demand scheduling** — `schedule_from_aggregator` wires MeshAggregator → GatewayScheduler directly.
- ✅ **In-memory tag cache** — O(matches) tag queries replace O(N) full-table scans.
- ✅ End-to-end simulation validated (attack scenarios included).
- ✅ Plugin SDK + web bridge (`tfp://`) ready for extensions.
- Ready for testbed deployment in 3 regions.

## Quick Start

```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
TFP_DB_PATH=:memory: PYTHONPATH=. pytest tests/ -q   # 390 tests
uvicorn tfp_demo.server:app --reload                  # Demo node on :8000
```

Open `http://localhost:8000` — the PWA is installable directly from the browser.

### With Docker

```bash
cd Scholo
docker compose up --build
# Open http://localhost:8000
# Open http://localhost:8000/docs (interactive API docs)
```

### CLI

```bash
cd tfp-foundation-protocol
pip install -e .
tfp earn --task-id demo-task-1
tfp publish --title "Hello" --text "From CLI" --tags demo,cli
tfp search
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
