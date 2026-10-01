# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Phase D Automated Test Suite:
Browser Bulletin Verification, Shared Python/Browser Test Vectors, and Trust-Tier Isolation.

Proves 1:1 agreement between Python (`tfp_core_v4.bulletin_identity` + `TFPNode`) and
the browser receiver (`acoustic_stream.js` + `acoustic_receiver.html`) across all 9
required categories:
1. Valid signed content (SHA3-256, canonical v2 envelope, Ed25519 sync + WebCrypto SubtleCrypto)
2. Altered body, title, ID, or revision (tamper rejection)
3. Invalid signatures (forged bytes, truncated/malformed hex, S >= L malleability, unsigned trusted-key claim)
4. Unknown publisher keys (valid_signature_unknown_key vs trusted_publisher)
5. Trusted publisher keys & trust isolation (unverified/unknown-key content never replaces
   verified trusted content, never pins a bulletin ID against a trusted publisher, and never
   advances the authoritative revision watermark)
6. Duplicate messages (idempotence & archive restoration)
7. Conflicting revisions (same revision with altered body or title signed by same key)
8. Out-of-order arrival (revision gap detection Rev 1 -> Rev 3, followed by stale Rev 2 rejection)
9. Persistence and restart across reload / SQLite reopen
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_core_v4.bulletin_identity import (
    SIGNATURE_VERSION,
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    canonical_envelope,
    sign_bulletin_content,
    verification_status,
    verify_bulletin_signature,
)
from tfp_core_v4.node import TFPNode
from tfp_core_v4.visualizer_server import get_static_assets_dir

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


@pytest.fixture(scope="module")
def receiver_http_server():
    """Serve static receiver assets over localhost HTTP (secure context for WebCrypto & SW)."""
    static_dir = str(get_static_assets_dir())
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=static_dir))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser, f"http://127.0.0.1:{server.server_port}/acoustic_receiver.html"
        browser.close()
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def page(receiver_http_server):
    browser, url = receiver_http_server
    context = browser.new_context()
    pg = context.new_page()
    pg.goto(url)
    pg.wait_for_selector("#packetCount")
    yield pg
    context.close()


def make_signed_wire(
    sk: Ed25519PrivateKey,
    bulletin_id: str = "PHASE-D-BULLETIN-001",
    revision: int = 1,
    title: str = "Emergency Water Advisory",
    body: str = "Boil water for 60 seconds before use in Sector 4.",
) -> dict[str, Any]:
    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n")
    content_hash = hashlib.sha3_256(normalized_body.encode("utf-8")).hexdigest()
    pub_hex, sig_hex = sign_bulletin_content(
        bulletin_id=bulletin_id,
        revision=revision,
        content_hash=content_hash,
        private_key=sk,
        title=title,
    )
    return {
        "v": SIGNATURE_VERSION,
        "id": bulletin_id,
        "rev": revision,
        "title": title,
        "body": body,
        "pub": pub_hex,
        "sig": sig_hex,
    }


def decode_in_browser(page, wire_dict: dict[str, Any]) -> dict[str, Any]:
    wav = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16).synthesize_wav(
        json.dumps(wire_dict, ensure_ascii=False).encode("utf-8")
    )
    b64 = base64.b64encode(wav).decode("ascii")
    res = page.evaluate("b64 => window.decodeAcousticWav(b64)", b64)
    decision = page.evaluate("() => window.lastBulletinDecision")
    return {"decode": res, "decision": decision}


