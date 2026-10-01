# Meshtastic LoRa Bridge & Kiwix ZIM Delta-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate The Foundation Protocol with physical Meshtastic LoRa radio networks for ACK-free background file carousel broadcasting (10 KB – 250 KB), and implement FastCDC delta-synchronization for Kiwix OpenZIM archives (100 MB – 2 GB) over local multicast/mesh.

**Architecture:** 
1. Build `tfp_transport/meshtastic_bridge.py` encapsulating TFP `FountainDroplet` payloads into standard Meshtastic Data packets via asynchronous SLIP serial framing, with strict duty-cycle rate limiting (ETSI/FCC).
2. Build `tfp_core_v4/zim_sync.py` to perform FastCDC cluster-aware diffing between OpenZIM editions, generating minimal `ZimPatchRecipe` streams for rateless distribution.
3. Expose unified CLI subcommands (`tfp lora-broadcast`, `tfp lora-listen`, `tfp zim-delta`, `tfp zim-apply`) preserving all existing security invariants (constant-time HMAC, anti-pollution gating, zero unhandled async tasks).

**Tech Stack:** Python 3.11+, `asyncio`, `pyserial-asyncio`, `struct`, TFP `FountainCodec` (GF(2) Soliton), TFP `ContentDefinedChunker` (FastCDC 64-bit rolling gear matrix), Meshtastic protobuf/serial wire format.

**Spec:** Strategic Appraisal & Adversarial Analysis (2026-10-01).

---

## Global Constraints

- **Zero-Mock Invariant**: All tests must verify real mathematical encoders/decoders and serial framing with zero `unittest.mock` inside production packages (`no-mock-in-production.yml`).
- **Async Concurrency Hygiene**: No blocking calls or `time.sleep()` in coroutines (`no-blocking-sleep-in-async.yml`); all serial reads/writes and timers must use `asyncio`.
- **Cryptographic Hygiene**: Use constant-time comparisons (`hmac.compare_digest`) for hashes and tags (`constant-time-crypto-compare.yml`); use `secrets` or `os.urandom` for nonces/seeds (`no-unshielded-random.yml`).
- **Memory Boundedness**: Streaming and chunking must operate in bounded chunk windows ($\le 64$ MB resident RAM) to ensure viability on low-resource edge devices (Raspberry Pi 3/4, phones).
- **RF Spectrum Compliance**: Airtime pacing must enforce regional regulatory ceilings (1% duty cycle EU868, channel utilization $\le 5\%$ US915) via `SpectrumMask` logic.

---

## Review Focus

1. **Airtime runaway under error loops**: If radio hardware disconnects or serial buffers back up, the pacer must fail closed and pause rather than dump buffered packets in a rapid burst.
2. **Droplet anti-pollution filter bypass**: Malformed or unauthenticated LoRa packets injected over-the-air must be dropped at admission before touching the Soliton matrix decoder.
3. **ZIM cluster boundary desynchronization**: Edited ZIM files must maintain cluster alignment so FastCDC achieves $\ge 90\%$ chunk deduplication on minor revisions.
4. **Serial buffer fragmentation and frame corruption**: Partial SLIP frames across USB disconnects must not cause infinite parser loops or memory bloat.
5. **Disk exhaustion on low-storage edge nodes**: ZIM delta application must apply in-place or via streaming chunks without requiring $2\times$ archive disk space.

---

## Things to Avoid & Look Out For (The Minefield)

### 1. RF & Meshtastic Operational Red Lines
- **DO NOT broadcast on Channel 0 (Public LongFast)**: Meshtastic's primary channel is intended for low-bandwidth life-safety text messages. Blasting fountain packets there will congest the network and get your node banned. *Always assign a dedicated secondary channel (e.g. `TFP-DATA`) with its own pre-shared key.*
- **DO NOT use multi-hop flooding (`hop_limit > 1`)**: LoRa uses managed flood routing. A 100-packet broadcast with `hop_limit=3` will cause thousands of repeater retransmissions. *Always set `hop_limit=0` (local direct footprint) or `hop_limit=1` (single repeater hop).*
- **DO NOT omit duty-cycle pacing**: Transmitting continuously without listening will violate FCC Part 15 / ETSI EN 300 220 rules and overheat small ESP32 radio power amplifiers.

