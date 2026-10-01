# Phase A — Capability Map & Concrete Implementation Plan

- **Date:** 2026-09-27
- **Base Revision:** `d53f5f7fbe4de97feeedb09f7b2ce5dd4ab2fea8` (`main` == `origin/main`)
- **Working Branch:** `feat/device-to-phone-broadcast-baseline`
- **Untouched Local State:** `research/device-to-phone-proposal-review-2026-09-27.md`, worktrees `codex/bulletin-acceptance-recovery` and `codex/identity-receiver-package`

---

## 1. Trace of Path 1: Complete-Bulletin Acoustic Path

End-to-end flow:
`prepare_bulletin_package` $\rightarrow$ `AFSKModulator` $\rightarrow$ WAV / Speaker $\rightarrow$ Browser `IncrementalAFSKReceiver` (or Python `AFSKDemodulator` + `import_bulletin_package`) $\rightarrow$ Verification & Persistence.

| Stage | Input $\rightarrow$ Output Format | Implementation Location | Validation | Resource Limits | Persistence Behavior | Relevant Tests |
|---|---|---|---|---|---|---|
| **1. Bulletin Identity & Signing** | `(bulletin_id, rev, title, body_utf8, priv_key)` $\rightarrow$ `(publisher_hex, ed25519_sig_hex)` over canonical JSON array `["TFP_BULLETIN", 2, id, rev, title, sha3_256(body), pub]` | `tfp_core_v4/bulletin_identity.py:28-76` | Non-empty string `id`, `1 <= rev <= 2^53 - 1`, 64-hex `content_hash` (SHA3-256) & `publisher_id`, Ed25519 signature (`SIGNATURE_VERSION = 2`) | Safe integer bound `2^53 - 1` for JS compatibility | Stateless helper | `tests/test_bulletin_admission_recovery.py`, `tests/test_bulletin_workflow.py` |
| **2. Bulletin Package Preparation** | `(id, rev, title, content_text, key)` $\rightarrow$ JSON wire bytes `{"v":2,"id":...,"rev":...,"title":...,"body":...,"pub":...,"sig":...}` + `broadcast.wav` | `tfp_core_v4/bulletin.py:64-248`, CLI `bulletin-prepare` (`tfp_core_v4/cli.py`) | Rejects symlinks, normalizes CRLF to `\n`, checks `len(wire_payload) <= 4096` and `airtime_limit_seconds` before synthesis | `MAX_AFSK_PAYLOAD_SIZE = 4096` bytes; optional `airtime_limit_seconds` | Stages into `.tmp_<name>_<uuid>`, moves existing package to `.previous_<name>_<uuid>` backup before atomic rename | `tests/test_bulletin_workflow.py`, `tests/test_bulletin_admission_recovery.py` |
| **3. AFSK Modulation** | Raw payload `bytes` ($\le 4096$ B) $\rightarrow$ Framed packet (`16B 0x7E` + `2B len` + `payload` + `2B CRC16-CCITT` + `4B 0x7E`) $\rightarrow$ 16-bit mono PCM WAV (Bell 202: 1200/2200 Hz @ 1200 or 300 baud; optional 50 ms chirp + 10 ms guard) | `tfp-foundation-protocol/tfp_client/lib/audio/afsk_modulator.py:36-185` | Raises `ValueError` if payload $> 4096$ bytes; computes big-endian `crc16_ccitt` (`0x1021`, init `0xFFFF`) | `MAX_AFSK_PAYLOAD_SIZE = 4096` bytes (+24 B framing = 4120 B max on-air frame) | In-memory `BytesIO` WAV synthesis; written to disk by caller | `tests/test_acoustic_bulletin_verification.py`, `tests/test_acoustic_multipath_sweep.py` |
| **4. Python AFSK Demodulation & Import** | 16-bit mono/stereo WAV `bytes` $\rightarrow$ `list[bytes]` CRC-valid payloads $\rightarrow$ `TFPNode.store_bulletin` | `tfp-foundation-protocol/tfp_client/lib/audio/afsk_demodulator.py:45-246`, `tfp_core_v4/bulletin.py:251-335`, `tfp_core_v4/node.py:707-840` | Peak AGC normalization, quadrature correlation across $\pm 1.5\%, \pm 3\%$ clock drift (`fallback_300=True` option), `crc16_ccitt`, Ed25519 signature check (`verification_status`), publisher pinning & revision watermark check | `MAX_AFSK_PAYLOAD_SIZE = 4096` bytes; processes entire WAV buffer in memory | `BEGIN IMMEDIATE` SQLite transaction writes `recipes`, `chunks`, `droplets`, `bulletins`, and monotonic `bulletin_watermarks` (`publisher_trust: "not_established"`) | `tests/test_acoustic_bulletin_verification.py`, `tests/test_bulletin_watermarks.py`, `tests/test_bulletin_admission_recovery.py` |
| **5. Browser Receiver Server & Bootstrap** | HTTP GET `/`, `/receiver`, `/acoustic_receiver.html`, `/acoustic_stream.js` | `tfp_core_v4/cli.py:594-633` | Static file serving only | Binds exclusively to `127.0.0.1:port` | None (no Service Worker registered; no offline cold-launch cache) | `tests/test_browser_acoustic_acceptance.py` |
| **6. Browser Audio Capture & AFSK Demodulation** | Microphone `MediaStream` (via `ScriptProcessorNode` 2048-sample blocks) or uploaded `.wav` $\rightarrow$ `Uint8Array` payload ($\le 4096$ B) | `tfp-foundation-protocol/tfp_demo/static/acoustic_receiver.html:283-355`, `tfp-foundation-protocol/tfp_demo/static/acoustic_stream.js:4-96` | Sample rate check ($8000\text{--}96000\text{ Hz}$); 24 timing hypotheses ($0, \pm 1.5\%$ drift $\times 8$ phase offsets) at hardcoded 1200 baud; `0x7E` sync ($\ge 2$ flags), `1 <= length <= 4096`, `crc16Ccitt` | Processes in 2048-sample slices; retains $< 1$ bit of PCM buffer + at most one 4096-byte frame per hypothesis; `seen` set capped at 128 hashes | `seen` set in memory (max 128 entries) | `tests/test_browser_acoustic_acceptance.py` |
| **7. Browser Bulletin Admission & Display** | `Uint8Array` payload $\rightarrow$ UTF-8 / JSON parse $\rightarrow$ DOM display & `localStorage` | `tfp-foundation-protocol/tfp_demo/static/acoustic_receiver.html:357-495, 840-930` | Validates JSON types (`id`, `rev >= 1`, `body`, `title`), checks local publisher pinning & revision watermarks; **does NOT verify Ed25519 signatures** (`verification: 'signature_unverified'`) | `seenPacketHashes` max 128; `tfp_transmissions` archive capped at 20 items; `tfp_bulletin_watermarks` unbounded per unique `(pub, id)` | `localStorage` keys `tfp_transmissions` (last 20) and `tfp_bulletin_watermarks` (unverified packets can currently advance watermarks) | `tests/test_browser_acoustic_acceptance.py` |