@pytest.mark.parametrize("sign_bit", [0, 128])
def test_small_order_public_key_cannot_forge_trusted_bulletin(page, sign_bit):
    """An identity key and R=identity,S=0 must not authenticate any message.

    The second encoding sets the sign bit for x=0 (noncanonical). The old
    equation-only verifier accepted the canonical forgery as trusted.
    """
    identity = bytes([1] + [0] * 30 + [sign_bit]).hex()
    page.evaluate("pub => window.configureTrustedPublisherKeys([pub])", identity)
    wire = {"v": 2, "id": "FORGED-IDENTITY", "rev": 1,
            "title": "Forged advisory", "body": "No private key signed this.",
            "pub": identity, "sig": "01" + "00" * 63}
    result = decode_in_browser(page, wire)
    assert result["decision"]["admitted"] is False
    assert result["decision"]["verification"] == "invalid_signature"
    assert page.evaluate("() => localStorage.getItem('tfp_trusted_bulletin_watermarks')") in (None, "{}")


def test_actual_admission_offline_without_native_ed25519(receiver_http_server):
    """Cold offline reopening must use bundled crypto on the real audio admission path."""
    browser, url = receiver_http_server
    context = browser.new_context()
    try:
        # Simulate platforms lacking native Ed25519 while preserving the browser's SW.
        context.add_init_script("""Object.defineProperty(crypto, 'subtle', {
            value: undefined, configurable: true
        });""")
        pg = context.new_page()
        pg.goto(url)
        pg.wait_for_function("() => window.getReceiverReadiness?.().offlineAssetsState === 'offline_assets_ready'")
        sk = Ed25519PrivateKey.generate()
        pub = sk.public_key().public_bytes_raw().hex()
        pg.evaluate("pub => window.configureTrustedPublisherKeys([pub])", pub)
        pg.close()
        context.set_offline(True)
        pg = context.new_page()
        pg.goto(url)
        pg.wait_for_selector("#packetCount")
        wire = make_signed_wire(sk, bulletin_id="OFFLINE-MAINTAINED-CRYPTO")
        result = decode_in_browser(pg, wire)
        assert result["decision"]["admitted"] is True
        assert result["decision"]["verification"] == "trusted_publisher"
        assert "VERIFIED ED25519" in pg.locator("#contentArea").inner_text()
        forged = {**wire, "rev": 2, "body": "Tampered offline"}
        rejected = decode_in_browser(pg, forged)
        assert rejected["decision"]["admitted"] is False
        pg.reload()
        pg.wait_for_selector("#packetCount")
        replay = decode_in_browser(pg, wire)
        assert replay["decision"]["duplicate"] is True
    finally:
        context.close()


def test_shared_vectors_valid_signed_content_and_canonical_parity(page):
    """
    Category 1: Valid signed content.
    Proves Python and Browser (both synchronous RFC 8032 and async WebCrypto SubtleCrypto)
    produce identical SHA3-256 hashes, canonical v2 envelopes, and Ed25519 verifications
    across ASCII, Unicode, and CRLF-normalized payloads.
    """
    sk = Ed25519PrivateKey.generate()
    pub_hex = sk.public_key().public_bytes_raw().hex()

    vectors = [
        ("VEC-ASCII-01", 1, "Standard Advisory", "Simple ASCII emergency notice."),
        ("VEC-UNICODE-02", 2, "Alerta Sísmica 🚨", "Evacuación inmediata en Zona Sur • Agua 💧 disponible."),
        ("VEC-CRLF-03", 3, "Multiline Notice", "Line 1\r\nLine 2\rLine 3\nLine 4"),
        ("VEC-LONG-04", 10, "Extended Bulletin", "A" * 600),
    ]

    for bid, rev, title, raw_body in vectors:
        wire = make_signed_wire(sk, bulletin_id=bid, revision=rev, title=title, body=raw_body)
        norm_body = raw_body.replace("\r\n", "\n").replace("\r", "\n")
        py_hash = hashlib.sha3_256(norm_body.encode("utf-8")).hexdigest()
        py_envelope = canonical_envelope(bid, rev, py_hash, pub_hex, title, SIGNATURE_VERSION).decode("utf-8")
        py_status = verification_status(bid, rev, py_hash, pub_hex, wire["sig"], title, SIGNATURE_VERSION)
        assert py_status == "verified_ed25519"

        # Verify in browser against both untrusted and trusted lists
        js_env = page.evaluate(
            "args => window.verifyBulletinEnvelope(args.wire, [args.pub])",
            {"wire": wire, "pub": pub_hex},
        )
        assert js_env["validFields"] is True
        assert js_env["contentHash"] == py_hash
        assert js_env["canonicalEnvelope"] == py_envelope
        assert js_env["pythonVerifiedStatus"] == py_status
        assert js_env["verification"] == "trusted_publisher"

        # Verify WebCrypto SubtleCrypto agreement
        wc = page.evaluate(
            "args => window.verifyBulletinSignatureWebCrypto(args.pub, args.sig, args.env)",
            {"pub": pub_hex, "sig": wire["sig"], "env": py_envelope},
        )
        assert wc["valid"] is True


