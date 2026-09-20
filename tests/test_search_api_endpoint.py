# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Contract tests for visualizer server search, article retrieval, and ingestion endpoints.
"""

import json
import threading
import time
from urllib.request import urlopen, Request
import pytest

from tfp_core_v4.cli import create_visualizer_server


@pytest.fixture(scope="module")
def api_server():
    server, port = create_visualizer_server(port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


def test_api_articles_list(api_server):
    with urlopen(f"{api_server}/api/articles") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["count"] >= 6
        assert len(data["articles"]) >= 6
        titles = [a["title"] for a in data["articles"]]
        assert any("Hypothermia" in t for t in titles)
        assert any("Water Purification" in t for t in titles)


def test_api_search_exact_and_fuzzy(api_server):
    # Test search for water chlorine
    url = f"{api_server}/api/search?q=chlorine+bleach+boiling"
    with urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["count"] > 0
        top = data["results"][0]
        assert "Water Purification" in top["metadata"]["title"]
        assert "merkle_root" in top
        assert top["score"] > 0


def test_api_search_empty_query(api_server):
    url = f"{api_server}/api/search?q="
    with urlopen(url) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        assert data["count"] == 0
        assert data["results"] == []


def test_api_article_standalone_reader(api_server):
    # First get list of articles
    with urlopen(f"{api_server}/api/articles") as resp:
        data = json.loads(resp.read().decode("utf-8"))
        root = data["articles"][0]["merkle_root"]

    # Fetch article HTML
    article_url = f"{api_server}/api/article?root={root}"
    with urlopen(article_url) as resp:
        assert resp.status == 200
        content_type = resp.headers.get("Content-Type", "")
        assert "text/html" in content_type
        html = resp.read().decode("utf-8")
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "class='container'" in html or "container" in html


def test_api_ingest_custom_markdown(api_server):
    custom_md = """# Emergency Tourniquet Application Protocol
> Tactical combat and disaster hemorrhage control.

## Direct Pressure
Apply firm direct manual pressure directly over the wound.

## Tourniquet Placement
Place the windlass tourniquet 2-3 inches proximal to the bleeding site.
- Twist windlass until arterial pulsatile bleeding stops.
- Record exact application time on the patient's forehead (e.g. T 14:32).
"""
    req = Request(
        f"{api_server}/api/ingest",
        data=custom_md.encode("utf-8"),
        headers={"Content-Type": "text/markdown"},
        method="POST",
    )
    with urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        assert "bundle" in data
        merkle_root = data["bundle"]["merkle_root"]
        assert len(merkle_root) > 0

    # Search for newly ingested article
    search_url = f"{api_server}/api/search?q=tourniquet+hemorrhage"
    with urlopen(search_url) as resp:
        assert resp.status == 200
        search_data = json.loads(resp.read().decode("utf-8"))
        assert search_data["count"] > 0
        assert "Tourniquet" in search_data["results"][0]["metadata"]["title"]
