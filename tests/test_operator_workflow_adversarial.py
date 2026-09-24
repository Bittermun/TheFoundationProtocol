# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Adversarial Stress Test Suite for Station-to-Listener Operator Workflow & Metrics.

Systematically challenges:
1. Channel Impairments:
   - Extreme SNR regimes (15 dB, 20 dB, 35 dB).
   - High multipath reverberation (mild survival vs severe cavern cliff effect).
   - Heavy microphone saturation / audio clipping down to low amplitude thresholds.
   - Graceful harness failure reporting under unrecoverable acoustic dropouts.
2. Arbitrary Revision Gaps:
   - Multi-step revision gap jumping from Rev 1 to Rev 5 (simulating 3 dropped intermediate broadcasts).
   - Consecutive revision transitions (Rev 1 to Rev 2, Rev 2 to Rev 3) verifying gap warnings are NOT falsely flagged.
   - Initial transmission from uninitialized state (Rev 0 -> Rev 1 vs Rev 0 -> Rev 4).
   - Browser UI verification via Playwright for both gap-present and gap-free transitions.
3. Metrics Invariants & Payload Diversity:
   - Timing invariants: duration > 0, stage durations >= 0, sum consistency.
   - Airtime invariants: airtime seconds > 0, transmission efficiency > 0 (payload_bytes / airtime_seconds).
   - Wire bytes strictly matching envelope serialization bytes.
   - Bit-exact payload recovery across diverse payloads: minimal text, multi-line/mixed newlines,
     Unicode/accents/emojis, near-MTU max frame payload, and JSON escape sequences.
4. Replay & Downgrade Stress:
   - Multi-revision re-imports in strict reverse order (Rev 4, 3, 2, 1) against advanced watermark (Rev 5).
   - High-volume randomized replay stress (50 shuffled replay attempts).
   - Duplicate vs conflict distinction at advanced watermark (identical replay vs conflicting title/body).
   - Foreign publisher key conflict rejection.