@pytest.mark.parametrize("tamper_field,tamper_value", [
    ("body", "Tampered body text: do NOT boil water."),
    ("title", "Tampered Headline"),
    ("id", "TAMPERED-BULLETIN-ID"),
    ("rev", 2),
])
def test_shared_vectors_altered_body_title_id_or_revision_rejected(
    page, tmp_path: Path, tamper_field: str, tamper_value: Any
):
    """
    Category 2: Altered body, title, ID, or revision.
    Proves that mutating any signed envelope field after signing causes both Python and
    the browser receiver to reject the bulletin as invalid_signature without admitting it
    or advancing watermarks.
    """
    sk = Ed25519PrivateKey.generate()
    pub_hex = sk.public_key().public_bytes_raw().hex()
    page.evaluate("pub => window.configureTrustedPublisherKeys([pub])", pub_hex)

    wire = make_signed_wire(sk, bulletin_id="TAMPER-TEST-01", revision=1, title="Authentic Title", body="Authentic body.")
    tampered = dict(wire)
    tampered[tamper_field] = tamper_value

    # 1. Python rejects with ValueError("Bulletin signature verification failed; content was not accepted")
    node = TFPNode(db_path=tmp_path / f"tamper_{tamper_field}.db")
    norm_body = tampered["body"].replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    with pytest.raises(ValueError, match="Bulletin signature verification failed"):
        node.store_bulletin(
            bulletin_id=tampered["id"],
            revision=tampered["rev"],
            data=norm_body,
            title=tampered["title"],
            publisher_id=tampered["pub"],
            signature_hex=tampered["sig"],
            signature_version=tampered["v"],
        )

    # 2. Browser rejects with invalid_signature and does not admit or store watermark
    res = decode_in_browser(page, tampered)
    assert res["decision"]["admitted"] is False
    assert res["decision"]["verification"] == "invalid_signature"
    assert "[INVALID SIGNATURE]" in page.locator("#packetFeed").inner_text()
    assert page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]').length") == 0
    assert page.evaluate("() => Object.keys(JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')).length") == 0


def test_shared_vectors_invalid_signatures_rejected(page, tmp_path: Path):
    """
    Category 3: Invalid signatures.
    Tests forged signature bytes, non-hex/truncated signatures, S >= L scalar malleability,
    and unsigned packets claiming a configured trusted publisher key.
    """
    sk = Ed25519PrivateKey.generate()
    pub_hex = sk.public_key().public_bytes_raw().hex()
    page.evaluate("pub => window.configureTrustedPublisherKeys([pub])", pub_hex)

    valid_wire = make_signed_wire(sk, bulletin_id="INVALID-SIG-01", revision=1)

    # A. Bit-flipped signature
    flipped_sig = ("ff" if valid_wire["sig"][:2] != "ff" else "00") + valid_wire["sig"][2:]
    # B. Truncated signature
    short_sig = valid_wire["sig"][:64]
    # C. S >= L malleable scalar (all 0xff in second 32 bytes)
    high_s_sig = valid_wire["sig"][:64] + ("ff" * 32)
    # D. Missing signature while claiming configured trusted publisher key
    missing_sig = None

    node = TFPNode(db_path=tmp_path / "invalid_sigs.db")
    for idx, bad_sig in enumerate([flipped_sig, short_sig, high_s_sig, missing_sig]):
        candidate = {**valid_wire, "id": f"INVALID-SIG-{idx}", "sig": bad_sig}
        with pytest.raises(ValueError, match="Bulletin signature verification failed"):
            node.store_bulletin(
                bulletin_id=candidate["id"],
                revision=candidate["rev"],
                data=candidate["body"].encode("utf-8"),
                title=candidate["title"],
                publisher_id=candidate["pub"],
                signature_hex=candidate["sig"],
                signature_version=candidate["v"],
            )

        res = decode_in_browser(page, candidate)
        assert res["decision"]["admitted"] is False
        assert res["decision"]["verification"] == "invalid_signature"

    assert page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]').length") == 0