---

## 2. Trace of Path 2: Separate Fountain / Media Path

End-to-end flow:
`ContentDefinedChunker` / `MediaStreamPackager` $\rightarrow$ `FountainEncoder` / `FountainStreamer` $\rightarrow$ UDP / Byte Stream $\rightarrow$ `FountainStreamReceiver` / `FountainDecoder`.

| Stage | Input $\rightarrow$ Output Format | Implementation Location | Validation | Resource Limits | Persistence Behavior | Relevant Tests |
|---|---|---|---|---|---|---|
| **1. Content-Defined Chunking & Manifest Packaging** | Raw `bytes` $\rightarrow$ `ChunkRecipe` / `MediaManifest` + `list[bytes]` chunks + `MerkleTree` | `tfp_core_v4/cdc.py:85-259`, `tfp-foundation-protocol/tfp_client/lib/media/stream_packager.py:30-185` | SHA3-256 per chunk, SHA3-256 root hash / Merkle root, `sum(chunk_sizes) == total_size` | Core FastCDC: `min=512, target=1024, max=4096` B; MediaStreamPackager: `min=4096, target=16384, max=65536` B | In-memory or persisted to SQLite `recipes`/`chunks` via `TFPNode` | `tests/test_media_fountain_stream.py`, `tests/test_recipe_integrity_acceptance.py` |
| **2. Core Fountain Codec** | Chunk `bytes` $\rightarrow$ `list[FountainDroplet]` ($K$ systematic degree-1 droplets `seed = 0..K-1`, plus repair droplets with Robust Soliton degree & HMAC-SHA3-256 seed schedule) | `tfp_core_v4/fountain.py:22-439` | `symbol_size >= 16` (default 256 B); `verify_droplet_seed_authenticity` checks seed/degree/indices deterministically; `FountainDecoder.decode` has degree-1 systematic fast path (`fountain.py:307-331`) + GF(2) Gaussian elimination + SHA3-256 root hash check | Core wire format (`FountainDroplet.serialize`): `10 + 2*degree + symbol_size` bytes (incompatible with media streamer header) | Stored in SQLite `droplets` table when published via `TFPNode` | `tests/test_honest_fountain_erasure.py`, `tests/test_deterministic_seed_schedule.py` |
| **3. Media Fountain Streamer** | `MediaManifest` + `list[bytes]` chunks $\rightarrow$ `MANIFEST_MAGIC (b"FM")` packets (24 B header + JSON) interleaved with `PACKET_MAGIC (b"FD")` `MediaDropletPacket` (40 B header + `symbol_size` payload) | `tfp-foundation-protocol/tfp_client/lib/media/fountain_streamer.py:45-419` | 16-byte truncated HMAC-SHA3-256 tag using shared `secret_key` (`b"tfp-default-streaming-salt"`) | Default `symbol_size = 512` B; 40-byte header per droplet; FLUTE-style manifest repeat (`repeat_manifest=3`, `manifest_interval=10`) | Stateless generator / UDP socket sender | `tests/test_media_fountain_stream.py`, `tests/test_flute_late_join.py` |
| **4. Media Fountain Receiver** | Wire datagram `bytes` (`FM` manifest or `FD` droplet) $\rightarrow$ Reconstructed chunks & assembled media `bytes` | `tfp-foundation-protocol/tfp_client/lib/media/receiver.py:69-692` | Checks shared-key HMAC tag, validates manifest bounds, verifies chunk SHA3-256 against manifest before saving or assembling | `max_sessions=32`, `max_droplets_per_chunk=512`, `max_chunks_per_session=128`, `session_ttl_seconds=600.0`, manifest file $\le 1\text{ MB}$ | Atomic `.tmp_*` $\rightarrow$ `os.replace` checkpoints per chunk (`chunk_<idx>_<sha3>.dat`) and HMAC-signed `manifest.json` in `checkpoint_dir/session_<id>` | `tests/test_media_fountain_stream.py`, `tests/test_receiver_checkpoints.py`, `tests/test_receiver_resource_limits.py` |

