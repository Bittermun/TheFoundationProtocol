# Changelog

All notable changes to The Foundation Protocol will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [4.0.0] - 2026-09-20

### Security
- **Strict HMAC Enforcement**: Closed authentication bypass in `raptorq_ffi.py` and `fountain_real.py` where packets prefixed with `fallback_shard_` were returned prior to HMAC verification. HMAC validation is now executed first, raising `IntegrityError` on forged or missing signatures.
- **Client-Side Sanitization**: Eliminated stored and reflected XSS vulnerabilities in `acoustic_receiver.html` by replacing unescaped `innerHTML` interpolation with safe `textContent` / DOMPurify sanitization.
- **Anti-Pollution Tagging**: Validated O(1) HMAC anti-pollution tags on all incoming fountain droplets before buffering or decoding.

### Added
- **Durable SQLite Persistence**: `TFPNode` now persists recipes, FastCDC content-addressed chunks, and rateless droplets to SQLite (`~/.tfp/node_store.db` or `$TFP_DB_PATH`).
- **Storage Self-Sufficiency**: `TFPNode.fetch()` implements an instant fast-path for intact local chunks and decouples verification from the reader's FastCDC/symbol settings via recipe chunk size slicing.
- **Persistent Full-Text Search**: `tfp search` connects directly to SQLite archives, reassembling stored chunks and indexing title and body text into `HybridSearchEngine` (BM25 + MinHash).
- **FLUTE RFC 6726 Manifest Interleaving**: `FountainStreamer.stream_manifest_wire_packets` interleaves manifest wire packets periodically throughout transmission and at stream close, allowing late-joining receivers to recover complete transfers.
- **Receiver State Bounding**: `FountainStreamReceiver` enforces `max_sessions` LRU eviction across manifests, session timestamps, and reconstructed chunks, while purging orphaned `_chunk_meta` upon session reset.
- **Unified CLI Entrypoint**: Standardized packaging on `tfp = "tfp_core_v4.cli:main"` with 16 subcommands: `publish`, `stream`, `search`, `fetch`, `inspect`, `radio-frame`, `mesh-sim`, `visualize`, `ingest-article`, `audio-encode`, `audio-decode`, `acoustic-receiver`, `audio-scholar`, `export-zim`, `voice-memo`, and `verify`.
- **Packaging Data**: Bundled static web templates and HTML assets (`tfp_demo/static/*`) into wheel distributions.
- **Kiwix ZIM Exporter**: `tfp export-zim` packages ingested articles into Kiwix-compatible directory hierarchies with disambiguated slug titles.
- **Physical Acoustic Channel Verification**: Added automated test battery verifying 0-packet reception under pure silence, 0-packet reception under Gaussian white noise, strict CRC16 rejection of corrupted audio, and bit-exact recovery of novel emergency bulletins under simulated room echo.

### Changed
- **Packet Limit Parity**: Synchronized AFSK physical framing limits across sender and receiver to exactly 4,096 bytes (`MAX_AFSK_PAYLOAD_SIZE`).
- **FastCDC Gear Matrix Consolidation**: Deduplicated the 256-integer FastCDC gear hash matrix to canonical `tfp_core_v4.cdc`.
- **RaptorQ FFI Acceleration**: Re-routed `RaptorQAdapter` through `raptorq_ffi.py` to enable compiled Rust acceleration with seamless pure-Python fallback.
- **Acoustic Interface Transparency**: Explicitly labeled browser simulation controls as `[SIMULATION]` to distinguish synthesized demonstration tones from over-the-air DSP decoding.

### Fixed
- Fixed silent vocoder RMS frame encoding bug that caused valid audio frames to compress as silence.
- Fixed `export-zim` plain-text fallback `NameError: hashlib is not defined`.
- Fixed disposable lab docker-compose service alias resolution.
- Fixed session ID mismatch in end-to-end distribution integration test.
