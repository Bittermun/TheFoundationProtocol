# Receiver Reliability Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans and test-driven-development. Independent cache and crypto work may use dispatching-parallel-agents; integrate and review before publishing.

**Goal:** Repair the confirmed browser reception, cache-upgrade, and cryptographic-maintenance defects, with tests exercising the real connections.

**Architecture:** Preserve the prepared-phone receiver and canonical v2 bulletin format. Standardize worklet messages and buffer ownership, install complete offline releases into separate caches, and replace handwritten cryptographic primitives with a pinned maintained implementation bundled locally. Keep synchronous bulletin admission if a maintained synchronous verifier supports the existing contract.

**Tech Stack:** Python/pytest, Playwright Chromium, browser JavaScript, AudioWorklet, Service Worker Cache Storage; locally bundled maintained cryptography.

**Spec:** User-approved repair scope in this chat; deployment context in `docs/device_to_phone_deployment.md`.

## Global Constraints

- Preserve existing wire format, Python/browser canonical parity, trust separation, and replay watermarks.
- No runtime CDN dependency; prepared receiver must cold-open offline.
- No claim of physical-phone validation from synthetic browser audio.
- Preserve original checkout and its untracked research; use the isolated repair worktree.
- Publish repair branch and detailed GitHub explanation under the user's earlier authorization; do not merge.

## Review Focus

- Real transferred buffers must return to the producer after normal decoding and overload.
- Main-thread stalls must not silently stop reception or hide producer drops.
- Failed cache writes must preserve the old complete release; old tabs must retain matching assets.
- Unsupported native Ed25519 must still verify offline using maintained bundled code, fail closed on invalid inputs.
- Trust decisions and revision handling must retain behavior after reload and malformed/tampered signed packets.

## Task 1: Restore actual AudioWorklet reception

**Files:** `tfp-foundation-protocol/tfp_demo/static/acoustic_receiver.html`, `acoustic_worklet.js`, `tests/test_audio_worklet_contention_phase_e.py`.
**Interfaces:** Worklet sends `audio_block` with `buffer: ArrayBuffer`, `sampleCount`, `seq`, `frameStart`; consumer returns `return_buffer`. Align overload and sample-gap messages with real producer telemetry.

- [ ] Replace misleading live tests with a real MediaStream source playing a synthesized signed bulletin through the AudioWorklet; assert trusted display, >32 processed blocks, and returned-buffer reuse. Retain isolated controller tests clearly labeled as such.
- [ ] Run the new tests before production changes; expect no decoded bulletin/callbacks.
- [ ] Repair message decoding/ownership and overload/stall telemetry. Reset demodulation across actual missing samples so discontinuous audio is not concatenated.
- [ ] Test real main-thread contention, producer exhaustion, recovery, and stop/restart. Remove fake production stall helpers if no longer necessary.
- [ ] Run `python -m pytest tests/test_audio_worklet_contention_phase_e.py tests/test_browser_acoustic_acceptance.py tests/test_receiver_readiness_lifecycle.py -q`; expect all passing.

## Task 2: Make offline release upgrades coherent

**Files:** `acoustic_sw.js`, new cache-upgrade tests; root integrator updates any HTML/config version references.
**Interfaces:** Preserve `VERIFY_OFFLINE_CACHE` / `OFFLINE_CACHE_STATUS`; required assets must include the crypto bundle from Task 3.

- [ ] Add failing tests for a cache put failure during upgrade preserving old bytes and a successful upgrade with existing clients.
- [ ] Use an immutable release-specific cache, clean failed staging, avoid taking over existing tabs with incompatible assets. Do not mutate versioned code/config cache entries independently.
- [ ] Test initial offline cold reopen, failed install, successful replacement and retry; expect complete old or complete new assets only.

## Task 3: Replace handwritten browser cryptography

**Files:** `acoustic_stream.js`, new local vendor crypto bundle and provenance/license/build files, `tests/test_browser_bulletin_verification_phase_d.py`. Root integrator adds bundle script before stream and includes it in cache/packaging.
**Interfaces:** Preserve synchronous `verifyBulletinEnvelope`, `sha3_256Hex`, existing canonical envelope and decision shape. Maintained verifier must be the actual admission implementation.

- [ ] Check primary upstream documentation and pin an appropriate maintained implementation and reproducible bundling version.
- [ ] Add/extend behavioral vectors covering invalid encodings, tampering, trust tiers, reload, and offline use; observe regression before replacing handwritten primitives.
- [ ] Remove handwritten Ed25519/SHA implementations in favor of locally bundled maintained code, retain canonicalization and admission policy.
- [ ] Run Phase D and existing bulletin signature tests; expect Python/browser parity for valid canonical vectors and rejection of invalid signatures.

## Task 4: Integrate, document, verify, publish

**Files:** deployment documentation, code graph generator/snapshot, plan progress, any asset packaging declarations.
**Interfaces:** Tasks 2/3 agree on exact cached bundle path; HTML script order is vendor then stream. Graph remains Python-only and must say its browser commentary is descriptive, not validation.

- [ ] Run targeted browser/deployment suite and project test command; report any environmental/baseline failures explicitly.
- [ ] Update supported-versus-tested target claims and provide a physical trial procedure with hardware results explicitly pending.
- [ ] Regenerate snapshot, verify clean diff and packaging, obtain independent review, address material findings with regression tests.
- [ ] Commit, push `codex/receiver-reliability`, create and attach a PR with detailed explanation and validation results; do not merge.