---

## 3. Classification of Current Capabilities

### A. Implemented & Verified Behavior
- **Python Complete-Bulletin Lifecycle**: `prepare_bulletin_package` and `import_bulletin_package` (`tfp_core_v4/bulletin.py`) with Ed25519 v2 signing (`tfp_core_v4/bulletin_identity.py`), atomic directory staging/backup, Bell 202 1200/300-baud AFSK WAV synthesis/demodulation, and SQLite admission/watermarking (`tfp_core_v4/node.py`).
- **Browser 1200-Baud AFSK Demodulation**: `IncrementalAFSKReceiver` (`acoustic_stream.js`) incrementally demodulates 1200-baud Bell 202 PCM with $\pm 1.5\%$ clock drift tolerance and bounded per-hypothesis memory ($\le 4096$ B frame).
- **Python Fountain & Media Streaming**: `FountainEncoder`/`FountainDecoder` (`tfp_core_v4/fountain.py`, including the degree-1 systematic fast path at lines 307–331) and bounded `FountainStreamReceiver` (`tfp_client/lib/media/receiver.py`) over UDP/byte streams.

### B. Stubs or Demonstrations
- **Browser Self-Test Buttons (`playTestTone`, `playTestVoiceMemo`, `playSimulatedVoicePcm`)**: Located in `acoustic_receiver.html:631-734, 812-827`. They play a synthesized tone/buzz and use `setTimeout` to render a hardcoded `[SIMULATED]` banner without passing through the demodulator (`playTestTone` even writes a dummy CRC `0x29 0xB1` at line 650).
- **Publisher Trust State**: Both Python (`tfp_core_v4/bulletin.py:172`, `tfp_core_v4/node.py:731`) and the browser (`acoustic_receiver.html:420`) hardcode `publisher_trust = "not_established"`. There is no trusted-publisher key store or trust-policy evaluation in the browser.

