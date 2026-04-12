"""
Integration test: full publish → IPFS pin → Nostr announce → subscriber discover pipeline.

Validates the end-to-end flow across all major layers without requiring a real
network connection (IPFS and Nostr operate in offline mode).

Layers exercised:
    Broadcaster (seed) → IPFSBridge (pin, offline) → NostrBridge (announce, offline)
    → NostrSubscriber (receive via _handle_message) → on_event callback

Demo server pipeline:
    POST /api/enroll → POST /api/earn → POST /api/publish → GET /api/content
    → GET /api/get/<hash>

Persistence test:
    Publish content → restart TestClient → content still present in pib.db
"""

import hashlib
import hmac as _hmac
import json
import os
import pathlib
import tempfile

from fastapi.testclient import TestClient

os.environ.setdefault("TFP_DB_PATH", ":memory:")

from tfp_broadcaster.broadcaster import Broadcaster
from tfp_client.lib.bridges.ipfs_bridge import IPFSBridge
from tfp_client.lib.bridges.nostr_bridge import TFP_CONTENT_KIND, TFP_CONTENT_ANNOUNCE_KIND, NostrBridge
from tfp_client.lib.bridges.nostr_subscriber import NostrSubscriber
from tfp_demo.server import app

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_sig(puf_entropy: bytes, message: str) -> str:
    return _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Layer 1 + 2: Broadcaster → IPFS pin (offline)
# ---------------------------------------------------------------------------


class TestPublishToIPFS:
    def test_pin_offline_returns_stub_cid(self):
        content = b"IPFS pipeline test content"
        ipfs = IPFSBridge(offline=True)
        pin_result = ipfs.pin(content, metadata={"title": "IPFS Test"})

        assert pin_result.cid.startswith("offline:")
        assert pin_result.pinned is False
        assert pin_result.size_bytes == len(content)

    def test_pin_content_hash_matches_broadcaster(self):
        content = b"IPFS pipeline test content"
        broadcaster = Broadcaster()
        result = broadcaster.seed_content(
            content, metadata={"title": "IPFS Test"}, use_ldm=False
        )

        ipfs = IPFSBridge(offline=True)
        pin_result = ipfs.pin(content, metadata={"title": "IPFS Test"})

        assert pin_result.content_hash == result["root_hash"]

    def test_manual_mapping_roundtrip(self):
        """record_mapping / get_cid_for_hash / get_hash_for_cid round-trip."""
        ipfs = IPFSBridge(offline=True)
        ipfs.record_mapping("a" * 64, "QmTestCID")
        assert ipfs.get_cid_for_hash("a" * 64) == "QmTestCID"
        assert ipfs.get_hash_for_cid("QmTestCID") == "a" * 64


# ---------------------------------------------------------------------------
# Layer 2 + 3: NostrBridge announce → NostrSubscriber receive
# ---------------------------------------------------------------------------


class TestNostrAnnounceThenDiscover:
    def test_publish_event_received_by_subscriber(self):
        broadcaster = Broadcaster()
        content = b"Nostr pipeline integration test"
        result = broadcaster.seed_content(
            content, metadata={"title": "Nostr Test"}, use_ldm=False
        )
        root_hash = result["root_hash"]

        # Build announcement (offline — no relay needed)
        bridge = NostrBridge(privkey=b"\xaa" * 32, offline=True)
        event = bridge.publish_content_announcement(
            root_hash, metadata={"title": "Nostr Test", "tags": ["integration"]}
        )
        assert event.kind == TFP_CONTENT_ANNOUNCE_KIND
        assert root_hash in event.content

        # Subscriber receives event via _handle_message (simulates relay delivery)
        discovered = []
        subscriber = NostrSubscriber(offline=True, on_event=discovered.append)
        raw_msg = json.dumps(["EVENT", "tfp-content-discovery", event.to_dict()])
        subscriber._handle_message(raw_msg)

        assert len(discovered) == 1
        payload = json.loads(discovered[0]["content"])
        assert payload["hash"] == root_hash

    def test_subscriber_log_contains_event(self):
        bridge = NostrBridge(privkey=b"\xbb" * 32, offline=True)
        event = bridge.publish_content_announcement("c" * 64, metadata={"title": "T"})

        subscriber = NostrSubscriber(offline=True)
        subscriber._handle_message(json.dumps(["EVENT", "sub", event.to_dict()]))

        received = subscriber.get_received()
        assert len(received) == 1
        payload = json.loads(received[0]["content"])
        assert payload["hash"] == "c" * 64


