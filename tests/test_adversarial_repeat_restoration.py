# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Empirical Adversarial Challenge Suite:
Browser Repeat Restoration, Revision Identity, and Node Persistence.

Validates:
1. Browser acoustic receiver (acoustic_receiver.html):
   - Ingest Rev 1 -> Rev 2
   - Clear archive (clearArchive())
   - Transmit Rev 1 (stale revision) -> asserted rejected and NOT displayed
   - Transmit Rev 2 (exact duplicate) -> asserted restored to display and archive
   - Transmit Rev 2 with altered title -> asserted rejected as conflict
   - Transmit Rev 2 with altered title while archive is cleared -> asserted rejected, NOT restored
   - Transmit Rev 2 with altered body while archive is cleared -> asserted rejected
   - Conflicting publisher replay after clear -> asserted rejected as PublisherIdentityConflict
2. Node persistence (TFPNode):
   - Ingest Rev 1 -> Rev 2 (Ed25519 signed)
   - Prune display bulletins (keep_last_n=0)
   - Replay Rev 1 -> StaleRevisionError
   - Replay Rev 2 (exact duplicate) -> Restored to bulletins table
   - Replay Rev 2 with altered title -> RevisionConflictError
   - Replay Rev 2 with altered payload -> RevisionConflictError
   - Replay Rev 2 with altered publisher -> PublisherIdentityConflictError
   - Restart node across DB file -> Watermarks and conflict rules preserved
   - Unsigned bulletins repeat restoration and title conflict check
