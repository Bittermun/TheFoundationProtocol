# Offline-library pilot results — 2026-10-05

The optional operator adapter passed a real installed-wheel demonstration on Windows: separately launched sender and receiver, seeded 30% packet loss, forced receiver process-tree termination after one persisted chunk, restart, independent artifact hash verification, and activation through real Kiwix. The changed fixture page was also checked against its expected body in integration tests. This is a bounded pilot result, not IIAB certification or physical-device validation.

| Measurement | Result |
|---|---:|
| Full target archive | 363,989 bytes |
| Signed update's delta artifact | 83,337 bytes |
| Artifact reduction | 77.1% |
| Wire bytes received by loss proxy, including carousel/restart overhead | 772,492 bytes |
| Wire bytes forwarded by proxy | 516,527 bytes |
| Sampled maximum operator process-tree RSS | 43,614,208 bytes (41.6 MiB) |
| Complete delivery and reader activation | 27.718 seconds |
| Completed chunks retained across process restart | 1 |

The selected carousel sent more than twice the target's size. The patch's smaller size does **not** establish lower end-to-end network cost. An ordinary full-file/resume comparison on the same impaired link, a low-dedup benchmark, and independently produced historical editions remain unmeasured. The preparation tests verify that unsuitable deltas select a full archive rather than reporting fabricated savings.

Tools: Kiwix tools 3.8.1, zim-tools 3.8.0; fixtures generated with libzim 3.13.0 from original CC0 content. See [fixture metadata](../tests/fixtures/library_update/fixtures.json), [machine-readable report](library_update_results.json), and [operator guide](offline_library_pilot.md). Regenerated fixtures can have different UUIDs and exact bytes; checked-in fixture hashes identify this run.

Reproduction requires an installed `tfp[library]` wheel, optional psutil for measurement, separately installed Kiwix/openZIM binaries, locally provisioned keys, a prepared signed package and a running monitored adapter catalog. Run:

```text
python scripts/verify_library_update.py --package package --public-key publisher.pub --transport-key transport.key --config config.json --python /path/to/installed/python --output new-evidence-directory --wheel /path/to/tfp.whl
```

The child processes use `-I` and run outside the checkout. On Windows the proxy is paused and recreated during restart to prevent a closed UDP destination's ICMP response from disabling the test proxy. Packet loss selection remains seeded across both proxy sockets. Measurements include actual delivered packet bytes; they are not the theoretical minimum recovery bandwidth.

Validation: full repository regression **1,954 passed, 1 skipped, 4 subtests passed** (417.84 seconds) and the official Ruff/Mypy/Bandit/Pytest gate (24 passed); explicit Ruff/Mypy/Bandit checks cover the new root-level modules. Real reader tests include failed-probe rollback, abrupt process death, duplicate activation, external catalog edits and competing writers. POSIX ownership/access-mode coverage is unavailable on Windows; a pinned Linux CI job is supplied and must pass before Linux deployment claims.

The original phone browser assets, shared receiver defaults, acoustic transport and radio framing are unchanged. The only phone-page edit corrects its existing server-side verification label. No new phone-side archive handling or dependency is introduced. Physical weak-phone tests, Raspberry Pi performance, disposable IIAB deployment, and historical edition/baseline benchmarks remain deployment/adoption gates.

No services were installed and no upstream submission, public release or partner contact was performed. To remove an optional pilot: stop only its dedicated reader/service, preserve its catalog/state and archives if needed, then remove its separate virtual environment/configuration. This does not require changing IIAB's own catalog or content-manager services.

## Optional Zstandard delta backend benchmark and verification (2026-10-06)

The optional Zstandard delta adapter (`tfp_core_v4/library_updates/zstd_delta.py`) passed comprehensive unit, boundary, benchmark, and process-isolation tests:

### 1. Comparative candidate benchmarks (`scripts/benchmark_library_delta.py`)

| Candidate | Artifact size | Artifact reduction vs target | Peak sampled process RSS | Reconstruction SHA3-256 |
|---|---:|---:|---:|---|
| Full-file baseline | 363,989 bytes | 0.0% | ~32 MiB | Exact match |
| CDC delta (`TFPZIMP1`) | 83,337 bytes | 77.1% | ~35 MiB | Exact match |
| Zstandard delta (`zstd-rawdict-v1`) | 247 bytes | 99.9% | ~34 MiB | Exact match |

*Note:* The 247-byte Zstandard delta represents performance on controlled same-prefix ZIM revisions where underlying content was appended/modified without container compression scrambling. It is evidence from this fixture, not a universal guarantee for all archive edits.

### 2. Multi-scenario process-boundary verification (`scripts/verify_library_update.py`)

The verification script supports two distinct test scenarios:
- **`--scenario delivery`:** Validates tiny 247-byte single-frame delivery over the lossy UDP proxy. Finishes in 1 chunk with `restart_count: 0`. No manufactured restart claims are made for single-chunk transfers.
- **`--scenario restart`:** Validates genuine multi-chunk interruption and resumption using a ~154 KiB payload (3 chunks). Process tree is killed after the first chunk checkpoint is saved, restarted cleanly, reuses the saved checkpoint, receives remaining droplets under 30% synthetic loss, and activates the reconstructed archive in a live `kiwix-serve` instance.
- **Resource bounds:** Measured peak operator process-tree RSS remained under 48 MiB across both scenarios, well within the declared 256 MiB pilot cap.

