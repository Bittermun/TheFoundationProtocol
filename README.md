# The Foundation Protocol (TFP v4.0)

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-Passing%20(49%2F49)-brightgreen)](https://github.com/Bittermun/TheFoundationProtocol)
[![Architecture](https://img.shields.io/badge/Architecture-Offline--First%20Narrow--Waist-purple)](#architecture--the-narrow-waist)

> **A sovereign, zero-infrastructure content and compute distribution protocol engineered for disaster zones, austere environments, civil defense, and censorship-resistant global knowledge preservation.**

---

## Overview

The Foundation Protocol (TFP) enables reliable knowledge distribution over **any physical medium** without relying on centralized servers, domain name registries, or active internet infrastructure. From high-frequency radio and community Wi-Fi meshes to classroom PA speakers and smartphone microphones, TFP treats all networks as lossy, intermittent broadcast channels.

### Core Architectural Pillars
- **Rateless Fountain Erasure Coding**: Systematic Luby Transform and RaptorQ-compatible erasure coding over GF(2). Ingests content, generates rateless repair droplets, and recovers original data from arbitrary droplet subsets once rank $K$ is satisfied.
- **Content-Defined Chunking (FastCDC)**: 64-bit rolling gear matrix chunking with content-addressed SHA3-256 deduplication. Minimizes bandwidth across versioned archives.
- **Physical Acoustic Modulation (Bell 202 AFSK)**: 1200 baud audio frequency shift keying (1200 Hz Mark / 2200 Hz Space) with HDLC framing and CRC16-CCITT integrity. Transmits bulletins through radio speakers and classroom PA systems into ordinary phone microphones.
- **Audio-Pocket 1200 bps Vocoder**: Linear predictive coding (LPC) that compresses 10-second human voice memos into ~1.5 KB audio chirps, surviving high-noise channels.
- **Durable SQLite Persistence**: ACID-backed node storage (`recipes`, `chunks`, `droplets`) that decouples writer settings from reader configurations.
- **Hybrid Lexical + Semantic Search**: In-memory and SQLite-backed search combining BM25 keyword ranking with MinHash Locality-Sensitive Hashing (LSH).
- **Kiwix ZIM & Zero-Install Web Reader**: Exports offline libraries into Kiwix-compatible `.zim` directory hierarchies and serves zero-install acoustic receiver web apps for low-resource devices.

---

## Architecture & The "Narrow Waist"

Like the Internet Protocol (IP), TFP organizes around a strict "narrow waist" where diverse physical transports converge on a unified wire datagram format before branching into application-layer representations:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            APPLICATIONS & READERS                           │
│  Offline Kiwix ZIM  │  Audio Scholar Appliance  │  Browser Acoustic Reader  │
│  Hybrid Search      │  Voice Memo Dispatch      │  Protocol Visualizer      │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────▼─────────────────────────────────────┐
│                             PERSISTENT STORAGE                              │
│  SQLite Node Database  │  FastCDC Chunks  │  SHA3-256 Merkle Recipes        │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────▼─────────────────────────────────────┐
│                           THE PROTOCOL NARROW WAIST                         │
│             Rateless Fountain Coding (Systematic + Soliton Repair)          │
│             FLUTE RFC 6726 Periodic Manifest Interleaving (FM / FD)         │
│             O(1) Anti-Pollution HMAC-SHA3-256 Authentication Tag            │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────▼─────────────────────────────────────┐
│                             FRAMING & CODECS                                │
│       RadioFrame MTU Packaging  │  Bell 202 HDLC Framing  │  LPC Vocoder    │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
┌───────────────────────────────────────▼─────────────────────────────────────┐
│                            PHYSICAL TRANSPORTS                              │
│  UDP Multicast  │  VHF/UHF Packet Radio (AX.25)  │  Acoustic PA / Mic Audio │
│  LoRa Physical  │  Wi-Fi Community Mesh          │  USB / Sneakernet Flash  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Prerequisites
- Python 3.11, 3.12, or 3.13
- Git

### Install from Source
```bash
git clone https://github.com/Bittermun/TheFoundationProtocol.git
cd TheFoundationProtocol

# Install production dependencies
pip install -e .

# Install development and test tooling
pip install -e ".[test,dev]"
```

---

## Command Line Interface (CLI)

The unified `tfp` CLI provides 16 subcommands for publishing, streaming, searching, and managing protocol operations:

### 1. Publishing & Ingestion
```bash
# Publish a file into FastCDC content-addressed SQLite storage
tfp publish path/to/manual.pdf --title "Emergency Triage Guide"

# Ingest a web article or Markdown document into an offline mobile bundle
tfp ingest-article https://en.wikipedia.org/wiki/Water_purification --out water_guide.html
```

### 2. Rateless Streaming & Reception
```bash
# Stream a file over UDP using rateless fountain packets (30% repair redundancy)
tfp stream path/to/video.mp4 --redundancy 0.30

# Launch interactive protocol visualizer (SSE telemetry + 60 FPS canvas)
tfp visualize --port 8080
```

### 3. Persistent Search & Retrieval
```bash
# Search stored articles using hybrid BM25 + MinHash LSH across SQLite
tfp search "water purification solar distillation" --top-k 5

# Fetch and reconstruct stored content by root hash
tfp fetch cd07a285cf65fbbda540a959a3a91c2ae0d0bf17b5d36bedb5404a834abfdee8 --output recovered.pdf

# Inspect recipe metadata, chunk hashes, and Merkle tree root
tfp inspect cd07a285cf65fbbda540a959a3a91c2ae0d0bf17b5d36bedb5404a834abfdee8
```

### 4. Acoustic Delivery & Radio Operations
```bash
# Modulate text or binary payload into Bell 202 AFSK audio WAV
tfp audio-encode "CRITICAL BULLETIN: Boil water before consumption." --out-wav alert.wav --baud 1200

# Demodulate AFSK WAV audio recording with CRC16 validation
tfp audio-decode alert.wav --baud 1200

# Fragment file into physical radio MTU frames
tfp radio-frame path/to/data.bin --mtu 256

# Serve zero-install acoustic microphone receiver for phones
tfp acoustic-receiver --port 8080

# Launch screenless zero-touch Audio Scholar triage daemon
tfp audio-scholar --port 9999 --speech-rate 140
```

### 5. Offline Library & Voice Memo Tooling
```bash
# Export articles to Kiwix-compatible ZIM directory layout
tfp export-zim data/articles/ --out zim_export/ --title "Community Health Library"

# Compress spoken audio WAV into 1200 bps voice memo
tfp voice-memo compress voice_input.wav --out memo.vm --callsign MEDIC01

# Decompress voice memo back to audible WAV
tfp voice-memo decompress memo.vm --out voice_output.wav
```

### 6. Verification
```bash
# Run automated self-verification test battery
tfp verify
```

---

## Verification & Testing

TFP enforces strict testing standards: **all tests operate against real mathematical implementations with zero mocks.**

### Run the Full Regression Battery
```bash
# Run all core, transport, security, and codec test suites
pytest tests/
```

### Test Suite Highlights
- **Security Authentication**: Validates strict HMAC enforcement and rejection of unauthenticated packets (`tests/test_security_auth.py`).
- **Reader Independence**: Verifies that stored content survives cold reboot when the reader runs different chunker or symbol settings (`tests/test_storage_reader_independence.py`).
- **Receiver State Bounding**: Proves that bursts of manifest-only packets respect `max_sessions` LRU bounds with zero memory leaks (`tests/test_receiver_comprehensive_bounds.py`).
- **FLUTE Late Join**: Drops opening packets and validates that late-joining receivers complete 100% bit-exact transfers via interleaved manifests (`tests/test_flute_late_join.py`).
- **Acoustic Physical Channel**: Verifies silence rejection, noise immunity, CRC16 rejection of corrupted audio, and room multipath recovery (`tests/test_acoustic_bulletin_verification.py`).

### Structural AST Code Graph
```bash
# Generate codebase structural statistics
python scripts/code_graph.py --stats

# Output GitHub-flavored Mermaid architecture flowchart
python scripts/code_graph.py --mermaid
```

---

## Specifications & Standards Compliance

| Component | Standard / Specification | Notes |
| :--- | :--- | :--- |
| **Erasure Coding** | RFC 6330 / RFC 5053 / Soliton | Rateless Gaussian elimination with systematic identity base |
| **Object Delivery** | FLUTE / RFC 6726 Section 3.3 | Periodic File Delivery Table (FDT) manifest interleaving |
| **Content Chunking**| FastCDC (64-bit Rolling Hash) | Gear matrix content-defined chunking with deduplication |
| **Authentication** | SHA3-256 / HMAC-SHA3-256 | O(1) anti-pollution packet tags and Merkle trees |
| **Audio Modulation**| Bell 202 Standard | 1200 baud AFSK (1200 Hz Mark / 2200 Hz Space) |
| **Framing** | HDLC Framing + CRC16-CCITT | 0x7E sync flags, bit stuffing, 16-bit cyclic redundancy check |
| **Speech Vocoder** | LPC-10 / Codec2 Architecture | 1200 bps parametric pitch and spectral envelope synthesis |
| **Offline Library** | OpenZIM Directory Standard | Compatible with Kiwix offline desktop and mobile readers |

---

## License

The Foundation Protocol is open-source software licensed under the [Apache License, Version 2.0](LICENSE).