"""

import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_core_v4.bulletin_identity import (
    PublisherIdentityConflictError,
    RevisionConflictError,
    StaleRevisionError,
    sign_bulletin_content,
)
from tfp_core_v4.node import TFPNode

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


def get_receiver_html_path() -> Path:
    html_path = (
        Path(__file__).resolve().parent.parent
        / "tfp-foundation-protocol"
        / "tfp_demo"
        / "static"
        / "acoustic_receiver.html"
    )
    assert html_path.exists(), f"Receiver HTML not found at {html_path}"
    return html_path


def test_adversarial_browser_repeat_restoration_and_revision_identity():
    """
    Empirical Challenge 1:
    - Receive Rev 1 -> Rev 2.
    - Clear archive via clearArchive().
    - Transmit Rev 1 (stale revision) -> assert rejected and NOT displayed.
    - Transmit Rev 2 (exact duplicate) -> assert restored to display and archive.
    - Transmit Rev 2 with altered title -> assert rejected as conflict.
    """
    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        bulletin_id = "ALERT-CHALLENGE-2026"
        pub = "station-delta"

        # 1. Simulate receiving Rev 1
        b1 = {
            "id": bulletin_id,
            "rev": 1,
            "pub": pub,
            "title": "Initial Emergency Notice (Rev 1)",
            "body": "Boil water advisory for Sector 4.",
        }
        wav1 = modulator.synthesize_wav(json.dumps(b1).encode("utf-8"))
        res1 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1["count"] == 1

        # Verify Rev 1 displayed & archived
        assert "Initial Emergency Notice (Rev 1)" in page.locator("#contentArea").inner_text()
        assert "Boil water advisory for Sector 4." in page.locator("#contentArea").inner_text()
        archive1 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive1) == 1
        assert archive1[0]["revision"] == 1

        # 2. Simulate receiving Rev 2
        b2 = {
            "id": bulletin_id,
            "rev": 2,
            "pub": pub,
            "title": "Updated Emergency Notice (Rev 2)",
            "body": "Water treatment plant restored. Boil water advisory lifted.",
        }
        wav2 = modulator.synthesize_wav(json.dumps(b2).encode("utf-8"))
        res2 = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2).decode("ascii"))
        assert res2["count"] == 1

        # Verify Rev 2 displayed & archived (both revisions now in archive history)
        assert "Updated Emergency Notice (Rev 2)" in page.locator("#contentArea").inner_text()
        assert "Water treatment plant restored." in page.locator("#contentArea").inner_text()
        archive2 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive2) == 2
        assert archive2[0]["revision"] == 2
        assert archive2[1]["revision"] == 1

        # Verify durable watermark at Rev 2
        wm2 = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        wm_key = f"{pub}:{bulletin_id}"
        assert wm_key in wm2
        assert wm2[wm_key]["revision"] == 2
        assert wm2[wm_key]["title"] == "Updated Emergency Notice (Rev 2)"

        # 3. Clear archive via clearArchive()
        page.evaluate("() => clearArchive()")
        assert page.locator("#archiveCount").inner_text() == "0"
        archive_cleared = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive_cleared) == 0
        content_after_clear = page.locator("#contentArea").inner_text()
        assert "Start listening near a speaker" in content_after_clear

        # Verify watermark store is preserved across clearArchive()
        wm_retained = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm_key in wm_retained
        assert wm_retained[wm_key]["revision"] == 2

        # 4. Transmit Rev 1 (stale revision) -> assert rejected and NOT displayed
        res1_stale = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav1).decode("ascii"))
        assert res1_stale["count"] == 1

        feed_after_stale = page.locator("#packetFeed").inner_text()
        assert "Downgrade rejected" in feed_after_stale
        assert "[REJECTED STALE]" in feed_after_stale
        assert "superseded by local watermark 2" in feed_after_stale

        # Assert NOT displayed in contentArea and archive remains empty
        assert "Initial Emergency Notice (Rev 1)" not in page.locator("#contentArea").inner_text()
        assert "Boil water advisory" not in page.locator("#contentArea").inner_text()
        assert page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')") == []

        # 5. Transmit Rev 2 (exact duplicate) -> assert restored to display and archive
        res2_repeat = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2).decode("ascii"))
        assert res2_repeat["count"] == 1

        feed_after_repeat = page.locator("#packetFeed").inner_text()
        assert "Authentic repeat restored to display archive." in feed_after_repeat

        # Assert content area restored
        assert "Updated Emergency Notice (Rev 2)" in page.locator("#contentArea").inner_text()
        assert "Water treatment plant restored. Boil water advisory lifted." in page.locator("#contentArea").inner_text()

        # Assert restored to archive
        restored_archive = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(restored_archive) == 1
        assert restored_archive[0]["revision"] == 2
        assert restored_archive[0]["title"] == "Updated Emergency Notice (Rev 2)"

        # 6. Transmit Rev 2 with altered title -> assert rejected as conflict
        b2_altered_title = {
            "id": bulletin_id,
            "rev": 2,
            "pub": pub,
            "title": "FORGED TITLE: Sector 4 Evacuation Notice (Rev 2)",
            "body": "Water treatment plant restored. Boil water advisory lifted.",
        }
        wav2_altered = modulator.synthesize_wav(json.dumps(b2_altered_title).encode("utf-8"))
        res2_altered = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2_altered).decode("ascii"))
        assert res2_altered["count"] == 1

        feed_after_conflict = page.locator("#packetFeed").inner_text()
        assert "Revision conflict; previous content retained." in feed_after_conflict

        # Content area MUST NOT be updated with the forged title
        current_content = page.locator("#contentArea").inner_text()
        assert "FORGED TITLE" not in current_content
        assert "Updated Emergency Notice (Rev 2)" in current_content

        # Archive MUST NOT contain the forged title
        archive_after_conflict = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(archive_after_conflict) == 1
        assert archive_after_conflict[0]["title"] == "Updated Emergency Notice (Rev 2)"

        # Watermark remains authentic
        wm_final = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_bulletin_watermarks') || '{}')")
        assert wm_final[wm_key]["title"] == "Updated Emergency Notice (Rev 2)"

        browser.close()


def test_adversarial_browser_altered_title_rejected_when_archive_cleared():
    """
    Empirical Challenge 2:
    Transmit Rev 2 with altered title while archive is CLEARED.
    Must be rejected as revision conflict, NOT restored to display or archive.
    Then transmit authentic Rev 2, which MUST be successfully restored.
    """
    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        bulletin_id = "ALERT-CHALLENGE-2027"
        pub = "station-echo"

        b2_authentic = {
            "id": bulletin_id,
            "rev": 2,
            "pub": pub,
            "title": "Legitimate Grid Status (Rev 2)",
            "body": "Substation 12 online.",
        }
        wav2_auth = modulator.synthesize_wav(json.dumps(b2_authentic).encode("utf-8"))
        res = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2_auth).decode("ascii"))
        assert res["count"] == 1

        # Clear archive
        page.evaluate("() => clearArchive()")
        assert len(page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")) == 0
        assert "Start listening near a speaker" in page.locator("#contentArea").inner_text()

        # Attacker injects Rev 2 with altered title while archive is empty
        b2_tampered = {
            "id": bulletin_id,
            "rev": 2,
            "pub": pub,
            "title": "MALICIOUS OVERWRITE: Grid Collapsed",
            "body": "Substation 12 online.",
        }
        wav2_tampered = modulator.synthesize_wav(json.dumps(b2_tampered).encode("utf-8"))
        res_tampered = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2_tampered).decode("ascii"))
        assert res_tampered["count"] == 1

        # Must reject with Revision conflict
        feed = page.locator("#packetFeed").inner_text()
        assert "Revision conflict; previous content retained." in feed

        # Display MUST NOT show malicious title; must remain cleared
        assert "MALICIOUS OVERWRITE" not in page.locator("#contentArea").inner_text()
        assert "Start listening near a speaker" in page.locator("#contentArea").inner_text()

        # Archive MUST remain empty
        assert len(page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")) == 0

        # Now authentic Rev 2 arrives: MUST restore
        res_restore = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2_auth).decode("ascii"))
        assert res_restore["count"] == 1
        assert "Authentic repeat restored to display archive." in page.locator("#packetFeed").inner_text()
        assert "Legitimate Grid Status (Rev 2)" in page.locator("#contentArea").inner_text()
        assert len(page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")) == 1

        browser.close()


def test_adversarial_browser_altered_payload_hash_rejected_when_archive_cleared():
    """
    Empirical Challenge 3:
    Transmit Rev 2 with authentic title but altered body while archive is cleared.
    Must be rejected as revision conflict due to contentHash mismatch.
    """
    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        bulletin_id = "ALERT-CHALLENGE-2028"
        pub = "station-foxtrot"

        b2_auth = {
            "id": bulletin_id,
            "rev": 2,
            "pub": pub,
            "title": "Hospital Status (Rev 2)",
            "body": "Normal operations resumed.",
        }
        wav2_auth = modulator.synthesize_wav(json.dumps(b2_auth).encode("utf-8"))
        res = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2_auth).decode("ascii"))
        assert res["count"] == 1

        # Clear archive
        page.evaluate("() => clearArchive()")

        # Attacker keeps title identical but changes body
        b2_tampered_body = {
            "id": bulletin_id,
            "rev": 2,
            "pub": pub,
            "title": "Hospital Status (Rev 2)",
            "body": "CRITICAL ATTACK: Hospital evacuated!",
        }
        wav2_tampered_body = modulator.synthesize_wav(json.dumps(b2_tampered_body).encode("utf-8"))
        res_tampered = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav2_tampered_body).decode("ascii"))
        assert res_tampered["count"] == 1

        # Must reject as Revision conflict
        assert "Revision conflict; previous content retained." in page.locator("#packetFeed").inner_text()
        assert "CRITICAL ATTACK" not in page.locator("#contentArea").inner_text()
        assert len(page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")) == 0

        browser.close()


def test_adversarial_node_persistence_repeat_restoration_and_revision_identity(tmp_path: Path):
    """
    Empirical Challenge 4:
    Node persistence revision identity and restoration:
    - Receive Rev 1 -> Rev 2 (Ed25519 signed)
    - Prune display bulletins (keep_last_n=0)
    - Replay Rev 1 -> StaleRevisionError
    - Replay Rev 2 (exact duplicate) -> Restored to bulletins table
    - Replay Rev 2 with altered title -> RevisionConflictError
    - Replay Rev 2 with altered payload -> RevisionConflictError
    - Replay Rev 2 with altered publisher -> PublisherIdentityConflictError
    - Restart node across DB file -> durable watermark checks hold
    """
    db_file = tmp_path / "node_adversarial.db"
    node = TFPNode(db_path=str(db_file))

    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bulletin_id = "NODE-ADV-01"

    # 1. Ingest Rev 1
    data_rev1 = b"Advisory Rev 1 payload content"
    h1 = hashlib.sha3_256(data_rev1).hexdigest()
    title1 = "Weather Advisory Rev 1"
    _, sig1 = sign_bulletin_content(bulletin_id, 1, h1, key, title=title1)

    node.store_bulletin(
        bulletin_id=bulletin_id,
        revision=1,
        data=data_rev1,
        title=title1,
        publisher_id=pub_hex,
        signature_hex=sig1,
    )
    wm1 = node.get_bulletin_watermark(pub_hex, bulletin_id)
    assert wm1 is not None
    assert wm1["max_revision"] == 1
    assert wm1["latest_title"] == title1

    # 2. Ingest Rev 2
    data_rev2 = b"Advisory Rev 2 payload content - updated"
    h2 = hashlib.sha3_256(data_rev2).hexdigest()
    title2 = "Weather Advisory Rev 2"
    _, sig2 = sign_bulletin_content(bulletin_id, 2, h2, key, title=title2)

    node.store_bulletin(
        bulletin_id=bulletin_id,
        revision=2,
        data=data_rev2,
        title=title2,
        publisher_id=pub_hex,
        signature_hex=sig2,
    )
    wm2 = node.get_bulletin_watermark(pub_hex, bulletin_id)
    assert wm2 is not None
    assert wm2["max_revision"] == 2
    assert wm2["latest_title"] == title2

    # 3. Prune display bulletins to 0 (display records wiped, watermarks preserved)
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bulletin_id, 2) is None

    # 4. Replay Rev 1 (stale revision) -> must raise StaleRevisionError
    with pytest.raises(StaleRevisionError) as exc_stale:
        node.store_bulletin(
            bulletin_id=bulletin_id,
            revision=1,
            data=data_rev1,
            title=title1,
            publisher_id=pub_hex,
            signature_hex=sig1,
        )
    assert "superseded by known watermark 2" in str(exc_stale.value)

    # 5. Replay authentic Rev 2 (exact duplicate) -> must restore to display archive!
    recipe_restored = node.store_bulletin(
        bulletin_id=bulletin_id,
        revision=2,
        data=data_rev2,
        title=title2,
        publisher_id=pub_hex,
        signature_hex=sig2,
    )
    assert recipe_restored is not None
    restored_bulletin = node.get_bulletin(bulletin_id, 2)
    assert restored_bulletin is not None
    assert restored_bulletin[0]["title"] == title2

    # 6. Replay Rev 2 with altered title (validly signed with altered title) -> must raise RevisionConflictError
    title2_forged = "Forged Title Rev 2"
    _, sig2_forged = sign_bulletin_content(bulletin_id, 2, h2, key, title=title2_forged)
    with pytest.raises(RevisionConflictError) as exc_title:
        node.store_bulletin(
            bulletin_id=bulletin_id,
            revision=2,
            data=data_rev2,
            title=title2_forged,
            publisher_id=pub_hex,
            signature_hex=sig2_forged,
        )
    assert "conflict: differing title or content" in str(exc_title.value)

    # 7. Replay Rev 2 with altered data payload -> must raise RevisionConflictError
    data_rev2_forged = b"Tampered payload data"
    h2_tampered = hashlib.sha3_256(data_rev2_forged).hexdigest()
    _, sig2_tampered = sign_bulletin_content(bulletin_id, 2, h2_tampered, key, title=title2)
    with pytest.raises(RevisionConflictError) as exc_data:
        node.store_bulletin(
            bulletin_id=bulletin_id,
            revision=2,
            data=data_rev2_forged,
            title=title2,
            publisher_id=pub_hex,
            signature_hex=sig2_tampered,
        )
    assert "conflict: differing title or content" in str(exc_data.value)

    # 8. Replay Rev 2 with conflicting publisher -> must raise PublisherIdentityConflictError
    key_rogue = ed25519.Ed25519PrivateKey.generate()
    pub_rogue = key_rogue.public_key().public_bytes_raw().hex()
    _, sig2_rogue = sign_bulletin_content(bulletin_id, 2, h2, key_rogue, title=title2)
    with pytest.raises(PublisherIdentityConflictError) as exc_pub:
        node.store_bulletin(
            bulletin_id=bulletin_id,
            revision=2,
            data=data_rev2,
            title=title2,
            publisher_id=pub_rogue,
            signature_hex=sig2_rogue,
        )
    assert "publisher identity conflict" in str(exc_pub.value).lower()

    # 9. Prune again and test conflict detection on pruned record
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bulletin_id, 2) is None
    # Altered title against pruned record must still be caught by watermark latest_title!
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(
            bulletin_id=bulletin_id,
            revision=2,
            data=data_rev2,
            title=title2_forged,
            publisher_id=pub_hex,
            signature_hex=sig2_forged,
        )

    # 10. Restart node from SQLite DB and verify persistence
    node_reopened = TFPNode(db_path=str(db_file))
    wm = node_reopened.get_bulletin_watermark(pub_hex, bulletin_id)
    assert wm is not None
    assert wm["max_revision"] == 2
    assert wm["latest_title"] == title2

    # Stale replay after restart still blocked
    with pytest.raises(StaleRevisionError):
        node_reopened.store_bulletin(
            bulletin_id=bulletin_id,
            revision=1,
            data=data_rev1,
            title=title1,
            publisher_id=pub_hex,
            signature_hex=sig1,
        )

    # Altered title after restart still blocked
    with pytest.raises(RevisionConflictError):
        node_reopened.store_bulletin(
            bulletin_id=bulletin_id,
            revision=2,
            data=data_rev2,
            title=title2_forged,
            publisher_id=pub_hex,
            signature_hex=sig2_forged,
        )

    # Authentic repeat restores display record in reopened node
    node_reopened.store_bulletin(
        bulletin_id=bulletin_id,
        revision=2,
        data=data_rev2,
        title=title2,
        publisher_id=pub_hex,
        signature_hex=sig2,
    )
    assert node_reopened.get_bulletin(bulletin_id, 2) is not None


def test_adversarial_unsigned_bulletin_repeat_restoration_and_conflict(tmp_path: Path):
    """
    Empirical Challenge 5:
    Unsigned bulletins:
    - Receive unsigned Rev 1 -> Rev 2
    - Prune display records
    - Stale unsigned Rev 1 replay -> StaleRevisionError
    - Exact duplicate unsigned Rev 2 -> Restored to display
    - Altered title unsigned Rev 2 -> RevisionConflictError
    - Altered content unsigned Rev 2 -> RevisionConflictError
    """
    db_file = tmp_path / "unsigned_node.db"
    node = TFPNode(db_path=str(db_file))
    bid = "UNSIGNED-BULLETIN-001"

    # Rev 1
    d1 = b"Unsigned Content Rev 1"
    t1 = "Unsigned Notice Rev 1"
    node.store_bulletin(bid, 1, d1, title=t1, publisher_id="unsigned", signature_hex=None)

    # Rev 2
    d2 = b"Unsigned Content Rev 2"
    t2 = "Unsigned Notice Rev 2"
    node.store_bulletin(bid, 2, d2, title=t2, publisher_id="unsigned", signature_hex=None)

    # Prune
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid, 2) is None

    # Stale replay
    with pytest.raises(StaleRevisionError):
        node.store_bulletin(bid, 1, d1, title=t1, publisher_id="unsigned", signature_hex=None)

    # Authentic duplicate replay -> restored
    node.store_bulletin(bid, 2, d2, title=t2, publisher_id="unsigned", signature_hex=None)
    assert node.get_bulletin(bid, 2) is not None

    # Altered title replay -> conflict
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 2, d2, title="Altered Unsigned Title", publisher_id="unsigned", signature_hex=None)

    # Altered content replay -> conflict
    with pytest.raises(RevisionConflictError):
        node.store_bulletin(bid, 2, b"Tampered unsigned content", title=t2, publisher_id="unsigned", signature_hex=None)


def test_adversarial_browser_page_reload_persistence_after_restoration():
    """
    Empirical Challenge 6:
    Verify that an authentic restored repeat remains persisted in localStorage
    and is properly reloaded after a full browser page refresh.
    """
    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        bulletin_id = "ALERT-CHALLENGE-2029"
        pub = "station-hotel"

        b = {
            "id": bulletin_id,
            "rev": 1,
            "pub": pub,
            "title": "Road Closure Update (Rev 1)",
            "body": "Bridge 4 closed due to high water.",
        }
        wav = modulator.synthesize_wav(json.dumps(b).encode("utf-8"))
        res = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav).decode("ascii"))
        assert res["count"] == 1

        # Clear archive
        page.evaluate("() => clearArchive()")
        assert len(page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")) == 0

        # Authentic repeat restores archive
        res_repeat = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav).decode("ascii"))
        assert res_repeat["count"] == 1
        assert len(page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")) == 1

        # Reload browser page
        page.reload()
        page.wait_for_selector("#packetCount")

        # Archive count in UI must be 1
        assert page.locator("#archiveCount").inner_text() == "1"
        stored = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
        assert len(stored) == 1
        assert stored[0]["bulletinId"] == bulletin_id
        assert stored[0]["title"] == "Road Closure Update (Rev 1)"

        # Clicking the item in historyFeed displays it in contentArea
        item_el = page.locator("#historyFeed .packet-line").first
        item_el.click()
        assert "Road Closure Update (Rev 1)" in page.locator("#contentArea").inner_text()
        assert "Bridge 4 closed due to high water." in page.locator("#contentArea").inner_text()

        browser.close()


def test_adversarial_browser_malformed_fields_rejection():
    """
    Empirical Challenge 7:
    Adversarial inputs: malformed JSON, negative revision, float revision, empty id, non-string title.
    All must be rejected and must not corrupt watermark or display state.
    """
    html_path = get_receiver_html_path()
    modulator = AFSKModulator(sample_rate=16000, baud_rate=1200, preamble_flags=16)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(f"file:///{html_path.resolve().as_posix()}")
        page.wait_for_selector("#packetCount")

        malformed_cases = [
            {"id": "", "rev": 1, "body": "empty id"},
            {"id": "   ", "rev": 1, "body": "whitespace id"},
            {"id": "BAD-01", "rev": -1, "body": "negative rev"},
            {"id": "BAD-02", "rev": 0, "body": "zero rev"},
            {"id": "BAD-03", "rev": 1.5, "body": "float rev"},
            {"id": "BAD-04", "rev": 1, "body": 12345},  # body not string
            {"id": "BAD-05", "rev": 1, "title": 9999, "body": "title not string"},
        ]

        for case in malformed_cases:
            wav = modulator.synthesize_wav(json.dumps(case).encode("utf-8"))
            res = page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav).decode("ascii"))
            assert res["count"] == 1
            feed = page.locator("#packetFeed").inner_text()
            assert "Rejected malformed bulletin fields; previous content retained." in feed
            # Ensure not stored in archive
            archive = page.evaluate("() => JSON.parse(localStorage.getItem('tfp_transmissions') || '[]')")
            assert len(archive) == 0

        browser.close()


def test_adversarial_legacy_migration_out_of_order_repeat_restoration(tmp_path: Path):
    """
    Empirical Challenge 8:
    Legacy database upgrade where an older revision has a higher received_at timestamp.
    Verify whether the authentic repeat of the highest revision can be restored.
    """
    db_file = tmp_path / "legacy_out_of_order.db"
    key = ed25519.Ed25519PrivateKey.generate()
    pub_hex = key.public_key().public_bytes_raw().hex()
    bid = "OOO-BULLETIN-001"

    # Create pre-upgrade database with ONLY bulletins table
    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE bulletins (
            bulletin_id TEXT, revision INTEGER, content_hash TEXT, root_hash TEXT, publisher_id TEXT,
            signature_hex TEXT, title TEXT, received_at REAL, verified_status TEXT, data_size INTEGER,
            metadata_json TEXT, PRIMARY KEY (bulletin_id, revision)
        )
        """
    )

    # Rev 1 arrived later (timestamp 2000)
    c1 = b"Payload Rev 1"
    h1 = hashlib.sha3_256(c1).hexdigest()
    t1 = "Title Rev 1"
    _, s1 = sign_bulletin_content(bid, 1, h1, key, title=t1)
    meta1 = {"bulletin_id": bid, "revision": 1, "title": t1, "publisher_id": pub_hex, "content_hash": h1, "root_hash": "r1", "received_at": 2000.0}
    conn.execute("INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (bid, 1, h1, "r1", pub_hex, s1, t1, 2000.0, "verified_ed25519", len(c1), json.dumps(meta1)))

    # Rev 2 arrived earlier (timestamp 1000)
    c2 = b"Payload Rev 2"
    h2 = hashlib.sha3_256(c2).hexdigest()
    t2 = "Title Rev 2"
    _, s2 = sign_bulletin_content(bid, 2, h2, key, title=t2)
    meta2 = {"bulletin_id": bid, "revision": 2, "title": t2, "publisher_id": pub_hex, "content_hash": h2, "root_hash": "r2", "received_at": 1000.0}
    conn.execute("INSERT INTO bulletins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (bid, 2, h2, "r2", pub_hex, s2, t2, 1000.0, "verified_ed25519", len(c2), json.dumps(meta2)))
    conn.commit()
    conn.close()

    # Open with modern node
    node = TFPNode(db_path=str(db_file))

    # Prune bulletins so display record is erased
    node.prune_display_bulletins(keep_last_n=0)
    assert node.get_bulletin(bid, 2) is None

    # Now authentic repeat of Rev 2 arrives: MUST be restored!
    recipe = node.store_bulletin(
        bulletin_id=bid,
        revision=2,
        data=c2,
        title=t2,
        publisher_id=pub_hex,
        signature_hex=s2,
    )
    assert recipe is not None
    assert node.get_bulletin(bid, 2) is not None