### C. Advertised Behavior Without Corresponding Evidence
- **"Zero-Install Acoustic Receiver" for Remote Smartphones (`tfp_core_v4/cli.py:615-618`)**: CLI output advertises *"Client Support: Weak smartphones (Chrome, Safari, Opera Mobile)"*, but binds to `127.0.0.1` (`cli.py:628`), serves plain HTTP (which blocks `getUserMedia` on remote phones), registers no Service Worker for offline reopening, and leaves browser audio constraints at default `audio: true` (allowing mobile voice DSP to suppress modem tones).
- **Browser Offline Cold-Launch**: `tests/test_browser_acoustic_acceptance.py:148-150` calls `page.reload()` *before* `page.context.set_offline(True)`, testing in-memory interaction after disconnect rather than opening the page while offline.
- **300-Baud Fallback in Browser**: Python's `AFSKDemodulator.decode_wav(..., fallback_300=True)` supports 300-baud fallback, whereas the browser's `IncrementalAFSKReceiver` (`acoustic_stream.js:17`) is hardcoded to `sampleRate / 1200`.
- **Public Broadcast Anti-Pollution in `fountain_streamer.py`**: Uses a symmetric HMAC with a default static key (`b"tfp-default-streaming-salt"`, line 252). In a public broadcast, any receiver holding that symmetric key can forge tags.

### D. Existing Functionality to Reuse
- `tfp_core_v4/bulletin_identity.py`: Canonical v2 envelope `["TFP_BULLETIN", 2, id, rev, title, sha3_256(body), pub]` and admission rules.
- `tfp_core_v4/bulletin.py`: `prepare_bulletin_package`, `estimate_bulletin_airtime`, and `import_bulletin_package`.
- `tfp-foundation-protocol/tfp_demo/static/acoustic_stream.js`: `IncrementalAFSKReceiver` state machine and bounded hypothesis buffer.
- `tfp_core_v4/fountain.py`: `FountainEncoder` and `FountainDecoder` (for Phase G transport comparisons).

### E. Compatibility Constraints
- **Wire Format Compatibility**: The browser must verify Python's existing v2 bulletin JSON format (`{"v":2,"id":...,"rev":...,"title":...,"body":...,"pub":...,"sig":...}`) where `content_hash` is **SHA3-256** of `\n`-normalized UTF-8 `body` and `sig` is **Ed25519** over the canonical array. Changing SHA3-256 to SHA-256 would break Python compatibility (`bulletin_identity.py:45`), so the browser must compute SHA3-256 in JS and verify Ed25519 (via WebCrypto `SubtleCrypto` with a deterministic JS Ed25519 fallback).
- **No `SharedArrayBuffer` Requirement**: Avoiding `SharedArrayBuffer` preserves compatibility with standard static hosting without requiring `Cross-Origin-Opener-Policy` / `Cross-Origin-Embedder-Policy` headers.

---

## 4. Baseline Test Selection & Recorded Results

### Environment
- **OS / Platform:** Windows (`win32`, `10.0.26200`)
- **Python:** `Python 3.14.0` (`C:\Python314\python.exe`)
- **Pytest:** `pytest-8.3.5` (with `playwright`, `hypothesis-6.151.10`, `pytest-timeout-2.4.0`)
- **Git Revision:** `d53f5f7fbe4de97feeedb09f7b2ce5dd4ab2fea8` on branch `feat/device-to-phone-broadcast-baseline`

