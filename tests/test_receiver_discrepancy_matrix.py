# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Cross-Platform Receiver Discrepancy Matrix Test Suite.

Executes identical synthesized acoustic AFSK payloads through both:
1. Python engine: AFSKDemodulator + TFPNode / bulletin admission
2. Headless Chromium engine: acoustic_receiver.html + window.decodeAcousticWav

Verifies strict 1:1 decision parity across all operational boundaries:
- Valid Initial Revision Admission
- Valid Sequential Revision Advancement
- Stale Revision Replay Defense (dual-store watermark preservation)
- Idempotent Duplicate Replay Handling
- Revision Conflict Rejection (same revision, mutated content)
- Publisher Identity Conflict Rejection (same bulletin ID, different publisher key)
- Malformed Fields Rejection (negative or non-integer revisions)
- Transport Audio Bit-Corruption (CRC16 detection)
- Unicode & CRLF Payload Normalization
- Decoupled Signature Trust: Python cryptographic validation vs. Browser explicit unverified warning
"""

import base64
import hashlib
import json
from pathlib import Path
import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_core_v4.bulletin_identity import (
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    sign_bulletin_content,
)
from tfp_core_v4.node import TFPNode

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


class MatrixEnvironment:
    """Manages synchronized Python TFPNode and Chromium Playwright contexts."""

    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.node = TFPNode(db_path=tmp_path / "matrix_node.db")
        self.modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)
        self.demodulator = AFSKDemodulator(sample_rate=16000, baud_rate=1200)

        html_path = (
            Path(__file__).resolve().parent.parent
            / "tfp-foundation-protocol"
            / "tfp_demo"
            / "static"
            / "acoustic_receiver.html"
        )
        assert html_path.exists(), f"Receiver HTML not found at {html_path}"
        self.html_uri = f"file:///{html_path.resolve().as_posix()}"

    def run_vector(self, page, wire_dict: dict | None, *, raw_bytes: bytes | None = None, corrupt_audio: bool = False):
        """
        Synthesizes audio for payload and feeds it to both Python and Browser demodulators.
        Returns:
            python_result: {
                "transport_ok": bool,
                "admitted": bool,
                "error_type": str | None,
                "bulletin": dict | None,
                "watermark_rev": int | None,
            }
            browser_result: {
                "transport_ok": bool,
                "admitted": bool,
                "rejection_log": str | None,
                "active_revision": int | None,
                "watermark_rev": int | None,
                "archive_count": int,
            }
        """
        # 1. Prepare raw payload
        if raw_bytes is not None:
            payload_data = raw_bytes
        elif wire_dict is not None:
            payload_data = json.dumps(wire_dict, ensure_ascii=False).encode("utf-8")
        else:
            raise ValueError("Must provide wire_dict or raw_bytes")

        # 2. Synthesize Bell 202 WAV audio
        wav_bytes = self.modulator.synthesize_wav(payload_data)
        if corrupt_audio:
            # Overwrite 4000 bytes (2000 samples = ~150 bits) in the payload section with silence to break CRC16
            corrupted = bytearray(wav_bytes)
            midpoint = len(corrupted) // 2
            corrupted[midpoint : midpoint + 4000] = b"\x00" * 4000
            wav_bytes = bytes(corrupted)

        # 3. Evaluate Python Pipeline
        python_res = {"transport_ok": False, "admitted": False, "error_type": None, "bulletin": None, "watermark_rev": None}
        decoded_packets = self.demodulator.decode_wav(wav_bytes)
        if decoded_packets:
            python_res["transport_ok"] = True
            pkt_bytes = decoded_packets[0]
            try:
                data = json.loads(pkt_bytes.decode("utf-8"))
                b_id = data.get("id")
                rev = data.get("rev")
                title = data.get("title", b_id or "")
                body = data.get("body", "")
                pub = data.get("pub") or "unsigned"
                sig = data.get("sig")
                v = data.get("v", 2)

                self.node.store_bulletin(
                    bulletin_id=b_id,
                    revision=rev,
                    data=body.encode("utf-8"),
                    title=title,
                    publisher_id=pub,
                    signature_hex=sig,
                    signature_version=v,
                )
                python_res["admitted"] = True
            except StaleRevisionError:
                python_res["error_type"] = "StaleRevisionError"
            except RevisionConflictError:
                python_res["error_type"] = "RevisionConflictError"
            except PublisherIdentityConflictError:
                python_res["error_type"] = "PublisherIdentityConflictError"
            except ValueError as e:
                err_msg = str(e).lower()
                if "conflict" in err_msg:
                    python_res["error_type"] = "RevisionConflictError"
                elif "stale" in err_msg:
                    python_res["error_type"] = "StaleRevisionError"
                elif "publisher" in err_msg:
                    python_res["error_type"] = "PublisherIdentityConflictError"
                else:
                    python_res["error_type"] = "ValueError"
            except Exception as e:
                python_res["error_type"] = type(e).__name__

            if wire_dict and "id" in wire_dict:
                stored = self.node.get_bulletin(wire_dict["id"])
                if stored:
                    python_res["bulletin"] = stored[0]
                wm = self.node.get_bulletin_watermark(wire_dict.get("pub") or "unsigned", wire_dict["id"])
                if wm:
                    python_res["watermark_rev"] = wm["max_revision"]

        # 4. Evaluate Headless Browser Pipeline
        browser_res = {"transport_ok": False, "admitted": False, "rejection_log": None, "active_revision": None, "watermark_rev": None, "archive_count": 0}
        b64_audio = base64.b64encode(wav_bytes).decode("ascii")

        # Snapshot archive count before
        archive_before = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        count_before = len(archive_before)

        res = page.evaluate("b64 => window.decodeAcousticWav(b64)", b64_audio)

        if res["count"] > 0:
            browser_res["transport_ok"] = True
            archive = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
            watermarks = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
            last_log = page.evaluate("""() => {
                const lines = document.querySelectorAll('#packetFeed .packet-line');
                return lines.length > 0 ? lines[lines.length - 1].innerText : '';
            }""")

            browser_res["archive_count"] = len(archive)
            target_id = wire_dict.get("id") if wire_dict else None
            pub_key = (wire_dict.get("pub") or "unsigned") if wire_dict else "unsigned"

            if target_id:
                wm_key = f"{pub_key}:{target_id}"
                if wm_key in watermarks:
                    browser_res["watermark_rev"] = watermarks[wm_key]["revision"]

                matching_archive = [item for item in archive if item.get("bulletinId") == target_id]
                if matching_archive:
                    browser_res["active_revision"] = matching_archive[0].get("revision")

            # Check rejection reasons in the latest log
            if "[REJECTED STALE]" in last_log:
                browser_res["rejection_log"] = "REJECTED_STALE"
            elif "Revision conflict" in last_log:
                browser_res["rejection_log"] = "REVISION_CONFLICT"
            elif "Publisher identity conflict" in last_log:
                browser_res["rejection_log"] = "PUBLISHER_CONFLICT"
            elif "Rejected malformed bulletin fields" in last_log:
                browser_res["rejection_log"] = "MALFORMED_FIELDS"

            # Check if admitted: archive count increased and matches revision
            if len(archive) > count_before and archive[0].get("bulletinId") == target_id:
                browser_res["admitted"] = True

        return python_res, browser_res


@pytest.fixture
def matrix_env(tmp_path: Path):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        env = MatrixEnvironment(tmp_path)
        page.goto(env.html_uri)
        page.wait_for_selector("#packetCount")
        yield env, page
        browser.close()


def test_discrepancy_matrix_valid_initial_admission(matrix_env):
    """Vector 1: Valid initial revision must be admitted identically in Python and Browser."""
    env, page = matrix_env
    v1 = {
        "v": 2,
        "id": "DISCREPANCY-ALPHA",
        "rev": 1,
        "pub": "unsigned",
        "title": "Flood Warning",
        "body": "River level rising at Sector 4.",
    }
    py_res, br_res = env.run_vector(page, v1)

    assert py_res["transport_ok"] is True
    assert br_res["transport_ok"] is True
    assert py_res["admitted"] is True
    assert br_res["admitted"] is True

    # Parity check: Both set revision and watermark to 1
    assert py_res["bulletin"]["revision"] == 1
    assert py_res["watermark_rev"] == 1
    assert br_res["active_revision"] == 1
    assert br_res["watermark_rev"] == 1
    assert br_res["archive_count"] == 1


def test_discrepancy_matrix_sequential_advancement(matrix_env):
    """Vector 2: Sequential revision advancement (rev 1 -> rev 2) admitted identically in both runtimes."""
    env, page = matrix_env
    v1 = {
        "v": 2,
        "id": "DISCREPANCY-SEQ",
        "rev": 1,
        "pub": "unsigned",
        "title": "Evacuation Notice Rev 1",
        "body": "Prepare emergency kits.",
    }
    v2 = {
        "v": 2,
        "id": "DISCREPANCY-SEQ",
        "rev": 2,
        "pub": "unsigned",
        "title": "Evacuation Notice Rev 2",
        "body": "Mandatory evacuation of Sector 4 initiated.",
    }
    # Ingest Rev 1
    env.run_vector(page, v1)

    # Ingest Rev 2
    py_res, br_res = env.run_vector(page, v2)
    assert py_res["admitted"] is True
    assert br_res["admitted"] is True

    # Parity check: Both advance active revision and watermark to 2
    assert py_res["bulletin"]["revision"] == 2
    assert py_res["watermark_rev"] == 2
    assert br_res["active_revision"] == 2
    assert br_res["watermark_rev"] == 2


def test_discrepancy_matrix_stale_revision_replay_defense(matrix_env):
    """Vector 3: Replaying older revision after watermark advanced is rejected identically in both runtimes."""
    env, page = matrix_env
    v1 = {
        "v": 2,
        "id": "DISCREPANCY-STALE",
        "rev": 1,
        "pub": "unsigned",
        "title": "Road Closed Rev 1",
        "body": "Bridge under repair.",
    }
    v2 = {
        "v": 2,
        "id": "DISCREPANCY-STALE",
        "rev": 2,
        "pub": "unsigned",
        "title": "Road Open Rev 2",
        "body": "Bridge repairs completed. Normal traffic.",
    }
    # Ingest newer Rev 2 first
    env.run_vector(page, v2)

    # Now attempt to ingest older Rev 1 (stale arrival)
    py_res, br_res = env.run_vector(page, v1)

    # Parity check: Both reject stale arrival
    assert py_res["admitted"] is False
    assert py_res["error_type"] == "StaleRevisionError"

    assert br_res["admitted"] is False
    assert br_res["rejection_log"] == "REJECTED_STALE"

    # Parity check: Neither rolled back or overwrote active Rev 2 content
    assert py_res["bulletin"]["revision"] == 2
    assert py_res["watermark_rev"] == 2
    assert br_res["active_revision"] == 2
    assert br_res["watermark_rev"] == 2


def test_discrepancy_matrix_duplicate_idempotence(matrix_env):
    """Vector 4: Exact duplicate arrival is handled idempotently without duplicate active entries."""
    env, page = matrix_env
    v = {
        "v": 2,
        "id": "DISCREPANCY-DUP",
        "rev": 1,
        "pub": "unsigned",
        "title": "Clinic Hours",
        "body": "Clinic open 08:00 - 16:00 daily.",
    }
    # First ingest
    env.run_vector(page, v)
    py_1_wm = env.node.get_bulletin_watermark("unsigned", "DISCREPANCY-DUP")["max_revision"]
    br_1_count = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]').length")

    # Duplicate ingest
    py_res, br_res = env.run_vector(page, v)

    # Parity check: Duplicate does not corrupt state or raise an error in Python
    assert py_res["admitted"] is True
    assert py_res["watermark_rev"] == py_1_wm

    # In browser, deduplication prevents duplicate archive entries
    br_2_count = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]').length")
    assert br_2_count == br_1_count
    assert br_res["watermark_rev"] == 1


def test_discrepancy_matrix_revision_conflict(matrix_env):
    """Vector 5: Same revision with conflicting mutated body is rejected identically in both runtimes."""
    env, page = matrix_env
    v_original = {
        "v": 2,
        "id": "DISCREPANCY-CONFLICT",
        "rev": 1,
        "pub": "unsigned",
        "title": "Shelter Info",
        "body": "Shelter open at School Gym.",
    }
    v_conflict = {
        "v": 2,
        "id": "DISCREPANCY-CONFLICT",
        "rev": 1,
        "pub": "unsigned",
        "title": "Shelter Info Mutated",
        "body": "Shelter relocated to Town Hall.",
    }
    # Ingest original
    env.run_vector(page, v_original)

    # Ingest conflicting revision 1
    py_res, br_res = env.run_vector(page, v_conflict)

    # Parity check: Both reject revision conflict
    assert py_res["admitted"] is False
    assert py_res["error_type"] == "RevisionConflictError"

    assert br_res["admitted"] is False
    assert br_res["rejection_log"] == "REVISION_CONFLICT"

    # Parity check: Original body remains intact in both stores
    assert env.node.get_bulletin("DISCREPANCY-CONFLICT")[1].decode("utf-8") == "Shelter open at School Gym."
    assert "Shelter open at School Gym." in page.locator("#contentArea").inner_text()


def test_discrepancy_matrix_publisher_identity_conflict(matrix_env):
    """Vector 6: Conflicting publisher attempting to publish under an existing bulletin ID is rejected."""
    env, page = matrix_env
    key_alpha = Ed25519PrivateKey.generate()
    key_bravo = Ed25519PrivateKey.generate()

    pub_alpha = key_alpha.public_key().public_bytes_raw().hex()
    pub_bravo = key_bravo.public_key().public_bytes_raw().hex()

    b_id = "DISCREPANCY-PUB-HIJACK"
    body_alpha = "Water is safe for consumption."
    h_alpha = hashlib.sha3_256(body_alpha.encode("utf-8")).hexdigest()
    _, sig_alpha = sign_bulletin_content(b_id, 1, h_alpha, key_alpha, title="Official Advisory")

    v_alpha = {
        "v": 2,
        "id": b_id,
        "rev": 1,
        "pub": pub_alpha,
        "sig": sig_alpha,
        "title": "Official Advisory",
        "body": body_alpha,
    }

    body_bravo = "Do not drink water."
    h_bravo = hashlib.sha3_256(body_bravo.encode("utf-8")).hexdigest()
    _, sig_bravo = sign_bulletin_content(b_id, 2, h_bravo, key_bravo, title="Compromised Advisory")

    v_bravo = {
        "v": 2,
        "id": b_id,
        "rev": 2,
        "pub": pub_bravo,
        "sig": sig_bravo,
        "title": "Compromised Advisory",
        "body": body_bravo,
    }
    # Ingest official publisher Alpha
    env.run_vector(page, v_alpha)

    # Ingest impostor publisher Bravo
    py_res, br_res = env.run_vector(page, v_bravo)

    # Parity check: Both reject publisher identity conflict
    assert py_res["admitted"] is False
    assert py_res["error_type"] == "PublisherIdentityConflictError"

    assert br_res["admitted"] is False
    assert br_res["rejection_log"] == "PUBLISHER_CONFLICT"

    # Parity check: Active content remains bound to publisher Alpha
    assert env.node.get_bulletin("DISCREPANCY-PUB-HIJACK")[0]["publisher_id"] == pub_alpha
    assert "Water is safe for consumption." in page.locator("#contentArea").inner_text()


@pytest.mark.parametrize("bad_rev", [-1, 0, "invalid_rev_string"])
def test_discrepancy_matrix_malformed_revision(matrix_env, bad_rev):
    """Vector 7 & 8: Malformed revisions (negative, zero, non-integer) are rejected identically in both runtimes."""
    env, page = matrix_env
    bad_wire = {
        "v": 2,
        "id": f"DISCREPANCY-MAL-{abs(hash(str(bad_rev)))}",
        "rev": bad_rev,
        "pub": "unsigned",
        "title": "Bad Revision",
        "body": "Test body",
    }
    py_res, br_res = env.run_vector(page, bad_wire)

    # Parity check: Both transport OK (JSON valid), but admission rejects malformed field
    assert py_res["transport_ok"] is True
    assert br_res["transport_ok"] is True
    assert py_res["admitted"] is False
    assert py_res["error_type"] == "ValueError"

    assert br_res["admitted"] is False
    assert br_res["rejection_log"] == "MALFORMED_FIELDS"


def test_discrepancy_matrix_transport_crc_corruption(matrix_env):
    """Vector 9: Transport-level bit corruption is rejected identically by CRC16 in both runtimes."""
    env, page = matrix_env
    wire = {
        "v": 2,
        "id": "DISCREPANCY-CORRUPT",
        "rev": 1,
        "pub": "unsigned",
        "title": "Corrupt Audio",
        "body": "Will not be recovered due to CRC error.",
    }
    py_res, br_res = env.run_vector(page, wire, corrupt_audio=True)

    # Parity check: Neither recovers packets from corrupted audio frames
    assert py_res["transport_ok"] is False
    assert br_res["transport_ok"] is False
    assert py_res["admitted"] is False
    assert br_res["admitted"] is False


def test_discrepancy_matrix_unicode_and_crlf_normalization(matrix_env):
    """Vector 10: Multilingual Unicode and CRLF line breaks preserve bit-exact fidelity in both runtimes."""
    env, page = matrix_env
    unicode_body = "Emergency Alert 🚨:\r\nLevel 3 warning in Sector B.\r\n• Hospitals: 99.8% capacity\r\n• Water: 💧 Available"
    wire = {
        "v": 2,
        "id": "DISCREPANCY-UNICODE",
        "rev": 1,
        "pub": "unsigned",
        "title": "Unicode Test 🌐",
        "body": unicode_body,
    }
    py_res, br_res = env.run_vector(page, wire)

    # Parity check: Both admit Unicode and CRLF cleanly
    assert py_res["admitted"] is True
    assert br_res["admitted"] is True

    # Parity check: Stored content is bit-exact
    stored_py_body = env.node.get_bulletin("DISCREPANCY-UNICODE")[1].decode("utf-8")
    assert stored_py_body == unicode_body

    content_area = page.locator("#contentArea").inner_text()
    assert "Level 3 warning in Sector B." in content_area
    assert "🚨" in content_area
    assert "💧" in content_area


def test_discrepancy_matrix_signature_trust_boundary(matrix_env):
    """
    Vector 11: Decoupled Signature Trust Boundary.
    Valid Ed25519 signature is cryptographically verified by Python node (verified_ed25519),
    while the zero-install Browser explicitly marks it SIGNATURE UNVERIFIED and warns that
    publisher trust is not established. Neither runtime implies physical station authorization.
    """
    env, page = matrix_env
    key = Ed25519PrivateKey.generate()
    b_id = "DISCREPANCY-SIG-BOUNDARY"
    rev = 1
    body_text = "Verified cryptographic signature test."
    content_hash = hashlib.sha3_256(body_text.encode("utf-8")).hexdigest()

    pub_hex, sig_hex = sign_bulletin_content(
        bulletin_id=b_id,
        revision=rev,
        content_hash=content_hash,
        private_key=key,
        title="Signature Test",
    )

    wire = {
        "v": 2,
        "id": b_id,
        "rev": rev,
        "pub": pub_hex,
        "sig": sig_hex,
        "title": "Signature Test",
        "body": body_text,
    }
    py_res, br_res = env.run_vector(page, wire)

    assert py_res["admitted"] is True
    assert br_res["admitted"] is True

    # Python node verification: mathematically verified Ed25519 signature
    py_stored = env.node.get_bulletin(b_id)[0]
    assert py_stored["verified_status"] == "verified_ed25519"
    assert py_stored["publisher_trust"] == "not_established"  # Trust != mathematical signature

    # Browser receiver verification: zero-install browser explicitly labels signature unverified
    content_area = page.locator("#contentArea").inner_text()
    assert "SIGNATURE UNVERIFIED" in content_area
    assert "Publisher trust not established" in content_area
    assert "AUTHENTIC" not in content_area  # Must NEVER claim authentic station authorization