### 2. ZIM / Storage Engineering Pitfalls
- **DO NOT compress already-compressed clusters**: ZIM clusters are already zstd/xz compressed. Re-compressing them consumes CPU and expands data size.
- **DO NOT load full archives into RAM**: Wikipedia ZIMs range from 5GB to 100GB. Read files strictly in rolling 1MB–4MB chunks.

### 3. Community Engagement Pitfalls
- **DO NOT use crypto/Web3 terminology**: Terms like "tokens", "coins", "airdrop", or "incentive layer" will get you permanently banned from amateur radio and civil defense communities. Use strictly: *"rateless fountain erasure coding", "Luby Transform", "FastCDC deduplication", "packet radio framing", "civil defense data carousel"*.

---

## Things to Prepare Beforehand (Prerequisites Checklist)

### 1. Hardware Bench ($40–$50)
- [ ] 2x **Heltec WiFi LoRa 32 V3** (ESP32-S3 + SX1262) or LilyGO T-Echo / T-Beam boards (matching your regional frequency: 915 MHz Americas/Asia, 868 MHz Europe).
- [ ] 2x Data-capable USB-C cables.
- [ ] 2x Tuned omnidirectional antennas (supplied with boards).

### 2. Software & Dependencies
- [ ] Meshtastic firmware flashed onto both boards via [flasher.meshtastic.org](https://flasher.meshtastic.org/).
- [ ] Test environment verified with `powershell -ExecutionPolicy Bypass -File scripts/agent/run_agent_gate.ps1`.
- [ ] Add `pyserial-asyncio>=0.6` to `pyproject.toml` under optional dependencies `[project.optional-dependencies] meshtastic = ["pyserial-asyncio>=0.6"]`.

### 3. Test Fixture Datasets
- [ ] Create synthetic micro-bundle (1.5 KB voice memo).
- [ ] Create synthetic small bundle (25 KB emergency triage guide).
- [ ] Procure/generate a pair of small real ZIM archives (e.g. two revisions of a 5MB Kiwix sample archive) for test fixtures in `tests/fixtures/zim/`.

---

## File Structure & Responsibilities

| File Path | Responsibility |
| :--- | :--- |
| `tfp_transport/meshtastic_bridge.py` | SLIP serial framing, Meshtastic packet packaging, asynchronous transmission queue, duty-cycle pacing. |
| `tfp_core_v4/zim_sync.py` | ZIM cluster-aware delta extraction, `ZimPatchRecipe` generation, chunk delta reassembly. |
| `tfp_transport/spectrum_encap.py` | Existing duty-cycle and airtime calculation engine (referenced by Meshtastic bridge). |
| `tfp_core_v4/cli.py` | CLI subcommands: `lora-broadcast`, `lora-listen`, `zim-delta`, `zim-apply`. |
| `tests/test_transport_meshtastic_bridge.py` | Real asynchronous loopback tests verifying frame packing, pacing, and packet admission. |
| `tests/test_zim_delta_sync.py` | End-to-end ZIM diffing, patch serialization, and bit-exact archive reconstruction. |

---

## Implementation Tasks

### Task 1: Meshtastic Serial Wire Framing & Packet Adapter

**Files:**
- Create: `tfp_transport/meshtastic_bridge.py`
- Modify: `pyproject.toml:50-55`
- Test: `tests/test_transport_meshtastic_bridge.py`

**Interfaces:**
- Consumes: `tfp_core_v4.fountain.FountainDroplet`, `tfp_transport.fountain.TransportFountainChannel`
- Produces: `MeshtasticFrameCodec.encode_packet()`, `MeshtasticFrameCodec.decode_packet()`, `MeshtasticSerialTransport`

- [ ] **Step 1: Write failing tests for Meshtastic SLIP framing and droplet encapsulation**
  ```python
  def test_meshtastic_frame_encode_decode_roundtrip():
      droplet_payload = b"X" * 192
      frame = MeshtasticFrameCodec.encode(
          session_id=0x12345678,
          seed=42,
          degree=3,
          data=droplet_payload,
          channel_index=1,
          hop_limit=0,
      )
      decoded = MeshtasticFrameCodec.decode(frame)
      assert decoded.session_id == 0x12345678
      assert decoded.seed == 42
      assert decoded.degree == 3
      assert decoded.data == droplet_payload
      assert decoded.hop_limit == 0
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_transport_meshtastic_bridge.py -v`
  Expected: FAIL with `NameError: name 'MeshtasticFrameCodec' is not defined`.

- [ ] **Step 3: Implement `MeshtasticFrameCodec` in `tfp_transport/meshtastic_bridge.py`**
  Implement SLIP framing (0xC0 delimiters, 0xDB escape sequences) with compact 8-byte TFP binary header: `[SessionID: 4B, Seed: 2B, Degree: 1B, Flags: 1B] + Payload`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_transport_meshtastic_bridge.py -v`
  Expected: PASS.

---

### Task 2: Asynchronous Airtime & Duty-Cycle Pacing Controller

**Files:**
- Modify: `tfp_transport/meshtastic_bridge.py`
- Test: `tests/test_transport_meshtastic_bridge.py`

**Interfaces:**
- Consumes: `tfp_transport.spectrum_encap.SpectrumMask`
- Produces: `AirtimePacer.calculate_airtime(payload_len, sf, bw, cr) -> float`, `AirtimePacer.wait_for_slot()`

- [ ] **Step 1: Write failing test for LoRa airtime calculation and token-bucket rate limiter**
  ```python
  def test_airtime_calculation_and_pacing():
      # Semtech SX1262 formula test for SF7, BW125kHz, CR 4/5, 200B payload
      airtime_ms = AirtimePacer.compute_lora_airtime_ms(payload_len=200, sf=7, bw_khz=125, cr=1)
      assert 300 < airtime_ms < 450
      
      # 1% duty cycle test: transmitting 400ms requires >= 39.6s pause
      pacer = AirtimePacer(duty_cycle_fraction=0.01)
      delay = pacer.calculate_required_delay(airtime_ms=400)
      assert delay >= 39.0
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_transport_meshtastic_bridge.py -k test_airtime -v`
  Expected: FAIL.

- [ ] **Step 3: Implement `AirtimePacer` using deterministic LoRa preamble/symbol math**
  Implement standard Semtech LoRa symbol duration $T_s = \frac{2^{SF}}{BW}$ and preamble/payload symbol counting. Integrate `asyncio.sleep` (never blocking `time.sleep`) to pace droplet transmission.

- [ ] **Step 4: Run test to verify it passes**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_transport_meshtastic_bridge.py -k test_airtime -v`
  Expected: PASS.

---

### Task 3: Meshtastic Serial Transport Daemon & CLI Commands

**Files:**
- Modify: `tfp_transport/meshtastic_bridge.py`
- Modify: `tfp_core_v4/cli.py`
- Test: `tests/test_transport_meshtastic_bridge.py`

**Interfaces:**
- Consumes: `tfp_core_v4.fountain.FountainStreamer`, `tfp_core_v4.fountain.FountainStreamReceiver`
- Produces: `async def run_lora_broadcast(...)`, `async def run_lora_listen(...)`

- [ ] **Step 1: Write failing test for asynchronous loopback serial broadcast and reception**
  ```python
  @pytest.mark.asyncio
  async def test_lora_simulated_serial_stream_reconstruction():
      source_data = b"CRITICAL CIVIL DEFENSE BULLETIN: PURIFY WATER BY ROLLING BOIL FOR 3 MINUTES." * 10
      loopback_stream = SimulatedSerialStream()
      broadcaster = MeshtasticBroadcaster(loopback_stream, pacer=AirtimePacer(duty_cycle_fraction=1.0))
      listener = MeshtasticListener(loopback_stream)
      
      # Broadcast droplets with 30% redundancy
      asyncio.create_task(broadcaster.broadcast_bytes(source_data, redundancy=0.30))
      recovered = await listener.receive_until_complete(timeout=10.0)
      assert recovered == source_data
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_transport_meshtastic_bridge.py -k test_lora_simulated -v`
  Expected: FAIL.

- [ ] **Step 3: Implement `MeshtasticBroadcaster`, `MeshtasticListener`, and CLI subcommands**
  Connect `tfp_core_v4/cli.py` to support `tfp lora-broadcast <file>` and `tfp lora-listen --out <file>`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_transport_meshtastic_bridge.py -v`
  Expected: PASS.

---

### Task 4: FastCDC ZIM Cluster-Aware Delta Extractor & Patcher

**Files:**
- Create: `tfp_core_v4/zim_sync.py`
- Modify: `tfp_core_v4/cli.py`
- Test: `tests/test_zim_delta_sync.py`

**Interfaces:**
- Consumes: `tfp_core_v4.cdc.ContentDefinedChunker`, `tfp_core_v4.cdc.ChunkRecipe`, `tfp_core_v4.node.TFPNode`
- Produces: `ZimDeltaEngine.compute_delta(base_zim_path, target_zim_path) -> ZimPatchRecipe`, `ZimDeltaEngine.apply_patch(base_zim_path, patch_path, out_path)`

- [ ] **Step 1: Write failing test for ZIM diffing and patch reconstruction**
  ```python
  def test_zim_delta_extraction_and_reconstruction(tmp_path):
      base_zim = tmp_path / "v1.zim"
      target_zim = tmp_path / "v2.zim"
      
      # Generate base archive and 5% mutated target archive
      shared_clusters = [secrets.token_bytes(64 * 1024) for _ in range(20)]
      base_zim.write_bytes(b"".join(shared_clusters))
      
      mutated_clusters = list(shared_clusters)
      mutated_clusters[5] = secrets.token_bytes(64 * 1024)  # 1 cluster modified
      target_zim.write_bytes(b"".join(mutated_clusters))
      
      patch_file = tmp_path / "patch.tfp"
      engine = ZimDeltaEngine(chunk_target_kb=64)
      recipe = engine.create_patch(base_path=base_zim, target_path=target_zim, patch_out=patch_file)
      
      # Assert patch size is approximately 1 cluster (~64KB), not full 1.2MB
      assert patch_file.stat().st_size < 100 * 1024
      
      reconstructed_zim = tmp_path / "reconstructed.zim"
      engine.apply_patch(base_path=base_zim, patch_path=patch_file, out_path=reconstructed_zim)
      assert reconstructed_zim.read_bytes() == target_zim.read_bytes()
  ```

- [ ] **Step 2: Run test to verify it fails**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_zim_delta_sync.py -v`
  Expected: FAIL with `ModuleNotFoundError: No module named 'tfp_core_v4.zim_sync'`.

- [ ] **Step 3: Implement `ZimDeltaEngine` in `tfp_core_v4/zim_sync.py`**
  Use `ContentDefinedChunker` with FastCDC gear matrix. Extract chunk hash set of `base_zim`, stream `target_zim`, emit only novel chunk payloads and the index reconstruction map. Wire to `cli.py` (`tfp zim-delta`, `tfp zim-apply`).

- [ ] **Step 4: Run test to verify it passes**
  Run: `.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_zim_delta_sync.py -v`
  Expected: PASS.

---

### Task 5: Quality Gate & AST Code Graph Verification

**Files:**
- Modify: `CODE_GRAPH_SNAPSHOT.json`
- Test: All suites

**Interfaces:**
- Enforces: 4-stage Quality Gate (`run_agent_gate.ps1`), AST graph snapshot sync.

- [ ] **Step 1: Refresh AST Code Graph snapshot**
  Run: `.\.dist_verify\runtime\Scripts\python.exe scripts/code_graph.py --json`
  Verify `CODE_GRAPH_SNAPSHOT.json` updates cleanly.

- [ ] **Step 2: Execute full 4-stage quality gate**
  Run: `powershell -ExecutionPolicy Bypass -File scripts/agent/run_agent_gate.ps1`
  Expected: 
  - Stage 1: Ruff clean (`E4,E7,E9,F`)
  - Stage 2: Mypy clean
  - Stage 3: Bandit clean (zero `-ll` findings)
  - Stage 4: Pytest 100% passing