def test_shared_vectors_unknown_key_vs_trusted_publisher_and_trust_isolation(page):
    """
    Categories 4 & 5: Unknown publisher keys, trusted publisher keys, and strict trust isolation.
    Verifies:
    - Unknown key valid signature -> valid_signature_unknown_key
    - Configured trusted publisher -> trusted_publisher
    - Unverified (unsigned) or unknown-key content NEVER:
      (a) pins a bulletin ID against a subsequent trusted publisher,
      (b) advances the authoritative revision watermark to block a trusted publisher,
      (c) overwrites or replaces an active trusted publisher bulletin in #contentArea or watermarks.
    """
    sk_trusted = Ed25519PrivateKey.generate()
    pub_trusted = sk_trusted.public_key().public_bytes_raw().hex()

    sk_unknown = Ed25519PrivateKey.generate()
    pub_unknown = sk_unknown.public_key().public_bytes_raw().hex()

    page.evaluate("pub => window.configureTrustedPublisherKeys([pub])", pub_trusted)
    readiness = page.evaluate("() => window.getReceiverReadiness()")
    assert readiness["publisherTrustState"] == "trusted_publisher_configured"

    bulletin_id = "CRITICAL-EVAC-ORDER"

    # Step 1: Unknown key broadcasts rev 10 first (attempting to pin bulletin_id and inflate watermark to 10)
    unknown_rev10 = make_signed_wire(
        sk_unknown,
        bulletin_id=bulletin_id,
        revision=10,
        title="Unknown Key High Revision Claim",
        body="Unverified unknown-key message claiming rev 10.",
    )
    res_unknown = decode_in_browser(page, unknown_rev10)
    assert res_unknown["decision"]["admitted"] is True
    assert res_unknown["decision"]["verification"] == "valid_signature_unknown_key"
    assert res_unknown["decision"]["publisherTrust"] == "unknown_key"
    assert "VALID SIGNATURE · UNKNOWN KEY" in page.locator("#contentArea").inner_text()
    # Authoritative trusted watermark must remain empty!
    trusted_wm_after_unknown = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_trusted_bulletin_watermarks') || '{}')")
    assert len(trusted_wm_after_unknown) == 0

    # Step 2: Configured trusted publisher broadcasts rev 1 for the SAME bulletin_id!
    # Because unknown_key cannot pin bulletin_id or advance the authoritative watermark,
    # trusted_publisher rev 1 MUST be accepted, replace the display, and evict the untrusted entry!
    trusted_rev1 = make_signed_wire(
        sk_trusted,
        bulletin_id=bulletin_id,
        revision=1,
        title="Official Trusted Evacuation Order (Rev 1)",
        body="Verified civil defense evacuation order for Sector 1.",
    )
    res_trusted = decode_in_browser(page, trusted_rev1)
    assert res_trusted["decision"]["admitted"] is True
    assert res_trusted["decision"]["verification"] == "trusted_publisher"
    assert res_trusted["decision"]["publisherTrust"] == "trusted_publisher"

    content_text = page.locator("#contentArea").inner_text()
    assert "Official Trusted Evacuation Order (Rev 1)" in content_text
    assert "[VERIFIED ED25519 · TRUSTED PUBLISHER]" in content_text
    assert pub_trusted in content_text

    trusted_wm = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_trusted_bulletin_watermarks') || '{}')")
    assert f"{pub_trusted}:{bulletin_id}" in trusted_wm
    assert trusted_wm[f"{pub_trusted}:{bulletin_id}"]["revision"] == 1

    # Step 3: Unknown key or unsigned packet attempts to overwrite or advance the trusted bulletin (rev 20)
    unknown_rev20 = make_signed_wire(
        sk_unknown,
        bulletin_id=bulletin_id,
        revision=20,
        title="Spoofed All-Clear (Rev 20)",
        body="Do not evacuate.",
    )
    res_spoof = decode_in_browser(page, unknown_rev20)
    assert res_spoof["decision"]["admitted"] is False
    assert res_spoof["decision"]["reason"] == "untrusted_cannot_override_trusted"

    unsigned_rev25 = {
        "v": 2,
        "id": bulletin_id,
        "rev": 25,
        "title": "Unsigned Override Attempt",
        "body": "Unsigned message attempting to override trusted bulletin.",
        "pub": None,
        "sig": None,
    }
    res_unsigned_override = decode_in_browser(page, unsigned_rev25)
    assert res_unsigned_override["decision"]["admitted"] is False
    assert res_unsigned_override["decision"]["reason"] == "untrusted_cannot_override_trusted"

    # Step 4: Even an untrusted bulletin for a DIFFERENT bulletin_id must NOT replace active trusted content in #contentArea
    other_unknown = make_signed_wire(
        sk_unknown,
        bulletin_id="OTHER-UNTRUSTED-BULLETIN",
        revision=1,
        title="Other Unknown Key Notice",
        body="Secondary untrusted notice.",
    )
    decode_in_browser(page, other_unknown)
    # Active #contentArea must STILL show the trusted publisher bulletin!
    assert "Official Trusted Evacuation Order (Rev 1)" in page.locator("#contentArea").inner_text()
    assert "Other Unknown Key Notice" not in page.locator("#contentArea").inner_text()