# ---------------------------------------------------------------------------
# Full demo server pipeline (end-to-end via HTTP)
# ---------------------------------------------------------------------------


class TestDemoServerPipeline:
    def test_enroll_earn_publish_search_get(self):
        puf_entropy = bytes(range(32))
        device_id = "pipeline-test-device"

        with TestClient(app) as client:
            # Enroll
            enroll = client.post(
                "/api/enroll",
                json={"device_id": device_id, "puf_entropy_hex": puf_entropy.hex()},
            )
            assert enroll.status_code == 200, enroll.text

            # Earn credits
            task_id = "pipeline-task-001"
            earn = client.post(
                "/api/earn",
                json={"device_id": device_id, "task_id": task_id},
                headers={
                    "X-Device-Sig": _make_sig(puf_entropy, f"{device_id}:{task_id}")
                },
            )
            assert earn.status_code == 200, earn.text
            assert earn.json()["credits_earned"] == 10

            # Publish
            title = "Pipeline Integration"
            pub = client.post(
                "/api/publish",
                json={
                    "title": title,
                    "text": "Full pipeline integration test content",
                    "tags": ["integration", "test"],
                    "device_id": device_id,
                },
                headers={
                    "X-Device-Sig": _make_sig(puf_entropy, f"{device_id}:{title}")
                },
            )
            assert pub.status_code == 200, pub.text
            root_hash = pub.json()["root_hash"]

            # Discover via tag search
            search = client.get("/api/content", params={"tag": "integration"})
            assert search.status_code == 200
            hashes = [item["root_hash"] for item in search.json()["items"]]
            assert root_hash in hashes

            # Retrieve content
            get = client.get(f"/api/get/{root_hash}", params={"device_id": device_id})
            assert get.status_code == 200
            assert get.json()["text"] == "Full pipeline integration test content"
            assert get.json()["root_hash"] == root_hash

    def test_tag_search_returns_only_matching(self):
        puf_entropy = bytes(range(32))
        device_id = "search-test"

        with TestClient(app) as client:
            client.post(
                "/api/enroll",
                json={"device_id": device_id, "puf_entropy_hex": puf_entropy.hex()},
            )
            title = "Unique Tag Article"
            client.post(
                "/api/publish",
                json={
                    "title": title,
                    "text": "content with a rare tag",
                    "tags": ["rare-tag-abc"],
                    "device_id": device_id,
                },
                headers={
                    "X-Device-Sig": _make_sig(puf_entropy, f"{device_id}:{title}")
                },
            )
            results = client.get("/api/content", params={"tag": "rare-tag-abc"}).json()
            assert all("rare-tag-abc" in item["tags"] for item in results["items"])

            empty = client.get("/api/content", params={"tag": "no-such-tag"}).json()
            assert empty["items"] == []


# ---------------------------------------------------------------------------
# Persistence: content survives server restart
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_content_survives_restart(self):
        import shutil
        fd, db_file = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(db_file)  # let SQLite create a fresh file

        puf_entropy = bytes(range(32))
        device_id = "persist-device"
        title = "Persistent Content"
        original_db_path = os.environ.get("TFP_DB_PATH", ":memory:")

        try:
            os.environ["TFP_DB_PATH"] = db_file

            # First "boot" — publish content
            with TestClient(app) as client:
                client.post(
                    "/api/enroll",
                    json={"device_id": device_id, "puf_entropy_hex": puf_entropy.hex()},
                )
                pub = client.post(
                    "/api/publish",
                    json={
                        "title": title,
                        "text": "Survives restart",
                        "tags": ["persist"],
                        "device_id": device_id,
                    },
                    headers={
                        "X-Device-Sig": _make_sig(puf_entropy, f"{device_id}:{title}")
                    },
                )
                assert pub.status_code == 200, pub.text
                root_hash = pub.json()["root_hash"]

            # Second "boot" — content must still be present
            with TestClient(app) as client2:
                items = client2.get("/api/content").json()["items"]
                hashes = [i["root_hash"] for i in items]
                assert root_hash in hashes, "Content not persisted after restart"
        finally:
            os.environ["TFP_DB_PATH"] = original_db_path
            try:
                os.unlink(db_file)
            except OSError:
                pass
            shutil.rmtree(
                pathlib.Path(db_file).with_suffix(".blobs"), ignore_errors=True
            )