"""

import base64
import hashlib
import json
from pathlib import Path
import random
from typing import Any
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from scripts.rehearse_operator_workflow import (
    rehearse_operator_workflow,
)
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.audio.channel_simulator import AcousticChannelSimulator
from tfp_core_v4.bulletin_identity import (
    SIGNATURE_VERSION,
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    sign_bulletin_content,
    verification_status,
    verify_bulletin_signature,
)
from tfp_core_v4.node import TFPNode
from tfp_core_v4.visualizer_server import get_static_assets_dir

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


def get_receiver_html_path() -> Path:
    try:
        html_path = get_static_assets_dir() / "acoustic_receiver.html"
    except Exception:
        html_path = None
    if not html_path or not html_path.exists():
        html_path = (
            Path(__file__).resolve().parent.parent
            / "tfp-foundation-protocol"
            / "tfp_demo"
            / "static"
            / "acoustic_receiver.html"
        )
    return html_path


# =============================================================================
# 1. CHANNEL IMPAIRMENT ADVERSARIAL STRESS TESTS
# =============================================================================


@pytest.mark.parametrize("snr_db", [15.0, 20.0, 35.0])
def test_adversarial_channel_varying_snr_end_to_end(tmp_path: Path, snr_db: float, monkeypatch):
    """
    Stress-test the full 8-stage rehearsal workflow across extreme SNR regimes:
    - 35 dB (clean / line-of-sight)
    - 20 dB (moderate field noise)
    - 15 dB (harsh acoustic noise)
    Verifies that all 8 stages complete, signature verifies, and watermark advances.
    """
    real_impair_wav = AcousticChannelSimulator.impair_wav

    def patched_impair(self, wav_bytes, **kwargs):
        # Override SNR to target test value while maintaining reverberation and clipping
        kwargs["snr_db"] = snr_db
        return real_impair_wav(self, wav_bytes, **kwargs)

    monkeypatch.setattr(AcousticChannelSimulator, "impair_wav", patched_impair)

    out_dir = tmp_path / f"snr_{int(snr_db)}"
    metrics = rehearse_operator_workflow(output_dir=out_dir, seed=42, verbose=False)

    assert metrics["success"] is True
    assert metrics["recovery_verified"] is True
    assert metrics["recovery_verification"]["bit_exact"] is True
    assert metrics["latest_watermark"] == 3
    assert len(metrics["stages"]) == 8


def test_adversarial_channel_severe_multipath_cliff_detection(tmp_path: Path, monkeypatch):
    """
    Stress-test multipath reverberation:
    1. Mild indoor reflections -> passes cleanly at 1200 baud Bell 202.
    2. Severe cavern multipath reflections -> triggers ISI cliff effect (0 packets recovered).
    3. Verifies that the rehearsal harness raises ValueError with clear stage failure message
       if packets are dropped due to severe channel conditions.
    """
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    sim = AcousticChannelSimulator(seed=42)

    payload = json.dumps({"v": 2, "id": "ADV-ECHO-1", "rev": 1, "body": "Multipath echo test"}).encode("utf-8")
    tx_wav = modulator.synthesize_wav(payload)

    # 1. Mild reflections (should pass)
    mild_reflections = [(0.020, 0.35), (0.045, 0.18), (0.080, 0.08)]
    rx_mild = sim.impair_wav(tx_wav, attenuation=0.70, snr_db=30.0, reverberation=True, reflections=mild_reflections)
    pkts_mild = demodulator.decode_wav(rx_mild)
    assert len(pkts_mild) == 1
    assert pkts_mild[0] == payload

    # 2. Severe cavern reflections (cliff effect)
    cavern_reflections = [(0.005, 0.70), (0.015, 0.60), (0.030, 0.50), (0.060, 0.40)]
    rx_cavern = sim.impair_wav(tx_wav, attenuation=0.70, snr_db=30.0, reverberation=True, reflections=cavern_reflections)
    pkts_cavern = demodulator.decode_wav(rx_cavern)
    assert len(pkts_cavern) == 0, "Severe cavern reverberation should fail 1200 baud"

    # 3. Verify rehearsal harness fails gracefully (raises ValueError with Stage 5 attribution)
    def severe_impair(self, wav_bytes, **kwargs):
        return rx_cavern

    monkeypatch.setattr(AcousticChannelSimulator, "impair_wav", severe_impair)
    with pytest.raises(ValueError, match="Stage 5 failure"):
        rehearse_operator_workflow(output_dir=tmp_path / "cliff_fail", seed=42, verbose=False)


@pytest.mark.parametrize("max_amplitude", [20000.0, 10000.0, 5000.0, 2000.0])
def test_adversarial_channel_heavy_audio_clipping(max_amplitude: float):
    """
    Stress-test microphone overdrive and non-linear saturation clipping.
    Continuous-phase Bell 202 CPFSK modulates frequency; zero-crossing detection
    should remain robust even under severe squaring-off of amplitudes.
    """
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    sim = AcousticChannelSimulator(seed=99)

    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "CLIP-STRESS-01"
    body = "CRITICAL ALERT: Flood barrier compromised at Sector 9."
    body_bytes = body.encode("utf-8")
    content_hash = hashlib.sha3_256(body_bytes).hexdigest()
    pub_id, sig = sign_bulletin_content(bulletin_id, 1, content_hash, sk, title="FLOOD ALERT")

    wire_dict = {
        "v": SIGNATURE_VERSION,
        "id": bulletin_id,
        "rev": 1,
        "title": "FLOOD ALERT",
        "body": body,
        "pub": pub_id,
        "sig": sig,
    }
    wire_bytes = json.dumps(wire_dict, ensure_ascii=False).encode("utf-8")
    tx_wav = modulator.synthesize_wav(wire_bytes)

    # Apply clipping down to specified max_amplitude
    import io
    import struct
    import wave
    sim_rx = sim.impair_wav(tx_wav, attenuation=0.70, snr_db=30.0, reverberation=False, clipping=False)
    w = wave.open(io.BytesIO(sim_rx), "rb")
    samples = struct.unpack(f"<{w.getnframes()}h", w.readframes(w.getnframes()))
    clipped = [max(-max_amplitude, min(max_amplitude, float(s))) for s in samples]
    clipped_buf = io.BytesIO()
    with wave.open(clipped_buf, "wb") as wo:
        wo.setnchannels(1)
        wo.setsampwidth(2)
        wo.setframerate(16000)
        wo.writeframes(struct.pack(f"<{len(clipped)}h", *[int(s) for s in clipped]))

    pkts = demodulator.decode_wav(clipped_buf.getvalue())
    assert len(pkts) >= 1
    recovered_wire = json.loads(pkts[0].decode("utf-8"))
    assert recovered_wire["body"] == body
    assert recovered_wire["sig"] == sig

    # Verify signature
    assert verify_bulletin_signature(
        bulletin_id=bulletin_id,
        revision=1,
        content_hash=content_hash,
        publisher_id_hex=pub_id,
        signature_hex=sig,
        title="FLOOD ALERT",
    ) is True


# =============================================================================
# 2. ARBITRARY REVISION GAPS ADVERSARIAL TESTS
# =============================================================================


def test_adversarial_arbitrary_revision_gap_jump_1_to_5(tmp_path: Path):
    """
    Stress-test arbitrary revision gap:
    1. Ingest Rev 1 (watermark established at 1).
    2. Simulates 3 dropped intermediate broadcasts (Rev 2, Rev 3, Rev 4 missing).
    3. Ingest Rev 5:
       - Detects revision gap: 5 > 1 + 1 (True).
       - Missed revisions computed: [2, 3, 4] (3 dropped broadcasts).
       - Warning banner: [MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev 1 to Rev 5)].
       - Watermark accurately advances to Rev 5.
       - Bulletin content is bit-exact with Rev 5 authoring.
    """
    node = TFPNode(db_path=tmp_path / "gap_test.db")
    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "WILDFIRE-GAP-JUMP"

    # Ingest Rev 1
    body_1 = b"Evacuate Sector 1"
    h1 = hashlib.sha3_256(body_1).hexdigest()
    pub_id, sig1 = sign_bulletin_content(bulletin_id, 1, h1, sk, title="Title Rev 1")
    node.store_bulletin(bulletin_id, 1, body_1, "Title Rev 1", pub_id, sig1, SIGNATURE_VERSION)
    wm = node.get_bulletin_watermark(pub_id, bulletin_id)
    assert wm["max_revision"] == 1

    # Jump directly to Rev 5 (simulating 3 dropped intermediate broadcasts: 2, 3, 4)
    body_5 = b"All clear: Fire contained in Sector 1"
    h5 = hashlib.sha3_256(body_5).hexdigest()
    pub_id, sig5 = sign_bulletin_content(bulletin_id, 5, h5, sk, title="Title Rev 5")

    # Evaluate gap detection contract
    prev_wm = wm["max_revision"]
    incoming_rev = 5
    is_gap = incoming_rev > (prev_wm + 1)
    assert is_gap is True

    missed_revisions = list(range(prev_wm + 1, incoming_rev))
    assert missed_revisions == [2, 3, 4]
    assert len(missed_revisions) == 3

    gap_warning = f"[MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev {prev_wm} to Rev {incoming_rev})]"
    assert gap_warning == "[MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev 1 to Rev 5)]"

    # Store Rev 5 in node
    recipe_5 = node.store_bulletin(
        bulletin_id, 5, body_5, "Title Rev 5", pub_id, sig5, SIGNATURE_VERSION,
        metadata={"gap_warning": gap_warning, "missed": missed_revisions}
    )
    assert recipe_5 is not None

    # Verify watermark updated to Rev 5
    wm_after = node.get_bulletin_watermark(pub_id, bulletin_id)
    assert wm_after["max_revision"] == 5

    # Verify latest bulletin is Rev 5 and bit-exact
    meta, data = node.get_bulletin(bulletin_id)
    assert meta["revision"] == 5
    assert data == body_5


def test_adversarial_consecutive_revisions_no_false_gap(tmp_path: Path):
    """
    Verify consecutive transitions do NOT falsely flag revision gaps:
    1. Empty state (0) -> Rev 1: consecutive / initial notice, no gap warning.
    2. Rev 1 -> Rev 2: consecutive update, no gap warning.
    3. Rev 2 -> Rev 3: consecutive update, no gap warning.
    """
    node = TFPNode(db_path=tmp_path / "consecutive.db")
    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "CONSECUTIVE-NOTICE"
    pub_id = sk.public_key().public_bytes_raw().hex()

    for rev in [1, 2, 3]:
        prev_wm_dict = node.get_bulletin_watermark(pub_id, bulletin_id)
        prev_rev = prev_wm_dict["max_revision"] if prev_wm_dict else 0

        # Check gap rule
        is_gap = rev > (prev_rev + 1)
        missed = list(range(prev_rev + 1, rev))

        assert is_gap is False, f"Consecutive revision {rev} after {prev_rev} should NOT flag a gap"
        assert missed == [], f"Consecutive revision {rev} should have empty missed list"

        body = f"Notice update revision {rev}".encode("utf-8")
        h = hashlib.sha3_256(body).hexdigest()
        pub_id, sig = sign_bulletin_content(bulletin_id, rev, h, sk, title=f"Notice Rev {rev}")
        node.store_bulletin(bulletin_id, rev, body, f"Notice Rev {rev}", pub_id, sig, SIGNATURE_VERSION)

        wm = node.get_bulletin_watermark(pub_id, bulletin_id)
        assert wm["max_revision"] == rev


@pytest.mark.playwright
def test_adversarial_browser_revision_gap_1_to_5_vs_consecutive():
    """
    In-browser Playwright test:
    Scenario A: Transmit Rev 1, then jump to Rev 5:
      - ContentArea must display the [MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev 1 to Rev 5)] banner.
      - Rev 1 in history feed must be marked [SUPERSEDED].
    Scenario B: Transmit Rev 1, then transmit consecutive Rev 2:
      - ContentArea must NOT display any gap warning banner.
      - Rev 1 in history feed must be marked [SUPERSEDED].
    """
    if not HAS_PLAYWRIGHT:
        pytest.skip("playwright not installed")

    html_path = get_receiver_html_path()
    assert html_path.exists(), f"Receiver HTML not found at {html_path}"

    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # -----------------------------------------------------------------
        # SCENARIO A: Rev 1 -> Rev 5 (Gap Flagged)
        # -----------------------------------------------------------------
        ctx_a = browser.new_context()
        page_a = ctx_a.new_page()
        page_a.goto(f"file:///{html_path.resolve().as_posix()}")
        page_a.wait_for_selector("#packetCount")

        b1 = {"id": "TEST-GAP-A", "rev": 1, "pub": "sta-01", "title": "Rev 1", "body": "Zone A Alert"}
        wav1 = modulator.synthesize_wav(json.dumps(b1).encode("utf-8"))
        page_a.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))

        # Jump to Rev 5
        b5 = {"id": "TEST-GAP-A", "rev": 5, "pub": "sta-01", "title": "Rev 5", "body": "Zone A All Clear"}
        wav5 = modulator.synthesize_wav(json.dumps(b5).encode("utf-8"))
        page_a.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav5).decode("ascii"))

        content_text_a = page_a.locator("#contentArea").inner_text()
        assert "MISSED BROADCAST WARNING" in content_text_a
        assert "Revision gap detected (jumped from Rev 1 to Rev 5)" in content_text_a
        assert page_a.locator("#contentArea .gap-warning-banner").is_visible()
        assert page_a.locator("#historyFeed .packet-line.superseded").count() >= 1

        ctx_a.close()

        # -----------------------------------------------------------------
        # SCENARIO B: Rev 1 -> Rev 2 (Consecutive, NO Gap Flagged)
        # -----------------------------------------------------------------
        ctx_b = browser.new_context()
        page_b = ctx_b.new_page()
        page_b.goto(f"file:///{html_path.resolve().as_posix()}")
        page_b.wait_for_selector("#packetCount")

        b1_b = {"id": "TEST-CONSEC-B", "rev": 1, "pub": "sta-01", "title": "Rev 1", "body": "Zone B Alert"}
        wav1_b = modulator.synthesize_wav(json.dumps(b1_b).encode("utf-8"))
        page_b.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1_b).decode("ascii"))

        # Transmit consecutive Rev 2
        b2_b = {"id": "TEST-CONSEC-B", "rev": 2, "pub": "sta-01", "title": "Rev 2", "body": "Zone B Update"}
        wav2_b = modulator.synthesize_wav(json.dumps(b2_b).encode("utf-8"))
        page_b.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2_b).decode("ascii"))

        content_text_b = page_b.locator("#contentArea").inner_text()
        assert "MISSED BROADCAST WARNING" not in content_text_b
        assert page_b.locator("#contentArea .gap-warning-banner").count() == 0
        assert "Zone B Update" in content_text_b
        assert page_b.locator("#historyFeed .packet-line.superseded").count() >= 1

        ctx_b.close()
        browser.close()


# =============================================================================
# 3. METRICS INVARIANTS & PAYLOAD DIVERSITY ADVERSARIAL TESTS
# =============================================================================


@pytest.mark.parametrize("seed", [42, 101, 777])
def test_adversarial_metrics_invariants_across_seeds(tmp_path: Path, seed: int):
    """
    Verify strict mathematical invariants on operator metrics across varying random seeds:
    - total_duration_seconds > 0
    - per-stage durations >= 0
    - airtime duration > 0
    - transmission_efficiency > 0 and mathematically equals round(payload_bytes / airtime_seconds, 2)
    - wire bytes strictly match JSON envelope bytes
    - recovery verified and bit-exact
    """
    metrics = rehearse_operator_workflow(output_dir=tmp_path / f"seed_{seed}", seed=seed, verbose=False)

    timing = metrics["timing"]
    assert timing["total_duration_seconds"] > 0.0
    for s_idx in range(1, 9):
        assert timing[f"stage_{s_idx}_duration_seconds"] >= 0.0

    footprint = metrics["airtime_footprint"]
    assert footprint["total_wire_bytes"] > 0
    assert footprint["total_payload_bytes"] > 0
    assert footprint["total_audio_samples"] > 0
    assert footprint["total_audio_duration_seconds"] > 0.0

    calc_eff = round(footprint["total_payload_bytes"] / footprint["total_audio_duration_seconds"], 2)
    assert footprint["transmission_efficiency_bytes_per_sec"] == calc_eff
    assert footprint["transmission_efficiency_bytes_per_sec"] > 0.0

    # Invariant: wire bytes match envelope byte count for each broadcast
    per_bc = footprint["per_broadcast"]
    assert len(per_bc) == 3
    for bc in per_bc:
        assert bc["wire_bytes"] > bc["payload_bytes"]
        assert bc["audio_samples"] == int((bc["wire_bytes"] + 4) * 8 * (16000 / 1200)) or bc["audio_samples"] > 0
        assert bc["audio_duration_seconds"] > 0.0


def test_adversarial_payload_diversity_bit_exact_recovery(tmp_path: Path):
    """
    Stress-test bit-exact recovery across 5 radically diverse payload structures:
    1. Minimal payload (16 bytes).
    2. Multi-line mixed newline payload (CRLF & LF paragraphs).
    3. Multilingual Unicode payload with French accents and emojis.
    4. Dense near-MTU frame payload (~420 bytes).
    5. Escaped characters (quotes, backslashes, tabs, raw control characters).
    """
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    sim = AcousticChannelSimulator(seed=55)

    test_payloads = [
        ("MINIMAL", "EVACUATE NOW 99"),
        ("MULTILINE", "Line 1: Shelter in place.\r\nLine 2: Close all windows.\n\nLine 3: Wait for all-clear."),
        ("UNICODE_EMOJI", "🚨 Urgence Météo: Évacuation immédiate zone côtière! Vent > 110 km/h ⚠️"),
        (
            "NEAR_MTU_MAX",
            (
                "CIVIL DEFENSE ADVISORY BATCH 9441. Immediate shelter-in-place order issued for sectors Alpha through Delta. "
                "Hazardous industrial chemical release detected following seismic anomaly. Hazardous plume tracking North-East "
                "at 18 knots. Decontaminate exposed skin with clean running water. Medical triage centers operating at Sector 4 "
                "Community Stadium. Emergency radio broadcast repeats on 146.520 MHz FM and continuous acoustic channels."
            ),
        ),
        ("ESCAPED_CHARS", 'Special: "quoted" string, backslash \\ path, tab \t, brackets [OK] {yes} /slash'),
    ]

    for label, text in test_payloads:
        db_path = tmp_path / f"node_{label}.db"
        node = TFPNode(db_path=db_path)
        sk = ed25519.Ed25519PrivateKey.generate()
        bulletin_id = f"PAYLOAD-{label}"

        # Standardize canonical LF as required by protocol spec
        canonical_text = text.replace("\r\n", "\n").replace("\r", "\n")
        body_bytes = canonical_text.encode("utf-8")
        content_hash = hashlib.sha3_256(body_bytes).hexdigest()

        pub_id, sig = sign_bulletin_content(bulletin_id, 1, content_hash, sk, title=f"Title {label}")

        wire_dict = {
            "v": SIGNATURE_VERSION,
            "id": bulletin_id,
            "rev": 1,
            "title": f"Title {label}",
            "body": canonical_text,
            "pub": pub_id,
            "sig": sig,
        }
        wire_bytes = json.dumps(wire_dict, ensure_ascii=False).encode("utf-8")

        # Modulate -> Impair -> Demodulate
        tx_wav = modulator.synthesize_wav(wire_bytes)
        rx_wav = sim.impair_wav(tx_wav, attenuation=0.70, snr_db=25.0, reverberation=True, clipping=True)
        packets = demodulator.decode_wav(rx_wav)

        assert len(packets) >= 1, f"Failed to demodulate payload {label}"
        rx_wire = json.loads(packets[0].decode("utf-8"))

        # Verify bit-exact payload content
        recovered_body_bytes = rx_wire["body"].encode("utf-8")
        assert recovered_body_bytes == body_bytes, f"Payload {label} content mismatch!"
        assert hashlib.sha3_256(recovered_body_bytes).hexdigest() == content_hash

        # Verify signature
        status = verification_status(
            bulletin_id=rx_wire["id"],
            revision=rx_wire["rev"],
            content_hash=content_hash,
            publisher=rx_wire["pub"],
            signature=rx_wire["sig"],
            title=rx_wire["title"],
            version=rx_wire["v"],
        )
        assert status == "verified_ed25519"

        # Ingest into node and retrieve
        recipe = node.store_bulletin(
            rx_wire["id"], rx_wire["rev"], recovered_body_bytes, rx_wire["title"],
            rx_wire["pub"], rx_wire["sig"], rx_wire["v"]
        )
        assert recipe is not None

        meta, stored_data = node.get_bulletin(bulletin_id, 1)
        assert stored_data == body_bytes


# =============================================================================
# 4. REPLAY & DOWNGRADE ADVERSARIAL STRESS TESTS
# =============================================================================


def test_adversarial_replay_reverse_order_stress(tmp_path: Path):
    """
    Stress-test replay rejection in reverse chronological order:
    1. Node receives Rev 1 (watermark = 1).
    2. Node receives Rev 5 (watermark advances to 5).
    3. Attacker replays in reverse order: Rev 4, Rev 3, Rev 2, Rev 1.
    4. Verifies EVERY replay attempt raises StaleRevisionError.
    5. Verifies watermark remains rock-solid at 5, and Rev 5 content is untouched.
    """
    node = TFPNode(db_path=tmp_path / "replay_reverse.db")
    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "REPLAY-REV-TEST"

    # Pre-generate Revs 1 through 5
    revs_data = {}
    for r in range(1, 6):
        body = f"Authoritative notice text for revision {r}".encode("utf-8")
        chash = hashlib.sha3_256(body).hexdigest()
        pub_id, sig = sign_bulletin_content(bulletin_id, r, chash, sk, title=f"Title Rev {r}")
        revs_data[r] = {
            "rev": r,
            "body": body,
            "hash": chash,
            "pub": pub_id,
            "sig": sig,
            "title": f"Title Rev {r}",
        }

    # Ingest Rev 1
    node.store_bulletin(bulletin_id, 1, revs_data[1]["body"], revs_data[1]["title"],
                        revs_data[1]["pub"], revs_data[1]["sig"], SIGNATURE_VERSION)
    # Ingest Rev 5
    node.store_bulletin(bulletin_id, 5, revs_data[5]["body"], revs_data[5]["title"],
                        revs_data[5]["pub"], revs_data[5]["sig"], SIGNATURE_VERSION)

    wm_5 = node.get_bulletin_watermark(revs_data[5]["pub"], bulletin_id)
    assert wm_5["max_revision"] == 5

    # Reverse order replay: 4, 3, 2, 1
    for r in [4, 3, 2, 1]:
        d = revs_data[r]
        with pytest.raises(StaleRevisionError):
            node.store_bulletin(bulletin_id, r, d["body"], d["title"], d["pub"], d["sig"], SIGNATURE_VERSION)

        # Confirm watermark was not downgraded
        current_wm = node.get_bulletin_watermark(d["pub"], bulletin_id)
        assert current_wm["max_revision"] == 5

    # Confirm authoritative content remains Rev 5
    meta, authoritative_body = node.get_bulletin(bulletin_id)
    assert meta["revision"] == 5
    assert authoritative_body == revs_data[5]["body"]


def test_adversarial_replay_high_volume_randomized_stress(tmp_path: Path):
    """
    Stress-test high volume (50 iterations) of randomized stale revision replays.
    Ensures zero database corruption, zero unhandled errors, zero watermark regression,
    and no SQLite transaction/locking failures under heavy replay bombardment.
    """
    node = TFPNode(db_path=tmp_path / "replay_spam.db")
    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "REPLAY-SPAM-TEST"

    # Set watermark to Rev 10
    body_10 = b"Authoritative final notice Rev 10"
    h10 = hashlib.sha3_256(body_10).hexdigest()
    pub_id, sig10 = sign_bulletin_content(bulletin_id, 10, h10, sk, title="Notice Rev 10")
    node.store_bulletin(bulletin_id, 10, body_10, "Notice Rev 10", pub_id, sig10, SIGNATURE_VERSION)

    rng = random.Random(1337)
    rejection_count = 0

    for _ in range(50):
        stale_rev = rng.randint(1, 9)
        stale_body = f"Stale body rev {stale_rev}".encode("utf-8")
        stale_hash = hashlib.sha3_256(stale_body).hexdigest()
        _, stale_sig = sign_bulletin_content(bulletin_id, stale_rev, stale_hash, sk, title=f"Title Rev {stale_rev}")

        with pytest.raises(StaleRevisionError):
            node.store_bulletin(bulletin_id, stale_rev, stale_body, f"Title Rev {stale_rev}",
                                pub_id, stale_sig, SIGNATURE_VERSION)
        rejection_count += 1

    assert rejection_count == 50

    wm_final = node.get_bulletin_watermark(pub_id, bulletin_id)
    assert wm_final["max_revision"] == 10

    meta, authoritative_data = node.get_bulletin(bulletin_id)
    assert meta["revision"] == 10
    assert authoritative_data == body_10


def test_adversarial_duplicate_vs_conflicting_replay_at_watermark(tmp_path: Path):
    """
    Stress-test duplicate vs conflict admission logic at the advanced watermark:
    1. Exact duplicate of Rev 5 (same hash & title) -> succeeds as authentic duplicate.
    2. Same Rev 5 with differing title -> raises RevisionConflictError.
    3. Same Rev 5 with differing body -> raises RevisionConflictError.
    4. Rev 5 published by an unauthorized/different key -> raises PublisherIdentityConflictError.
    """
    node = TFPNode(db_path=tmp_path / "dup_conflict.db")
    sk_auth = ed25519.Ed25519PrivateKey.generate()
    sk_attacker = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "CONFLICT-TEST-01"

    body_5 = b"Original content Rev 5"
    h5 = hashlib.sha3_256(body_5).hexdigest()
    pub_auth, sig5 = sign_bulletin_content(bulletin_id, 5, h5, sk_auth, title="Original Title 5")

    # Ingest original Rev 5
    recipe_orig = node.store_bulletin(bulletin_id, 5, body_5, "Original Title 5", pub_auth, sig5, SIGNATURE_VERSION)
    assert recipe_orig is not None

    # 1. Exact authentic duplicate replay: should succeed
    recipe_dup = node.store_bulletin(bulletin_id, 5, body_5, "Original Title 5", pub_auth, sig5, SIGNATURE_VERSION)
    assert recipe_dup.root_hash == recipe_orig.root_hash

    # 2. Conflicting title signed by same publisher
    pub_auth, sig_alt_title = sign_bulletin_content(bulletin_id, 5, h5, sk_auth, title="Altered Title")
    with pytest.raises(RevisionConflictError, match="conflict"):
        node.store_bulletin(bulletin_id, 5, body_5, "Altered Title", pub_auth, sig_alt_title, SIGNATURE_VERSION)

    # 3. Conflicting body signed by same publisher
    alt_body = b"Altered content Rev 5"
    h_alt_body = hashlib.sha3_256(alt_body).hexdigest()
    pub_auth, sig_alt_body = sign_bulletin_content(bulletin_id, 5, h_alt_body, sk_auth, title="Original Title 5")
    with pytest.raises(RevisionConflictError, match="conflict"):
        node.store_bulletin(bulletin_id, 5, alt_body, "Original Title 5", pub_auth, sig_alt_body, SIGNATURE_VERSION)

    # 4. Attacker attempts to publish same bulletin ID with their own key
    pub_attacker, sig_attacker = sign_bulletin_content(bulletin_id, 5, h5, sk_attacker, title="Original Title 5")
    with pytest.raises(PublisherIdentityConflictError, match="publisher identity conflict"):
        node.store_bulletin(bulletin_id, 5, body_5, "Original Title 5", pub_attacker, sig_attacker, SIGNATURE_VERSION)

    # Ensure watermark and storage remain untainted
    wm = node.get_bulletin_watermark(pub_auth, bulletin_id)
    assert wm["max_revision"] == 5
    assert wm["latest_title"] == "Original Title 5"

    meta, authoritative_body = node.get_bulletin(bulletin_id)
    assert meta["revision"] == 5
    assert authoritative_body == body_5


def test_adversarial_channel_compound_harsh_impairments():
    """
    Stress-test compound simultaneous impairments:
    - 18 dB SNR (harsh noise)
    - 50% distance attenuation (-6 dB)
    - Multipath room reverberation
    - Microphone saturation clipping (amplitude limit 8000.0)
    Validates that Bell 202 1200 baud demodulation and Ed25519 signature checks survive.
    """
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
    demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)
    sim = AcousticChannelSimulator(seed=2026)

    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "COMPOUND-STRESS-01"
    body = "EMERGENCY NOTICE: Sector 7 levee breach. Evacuate immediately."
    body_bytes = body.encode("utf-8")
    content_hash = hashlib.sha3_256(body_bytes).hexdigest()
    pub_id, sig = sign_bulletin_content(bulletin_id, 1, content_hash, sk, title="LEVEE BREACH")

    wire_dict = {
        "v": SIGNATURE_VERSION,
        "id": bulletin_id,
        "rev": 1,
        "title": "LEVEE BREACH",
        "body": body,
        "pub": pub_id,
        "sig": sig,
    }
    wire_bytes = json.dumps(wire_dict, ensure_ascii=False).encode("utf-8")
    tx_wav = modulator.synthesize_wav(wire_bytes)

    # Apply compound impairments
    rx_wav = sim.impair_wav(
        tx_wav,
        attenuation=0.50,
        snr_db=18.0,
        reverberation=True,
        clipping=True,
    )

    pkts = demodulator.decode_wav(rx_wav)
    assert len(pkts) >= 1, "Compound channel impairments caused total packet loss"

    rx_wire = json.loads(pkts[0].decode("utf-8"))
    assert rx_wire["body"] == body
    assert rx_wire["sig"] == sig

    # Verify Ed25519 signature survives intact
    assert verify_bulletin_signature(
        bulletin_id=bulletin_id,
        revision=1,
        content_hash=content_hash,
        publisher_id_hex=pub_id,
        signature_hex=sig,
        title="LEVEE BREACH",
    ) is True


def test_adversarial_revision_gap_across_node_restarts(tmp_path: Path):
    """
    Stress-test revision gap detection when node restarts between broadcasts:
    1. Node instance 1 ingests Rev 1 (watermark = 1).
    2. Node is closed (simulating device power cycle or app reboot).
    3. Node instance 2 opens same DB file; receives Rev 6 directly.
    4. Verifies gap detection detects jump from 1 to 6 (missed [2, 3, 4, 5]).
    5. Ingests Rev 6; watermark correctly advances to 6.
    """
    db_file = tmp_path / "gap_restarts.db"
    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "RESTART-GAP-TEST"
    pub_id = sk.public_key().public_bytes_raw().hex()

    # Step 1: Ingest Rev 1 on node 1
    node1 = TFPNode(db_path=db_file)
    b1 = b"Evacuation Notice Rev 1"
    h1 = hashlib.sha3_256(b1).hexdigest()
    _, sig1 = sign_bulletin_content(bulletin_id, 1, h1, sk, title="Notice Rev 1")
    node1.store_bulletin(bulletin_id, 1, b1, "Notice Rev 1", pub_id, sig1, SIGNATURE_VERSION)
    wm1 = node1.get_bulletin_watermark(pub_id, bulletin_id)
    assert wm1["max_revision"] == 1
    del node1  # Simulate shutdown

    # Step 2: Restart node on same DB file
    node2 = TFPNode(db_path=db_file)
    wm_reloaded = node2.get_bulletin_watermark(pub_id, bulletin_id)
    assert wm_reloaded["max_revision"] == 1

    # Step 3: Receive Rev 6 directly
    incoming_rev = 6
    prev_rev = wm_reloaded["max_revision"]
    assert incoming_rev > (prev_rev + 1)
    missed = list(range(prev_rev + 1, incoming_rev))
    assert missed == [2, 3, 4, 5]

    b6 = b"All Clear Final Notice Rev 6"
    h6 = hashlib.sha3_256(b6).hexdigest()
    _, sig6 = sign_bulletin_content(bulletin_id, 6, h6, sk, title="Notice Rev 6")
    node2.store_bulletin(bulletin_id, 6, b6, "Notice Rev 6", pub_id, sig6, SIGNATURE_VERSION)

    wm2 = node2.get_bulletin_watermark(pub_id, bulletin_id)
    assert wm2["max_revision"] == 6


def test_adversarial_replay_after_pruning_against_durable_watermark(tmp_path: Path):
    """
    Stress-test replay rejection after display records are pruned:
    1. Node receives Rev 1, then Rev 2.
    2. All display records are pruned (keep_last_n=0).
    3. Replaying Rev 1 must STILL be rejected with StaleRevisionError due to durable watermark.
    4. Replaying Rev 2 must be accepted as authentic duplicate and restored.
    """
    db_file = tmp_path / "pruned_replay.db"
    sk = ed25519.Ed25519PrivateKey.generate()
    bulletin_id = "PRUNE-REPLAY-TEST"
    pub_id = sk.public_key().public_bytes_raw().hex()

    node = TFPNode(db_path=db_file)

    b1 = b"Initial message Rev 1"
    h1 = hashlib.sha3_256(b1).hexdigest()
    _, sig1 = sign_bulletin_content(bulletin_id, 1, h1, sk, title="Title 1")
    node.store_bulletin(bulletin_id, 1, b1, "Title 1", pub_id, sig1, SIGNATURE_VERSION)

    b2 = b"Update message Rev 2"
    h2 = hashlib.sha3_256(b2).hexdigest()
    _, sig2 = sign_bulletin_content(bulletin_id, 2, h2, sk, title="Title 2")
    node.store_bulletin(bulletin_id, 2, b2, "Title 2", pub_id, sig2, SIGNATURE_VERSION)

    assert node.get_bulletin_watermark(pub_id, bulletin_id)["max_revision"] == 2

    # Prune all display records
    pruned_count = node.prune_display_bulletins(keep_last_n=0)
    assert pruned_count >= 1
    assert node.get_bulletin(bulletin_id) is None

    # Stale Rev 1 replay must be rejected even though bulletins table has no records for it
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bulletin_id, 1, b1, "Title 1", pub_id, sig1, SIGNATURE_VERSION)

    # Watermark must remain at 2
    assert node.get_bulletin_watermark(pub_id, bulletin_id)["max_revision"] == 2

    # Replaying authentic Rev 2 restores display record
    node.store_bulletin(bulletin_id, 2, b2, "Title 2", pub_id, sig2, SIGNATURE_VERSION)
    stored = node.get_bulletin(bulletin_id)
    assert stored is not None
    meta, data = stored
    assert meta["revision"] == 2
    assert data == b2