def test_shared_vectors_duplicates_conflicts_out_of_order_and_persistence(page, tmp_path: Path):
    """
    Categories 6, 7, 8, & 9:
    - Duplicate messages (idempotent handling + repeat restoration after archive clear)
    - Conflicting revisions (same revision with altered body or title signed by the trusted key)
    - Out-of-order arrival (Rev 1 -> Rev 3 gap warning, followed by late Rev 2 stale rejection)
    - Persistence across page reload and SQLite restart
    """
    sk = Ed25519PrivateKey.generate()
    pub_hex = sk.public_key().public_bytes_raw().hex()
    page.evaluate("pub => window.configureTrustedPublisherKeys([pub])", pub_hex)

    db_path = tmp_path / "phase_d_parity.db"
    node = TFPNode(db_path=db_path)
    bid = "SEQ-PARITY-2026"

    # 1. Valid Rev 1
    w1 = make_signed_wire(sk, bulletin_id=bid, revision=1, title="Advisory Rev 1", body="Initial shelter advisory.")
    node.store_bulletin(bid, 1, w1["body"].encode("utf-8"), w1["title"], pub_hex, w1["sig"], signature_version=2)
    r1 = decode_in_browser(page, w1)
    assert r1["decision"]["admitted"] is True

    # 2. Exact Duplicate of Rev 1 (Category 6)
    dup_recipe = node.store_bulletin(bid, 1, w1["body"].encode("utf-8"), w1["title"], pub_hex, w1["sig"], signature_version=2)
    assert dup_recipe.metadata["duplicate"] is True
    r1_dup = decode_in_browser(page, w1)
    assert r1_dup["decision"]["duplicate"] is True
    assert page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]').length") == 1

    # 3. Conflicting Rev 1 with different body signed by same key (Category 7)
    w1_conflict_body = make_signed_wire(sk, bulletin_id=bid, revision=1, title="Advisory Rev 1", body="Conflicting body text.")
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 1, w1_conflict_body["body"].encode("utf-8"), w1_conflict_body["title"], pub_hex, w1_conflict_body["sig"], signature_version=2)
    r1_conf_b = decode_in_browser(page, w1_conflict_body)
    assert r1_conf_b["decision"]["admitted"] is False
    assert r1_conf_b["decision"]["reason"] == "revision_conflict"

    # 4. Conflicting Rev 1 with different title signed by same key (Category 7)
    w1_conflict_title = make_signed_wire(sk, bulletin_id=bid, revision=1, title="Conflicting Title", body="Initial shelter advisory.")
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 1, w1_conflict_title["body"].encode("utf-8"), w1_conflict_title["title"], pub_hex, w1_conflict_title["sig"], signature_version=2)
    r1_conf_t = decode_in_browser(page, w1_conflict_title)
    assert r1_conf_t["decision"]["admitted"] is False
    assert r1_conf_t["decision"]["reason"] == "revision_conflict"

    # 5. Out-of-order arrival: Jump to Rev 3, then receive delayed Rev 2 (Category 8)
    w3 = make_signed_wire(sk, bulletin_id=bid, revision=3, title="Advisory Rev 3", body="Updated shelter advisory rev 3.")
    node.store_bulletin(bid, 3, w3["body"].encode("utf-8"), w3["title"], pub_hex, w3["sig"], signature_version=2)
    r3 = decode_in_browser(page, w3)
    assert r3["decision"]["admitted"] is True
    assert "MISSED BROADCAST WARNING: Revision gap detected (jumped from Rev 1 to Rev 3)" in page.locator("#contentArea").inner_text()

    w2_late = make_signed_wire(sk, bulletin_id=bid, revision=2, title="Advisory Rev 2", body="Delayed rev 2.")
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bid, 2, w2_late["body"].encode("utf-8"), w2_late["title"], pub_hex, w2_late["sig"], signature_version=2)
    r2_late = decode_in_browser(page, w2_late)
    assert r2_late["decision"]["admitted"] is False
    assert r2_late["decision"]["reason"] == "stale_revision"
    assert "Advisory Rev 3" in page.locator("#contentArea").inner_text()

    # 6. Persistence across reload & SQLite restart (Category 9)
    page.reload()
    page.wait_for_selector("#packetCount")
    restarted_node = TFPNode(db_path=db_path)

    # Verify trusted key and watermark survived reload
    readiness_after = page.evaluate("() => window.getReceiverReadiness()")
    assert readiness_after["publisherTrustState"] == "trusted_publisher_configured"
    assert pub_hex in readiness_after["trustedPublishers"]

    # Clicking archived Rev 3 restores it with [VERIFIED ED25519 · TRUSTED PUBLISHER]
    page.locator("#historyFeed .packet-line").first.click()
    reloaded_text = page.locator("#contentArea").inner_text()
    assert "Advisory Rev 3" in reloaded_text
    assert "[VERIFIED ED25519 · TRUSTED PUBLISHER]" in reloaded_text

    # Replaying stale Rev 2 after reload is still rejected in both runtimes
    with pytest.raises(StaleRevisionError):
        restarted_node.store_bulletin(bid, 2, w2_late["body"].encode("utf-8"), w2_late["title"], pub_hex, w2_late["sig"], signature_version=2)
    r2_after_reload = decode_in_browser(page, w2_late)
    assert r2_after_reload["decision"]["admitted"] is False
    assert r2_after_reload["decision"]["reason"] == "stale_revision"
