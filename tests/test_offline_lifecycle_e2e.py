# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
End-to-End Integration Test for the Complete Trustworthy Offline Delivery Lifecycle:
1. Ingest article content -> FastCDC chunks -> Merkle Tree.
2. Fountain streamer encodes droplets with repair redundancy -> Simulated 30% channel loss.
3. FountainStreamReceiver validates anti-pollution tags, collects rank, and assembles payload.
4. Payload & recipe persisted to SQLite database.
5. In-memory session purged to simulate complete device reboot / power failure.
6. Restored database queried with keyword search -> exact article retrieved.
7. Verified article exported to standard Kiwix / ZIM directory format.
"""

from pathlib import Path
import pytest

from scripts.verify_offline_lifecycle import run_lifecycle


def test_offline_delivery_lifecycle_full_mission(tmp_path: Path):
    db_path = tmp_path / "offline_lifecycle.db"
    zim_out = tmp_path / "zim_library"

    results = run_lifecycle(db_path=db_path, zim_out=zim_out, loss_rate=0.30)

    assert results["stage_1_ingest"] is True
    assert results["stage_2_transmission"] is True
    assert results["stage_3_reception"] is True
    assert results["stage_4_persistence"] is True
    assert results["stage_5_reboot"] is True
    assert results["stage_6_search"] is True
    assert results["stage_7_zim_export"] is True

    # Verify physical files on disk
    assert db_path.exists()
    assert (zim_out / "index.html").exists()
    assert (zim_out / "manifest.json").exists()
    assert (zim_out / "A").is_dir()
    assert len(list((zim_out / "A").glob("*.html"))) == 1


def test_offline_delivery_lifecycle_high_loss(tmp_path: Path):
    db_path = tmp_path / "offline_high_loss.db"
    zim_out = tmp_path / "zim_high_loss"

    # Even under 40% loss, redundancy=4.0 provides sufficient droplets to recover
    results = run_lifecycle(db_path=db_path, zim_out=zim_out, loss_rate=0.40)
    assert results["stage_3_reception"] is True
    assert results["stage_6_search"] is True
