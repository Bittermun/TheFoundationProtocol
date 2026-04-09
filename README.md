# Scholo — TFP v2.3 Foundation Protocol

A decentralized content/compute protocol for rural connectivity and AI-assisted broadcasting.

## Quick Start

```bash
cd tfp-foundation-protocol
pip install -r requirements.txt
pytest tests/ -v          # 100 tests, all passing
python tfp_simulator/attack_inject.py --seed 42 --requests 500
```

## Architecture

```
tfp-foundation-protocol/
├── tfp_client/            # Edge-device client (NDN, RaptorQ, ZKP, credit ledger)
│   └── lib/
│       ├── credit/        # CreditLedger — SHA3-256 hash chain, spend(), Merkle export
│       ├── ndn/           # NDN adapter (mock + real python-ndn)
│       ├── fountain/      # RaptorQ adapter (mock + real GF(2) erasure code, per-shard HMAC)
│       ├── zkp/           # ZKP adapter (mock + real Schnorr/Fiat-Shamir)
│       ├── security/      # SymbolicPreprocessor — recipe validator (wired into TFPClient)
│       ├── identity/      # PUFEnclave — HMAC-SHA3 identity + nonce (wired into TFPClient)
│       ├── routing/       # AsymmetricUplinkRouter — weighted cost channel
│       └── core/          # TFPClient — orchestrator (SecurityError, spend flow)
├── tfp_broadcaster/       # Broadcaster node (seed content, multicast tasks, LDM mapper)
│   └── src/
│       ├── multicast/     # Multicast adapter (mock + real UDP socket)
│       └── ldm_semantic_mapper/  # LDMSemanticMapper — Core/Enhanced PLP assignment
├── tfp_common/            # Shared schemas, proto stubs, lexicon sync
│   └── sync/lexicon_delta/ # HierarchicalLexiconTree — delta/rollback
├── tfp_simulator/         # Attack simulation (Python + ns-3 skeleton)
│   ├── attack_inject.py   # Standalone Python attack simulator
│   ├── ns3_tfp_sim.cc     # C++ ns-3/ndnSIM topology
│   └── run_sim.sh         # Unified runner
├── docs/
│   ├── porting_guide.md   # C/Rust porting guide (Cortex-M4 / RISC-V32)
│   ├── memory_budget.csv  # Per-module Flash/RAM budget
│   ├── sdr_pipeline.grc   # GNU Radio ATSC 3.0 ingestion pipeline
│   └── v2.2-hardening.md  # Security threat model & mitigations
└── tests/                 # 100 pytest tests (TDD)
```

## Key Components

| Module | Technology | Status |
|--------|-----------|--------|
| `CreditLedger` | SHA3-256 hash-chain, `spend()`, Merkle root, audit trail | ✅ v2.3 |
| `SymbolicPreprocessor` | Rule engine, confidence scoring, wired into TFPClient | ✅ v2.3 |
| `PUFEnclave` | HMAC-SHA3 + entropy + nonce, Sybil gate in TFPClient | ✅ v2.3 |
| `HierarchicalLexiconTree` | Delta apply + atomic rollback | ✅ Complete |
| `AsymmetricUplinkRouter` | Weighted cost, exponential backoff | ✅ Complete |
| `NDNAdapter` (real) | python-ndn 0.5.1, async, fallback | ✅ Complete |
| `RaptorQAdapter` (real) | GF(2) systematic erasure code, per-shard HMAC | ✅ v2.3 |
| `ZKPAdapter` (real) | Schnorr proof (Fiat-Shamir) | ✅ Complete |
| `MulticastAdapter` (real) | UDP socket multicast | ✅ Complete |
| `LDMSemanticMapper` | Core/Enhanced PLP assignment, wired into Broadcaster | ✅ v2.3 |
| Attack simulator | Shard poisoning, Sybil, congestion | ✅ Complete |
| ns-3 skeleton | C++ ndnSIM topology | ✅ Complete |
| Embedded porting guide | Cortex-M4 / RISC-V32 | ✅ Complete |

## Simulation

```bash
# Python attack injector (no ns-3 required)
python tfp_simulator/attack_inject.py --seed 42 --requests 500

# Full runner (uses ns-3 if installed)
bash tfp_simulator/run_sim.sh
```

See [`tfp_simulator/README.md`](tfp-foundation-protocol/tfp_simulator/README.md) for ns-3 + Mini-NDN build instructions (Ubuntu 22.04).

## Embedded Porting

See [`docs/porting_guide.md`](tfp-foundation-protocol/docs/porting_guide.md) for the full C/Rust porting guide targeting Cortex-M4 (STM32F4, nRF52840) and RISC-V32 (ESP32-C3). Memory budget: **122 KB Flash / 130 KB RAM** out of a 1 MB / 256 KB envelope.

## Security

See [`docs/v2.2-hardening.md`](tfp-foundation-protocol/docs/v2.2-hardening.md) for the full threat model covering shard poisoning, Sybil farming, credit chain tampering, and semantic drift.

## License

See [LICENSE](LICENSE).

