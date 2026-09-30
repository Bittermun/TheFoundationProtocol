# TFP Browser Acoustic Receiver UI & DSP Rules (`tfp_demo/static/`)

When modifying files in `tfp-foundation-protocol/tfp_demo/static/` (`acoustic_receiver.html`, `acoustic_stream.js`, `acoustic_worklet.js`, `acoustic_sw.js`), enforce these architectural and UI invariants:

1. **Zero-Install Offline-First Field Receiver**:
   - Must operate on low-end smartphones with zero external npm build step (pure self-contained HTML/CSS/JS + Web Audio API + Web Crypto API + Service Worker).
   - If you add or rename static assets, update the pre-cache asset list in `acoustic_sw.js` so offline cold-reopen continues to pass.

2. **AudioWorklet & DSP Pipeline (`Phase E` Invariants)**:
   - Keep demodulation and frame extraction inside `acoustic_worklet.js` off the main UI thread.
   - Preserve pre-allocated TypedArray buffer reuse (no per-quantum GC churn in `process()`), bounded ring/message queues, and stall/drop telemetry counters.

3. **Cryptographic Bulletin Trust Isolation (`Phase D` Invariants)**:
   - Bulletins decoded over acoustic streams must be verified via Ed25519 signatures before being rendered as trusted protocol bulletins. Unverified frames must be visibly quarantined.

4. **Field-Instrument Visual Tokens (`acoustic_receiver.html`)**:
   - Preserve high-contrast dark field-instrument CSS variables (`--bg: #090d16`, `--card: #131d2e`, `--border: #1e293b`, `--accent: #00e5ff`, `--text: #f1f5f9`, `--muted: #94a3b8`, `--success: #10b981`, `--warning: #f59e0b`, `--danger: #ef4444`).

5. **Mandatory Receiver Acceptance Tests**:
   Run all four browser receiver test suites after any edit in this directory:
   ```powershell
   .\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_browser_acoustic_acceptance.py tests/test_receiver_readiness_lifecycle.py tests/test_browser_bulletin_verification_phase_d.py tests/test_audio_worklet_contention_phase_e.py -q
   ```