### Executed Baseline Commands & Results
1. **Acoustic & Browser Acceptance Suite:**
   ```powershell
   python -m pytest tests/test_acoustic_multipath_sweep.py tests/test_acoustic_bulletin_verification.py tests/test_browser_acoustic_acceptance.py -v
   ```
   - **Result:** `23 passed, 791 warnings in 20.41s` (warnings are Python 3.14 `pytest_asyncio` deprecation notices).
2. **Bulletin Identity, Watermarks, Admission & Fountain Suite:**
   ```powershell
   python -m pytest tests/test_bulletin_workflow.py tests/test_bulletin_watermarks.py tests/test_bulletin_admission_recovery.py tests/test_media_fountain_stream.py tests/test_honest_fountain_erasure.py -v
   ```
   - **Result:** `51 passed, 1994 warnings in 4.21s`.

---

## 5. Concrete Implementation Plan (Phases B–J)

1. **Phase B (Supported Deployment Definition):**
   - Document the **Prepared-Phone Scenario** (trusted origin preload $\rightarrow$ Service Worker asset caching $\rightarrow$ trusted publisher key provisioning $\rightarrow$ offline outage operation) and the **Fresh-Phone Scenario** constraints (including the `<input type="file">` WAV recording fallback that works without `getUserMedia`).
2. **Phase C (Receiver Readiness & Offline Cold-Launch Lifecycle):**
   - Add `tfp-foundation-protocol/tfp_demo/static/acoustic_sw.js` with coherent versioned asset caching (`acoustic_receiver.html`, `acoustic_stream.js`, `receiver_config.json`).
   - Update `acoustic_receiver.html` to report all 8 readiness states (origin security, mic API availability, permission state, input availability, capture active, suspended/interrupted state, offline cache readiness, trusted publisher key configuration), request raw audio constraints (`echoCancellation: false`, `noiseSuppression: false`, `autoGainControl: false`), report effective `MediaStreamTrack.getSettings()`, and prevent duplicate capture pipelines.
   - Add Playwright cold-reopen offline tests (`context.set_offline(True)` *before* opening a new page and navigating).
3. **Phase D (Browser Bulletin Verification & Trust Policy):**
   - Implement exact v2 canonical envelope construction (`SHA3-256` + `Ed25519` verification via WebCrypto `SubtleCrypto` with pure-JS fallback) in `acoustic_stream.js` / `acoustic_receiver.html`.
   - Enforce strict separation between `unsigned`, `invalid_signature` (rejected immediately), `valid_signature_unknown_key`, and `trusted_publisher`.
   - Prevent unverified or unknown-key bulletins from replacing trusted bulletins or poisoning authoritative revision watermarks.
   - Validate against shared Python/browser test vectors covering all 9 required edge cases.
4. **Phase E (Bounded AudioWorklet Processing & Gap Telemetry):**
   - Add a bounded `AudioWorklet` processor (`tfp-afsk-worklet.js` / inline Blob module with fallback to `ScriptProcessorNode` for legacy mocks) with explicit queue caps, sample-gap sequence tracking, overload drop counters, and UI/worker stall measurements.
5. **Phase F (Physical Baseline Procedure & Tooling):**
   - Provide a reproducible physical baseline harness (`scripts/physical_acoustic_trial.py` + documentation) that generates a novel signed bulletin WAV, records metadata, and evaluates captured phone recordings without conflating synthetic tests with hardware trials.
6. **Phase G (Corrected Transport Comparison Model):**
   - Build a reproducible time-based burst-channel comparison harness (`scripts/compare_transport_schemes.py` + unit tests) comparing whole-bulletin repetition, bounded fragmentation, and `tfp_core_v4/fountain.py` with full framing, manifest, signature, and late-join accounting.
7. **Phases H & I (Conditional Gates):**
   - Evaluate whether Phase G justifies authenticated repair batches (Phase H) or Phase F warrants alternative modems (Phase I); document evidence-based decisions.
8. **Phase J (Operator Workflow & Reporting):**
   - Enhance CLI operator commands (`tfp_core_v4/cli.py`) so preparation, playback, listener reception, and cryptographic verification are tracked as distinct states, accompanied by an operator guide and full phase reporting.
