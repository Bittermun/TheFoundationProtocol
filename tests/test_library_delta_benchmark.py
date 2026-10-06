"""Tests for scripts/benchmark_library_delta.py."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import pytest

from scripts.benchmark_library_delta import generate_benchmark_report, evaluate_backend
from library_update_support import create_zim


def test_benchmark_report_real_zim_pair(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    out = tmp_path / "report.json"
    python_exe = Path(sys.executable)

    report = generate_benchmark_report(base, target, out, python_exe, timeout_seconds=30.0)

    assert report["schema_version"] == 1
    assert "git_commit" in report
    assert report["inputs"]["base"]["size_bytes"] == 363989
    assert report["inputs"]["target"]["size_bytes"] == 363989

    results = report["results"]
    for backend in ("cdc", "zstd", "full"):
        assert results[backend]["status"] == "passed"
        raw = results[backend]["raw_payload"]
        assert raw["reconstructed_matches"] is True
        assert raw["reconstructed_sha3"] == report["inputs"]["target"]["sha3_256"]
        assert raw["encode_peak_rss_bytes"] <= 256 * 1024 * 1024
        assert raw["decode_peak_rss_bytes"] <= 256 * 1024 * 1024

    # Observed 243-247 byte probe on this fixture
    assert results["zstd"]["raw_payload"]["artifact_bytes"] < 1000
    assert results["cdc"]["raw_payload"]["artifact_bytes"] == 83337
    assert results["full"]["raw_payload"]["artifact_bytes"] == 363989

    # Verify serialized report matches
    assert out.exists()
    serialized = json.loads(out.read_text(encoding="utf-8"))
    assert serialized == report


def test_benchmark_no_private_keys_recorded(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    out = tmp_path / "report.json"
    python_exe = Path(sys.executable)

    report = generate_benchmark_report(base, target, out, python_exe, timeout_seconds=30.0)

    dumped = json.dumps(report).lower()
    for forbidden in ("private", "transport_key", "secret", "private_key", "signing_key"):
        assert forbidden not in dumped, f"Forbidden key material term '{forbidden}' found in report"


def test_benchmark_subprocess_nonzero_failure_reporting(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    python_exe = Path(sys.executable)

    # Test with invalid backend
    result = evaluate_backend(
        backend="invalid_backend",
        base=base,
        target=target,
        work_dir=tmp_path,
        python_exe=python_exe,
        target_sha3="somehash",
        base_sha3="somebasehash",
        target_size=100,
        timeout_seconds=5.0,
    )
    assert result["status"] == "failed"
    assert "Encode exited with code" in result["failure_reason"] or "invalid choice" in result["failure_reason"].lower()


def test_benchmark_reconstruction_mismatch_reporting(tmp_path: Path) -> None:
    base = Path("tests/fixtures/library_update/base.zim")
    target = Path("tests/fixtures/library_update/target.zim")
    python_exe = Path(sys.executable)

    # Pass an incorrect target_sha3 so that verification fails
    result = evaluate_backend(
        backend="full",
        base=base,
        target=target,
        work_dir=tmp_path,
        python_exe=python_exe,
        target_sha3="0000000000000000000000000000000000000000000000000000000000000000",
        base_sha3="somebasehash",
        target_size=363989,
        timeout_seconds=10.0,
    )
    assert result["status"] == "failed"
    assert "Reconstructed SHA3 mismatch" in result["failure_reason"]


def test_benchmark_incompressible_changed_pair(tmp_path: Path) -> None:
    pytest.importorskip("libzim.writer", reason="Install optional libzim fixture generator")
    base = tmp_path / "base.zim"
    target = tmp_path / "target.zim"
    create_zim(base, revision=10)
    create_zim(target, revision=20)

    out = tmp_path / "report_incompressible.json"
    report = generate_benchmark_report(base, target, out, Path(sys.executable), timeout_seconds=30.0)

    assert report["schema_version"] == 1
    for backend in ("cdc", "zstd", "full"):
        assert report["results"][backend]["status"] == "passed"
        assert report["results"][backend]["raw_payload"]["reconstructed_matches"] is True
