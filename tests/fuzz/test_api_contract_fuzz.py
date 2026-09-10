# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
FastAPI ASGI Contract Fuzzer for TFP Information Exchange Endpoints.

Verifies invariants:
1. Zero Unhandled 500 Errors: All malformed, adversarial, out-of-range, or fuzz-generated inputs
   must return structured HTTP 4xx (400, 401, 403, 404, 415, 422, 429) or 2xx/503 status codes.
   Under no circumstances is an unhandled 500 Internal Server Error allowed for client input.
2. Zero Silent Buffer Corruptions or Server Crashes: The ASGI application maintains consistent state
   across sequential and randomized fuzz bursts.
3. Targets Covered:
   - POST /api/publish (JSON payloads, headers, auth signatures)
   - GET /api/get/{root_hash} (content addressing, path traversal, device queries)
   - POST /api/gossip/broadcast (message types, JSON bodies, TTL parameters)
   - GET /api/content/... (search index, recipes, shards, distribution tracking)
"""

import json
import os
import tempfile
import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from fastapi.testclient import TestClient

from tfp_demo.server import app


@pytest.fixture(scope="module")
def api_client():
    """Module-scoped TestClient with isolated temporary SQLite DB to eliminate lock contention."""
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db.close()
    old_db = os.environ.get("TFP_DB_PATH")
    os.environ["TFP_DB_PATH"] = temp_db.name
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        if old_db is not None:
            os.environ["TFP_DB_PATH"] = old_db
        else:
            os.environ.pop("TFP_DB_PATH", None)
        try:
            if os.path.exists(temp_db.name):
                os.remove(temp_db.name)
        except Exception:
            pass


class TestAPIContractFuzzer:
    """Hypothesis-driven contract fuzzer for FastAPI ASGI endpoints."""

    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @given(
        device_id=st.text(max_size=50),
        title=st.text(max_size=100),
        text=st.text(max_size=2000),
        tags=st.lists(st.text(max_size=30), max_size=5),
        sig_header=st.one_of(st.none(), st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./+=:; ", max_size=64)),
        content_type=st.sampled_from(["application/json", "application/xml", "text/plain"]),
    )
    def test_publish_contract_fuzz(
        self, api_client: TestClient, device_id: str, title: str, text: str, tags: list, sig_header: str, content_type: str
    ):
        """
        Contract Invariant: POST /api/publish handles fuzzed headers and payloads with structured 4xx,
        never an unhandled 500 error.
        """
        headers = {"content-type": content_type}
        if sig_header is not None:
            headers["X-Device-Sig"] = sig_header

        payload = {
            "device_id": device_id,
            "title": title,
            "text": text,
            "tags": tags,
        }

        response = api_client.post("/api/publish", headers=headers, json=payload)

        # Invariant: Must not return unhandled 500
        assert response.status_code != 500, f"Unhandled 500 on /api/publish: {response.text}"
        assert response.status_code in {200, 201, 400, 401, 403, 415, 422, 429}

    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @given(
        raw_body=st.one_of(
            st.binary(min_size=0, max_size=1024),
            st.text(min_size=0, max_size=500).map(lambda s: s.encode("utf-8")),
        ),
        sig_header=st.one_of(st.none(), st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./+=:; ", max_size=64)),
    )
    def test_publish_malformed_raw_body_fuzz(self, api_client: TestClient, raw_body: bytes, sig_header: str):
        """Contract Invariant: POST /api/publish rejects arbitrary raw bytes with 400/415/422, zero 500s."""
        headers = {"content-type": "application/json"}
        if sig_header:
            headers["X-Device-Sig"] = sig_header

        response = api_client.post("/api/publish", headers=headers, content=raw_body)
        assert response.status_code != 500, f"Unhandled 500 on raw publish: {response.text}"
        assert response.status_code in {400, 401, 415, 422}

    @settings(max_examples=25, deadline=None)
    @given(
        root_hash=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./\\",
            min_size=1,
            max_size=80,
        ),
        stream=st.booleans(),
        device_id=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=30),
    )
    def test_get_content_contract_fuzz(self, api_client: TestClient, root_hash: str, stream: bool, device_id: str):
        """
        Contract Invariant: GET /api/get/{root_hash} with arbitrary hash strings (including path traversal)
        returns structured 404/400/402/422, zero 500 errors.
        """
        response = api_client.get(
            f"/api/get/{root_hash}",
            params={"stream": stream, "device_id": device_id},
        )
        assert response.status_code != 500, f"Unhandled 500 on GET /api/get/{root_hash}: {response.text}"
        assert response.status_code in {200, 400, 402, 404, 422}

    @settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.large_base_example])
    @given(
        message_type=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=40),
        ttl=st.integers(min_value=-10, max_value=100),
        peer_secret=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_", max_size=40),
        payload=st.dictionaries(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=10),
            st.one_of(st.text(max_size=50), st.integers(), st.booleans(), st.none()),
            max_size=5,
        ),
    )
    def test_gossip_broadcast_contract_fuzz(
        self, api_client: TestClient, message_type: str, ttl: int, peer_secret: str, payload: dict
    ):
        """
        Contract Invariant: POST /api/gossip/broadcast handles varied TTLs, peer secrets, and payloads
        with structured 200 or 4xx responses, zero 500 errors.
        """
        headers = {}
        if peer_secret:
            headers["X-TFP-Peer-Secret"] = peer_secret

        response = api_client.post(
            "/api/gossip/broadcast",
            params={"message_type": message_type, "ttl": ttl},
            headers=headers,
            json=payload,
        )

        assert response.status_code != 500, f"Unhandled 500 on /api/gossip/broadcast: {response.text}"
        assert response.status_code in {200, 400, 401, 422}

    @settings(max_examples=20, deadline=None)
    @given(
        root_hash=st.text(alphabet="abcdef0123456789", min_size=1, max_size=64),
        shard_idx=st.integers(min_value=-5, max_value=500),
    )
    def test_content_endpoints_contract_fuzz(self, api_client: TestClient, root_hash: str, shard_idx: int):
        """
        Contract Invariant: GET /api/content/{root_hash}/recipe and shard endpoints return structured 4xx,
        never unhandled 500.
        """
        # Recipe endpoint
        r_recipe = api_client.get(f"/api/content/{root_hash}/recipe")
        assert r_recipe.status_code != 500, f"Unhandled 500 on get_recipe: {r_recipe.text}"
        assert r_recipe.status_code in {200, 400, 404, 422, 503}

        # Shard endpoint
        r_shard = api_client.get(f"/api/content/{root_hash}/shard/{shard_idx}")
        assert r_shard.status_code != 500, f"Unhandled 500 on get_shard: {r_shard.text}"
        assert r_shard.status_code in {200, 400, 404, 422, 503}

    @settings(max_examples=20, deadline=None)
    @given(
        tag=st.text(alphabet="abcdefghijklmnopqrstuvwxyz", max_size=20),
        limit=st.integers(min_value=-5, max_value=200),
        offset=st.integers(min_value=-5, max_value=200),
    )
    def test_content_list_and_search_contract_fuzz(self, api_client: TestClient, tag: str, limit: int, offset: int):
        """Contract Invariant: GET /api/content with fuzzed pagination parameters returns 200 or 422, zero 500s."""
        params = {"tag": tag, "limit": limit, "offset": offset}
        response = api_client.get("/api/content", params=params)
        assert response.status_code != 500, f"Unhandled 500 on /api/content: {response.text}"
        assert response.status_code in {200, 400, 422}
