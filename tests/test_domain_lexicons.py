# SPDX-License-Identifier: Apache-2.0
"""
Tests for Phase 2: Domain Lexicon Factory and Pre-Trained Zstandard Dictionaries.
"""

from pathlib import Path
import pytest
import zstandard as zstd

from scripts.train_lexicon_dict import generate_domain_samples, train_lexicon_dictionary
from tfp_client.lib.lexicon.adapter_real import RealLexiconAdapter


def test_domain_sample_generation():
    med_samples = generate_domain_samples("medical", count=50)
    assert len(med_samples) == 50
    assert all(b"triage" in s or b"patient_id" in s for s in med_samples)

    relief_samples = generate_domain_samples("disaster_relief", count=30)
    assert len(relief_samples) == 30
    assert any(b"INC-RELIEF" in s for s in relief_samples)


def test_dictionary_training_and_bandwidth_savings():
    samples = generate_domain_samples("medical", count=100)
    dictionary, metrics = train_lexicon_dictionary(samples, dict_size=32768)

    assert metrics["dictionary_size_bytes"] > 1000
    assert metrics["dict_ratio"] > metrics["generic_ratio"]
    assert metrics["bandwidth_savings_vs_generic_pct"] > 30.0  # Must beat generic by > 30%


def test_real_lexicon_adapter_loads_disk_dictionary(tmp_path, monkeypatch):
    # Train and save a test dictionary
    samples = generate_domain_samples("medical", count=80)
    dictionary, _ = train_lexicon_dictionary(samples, dict_size=16384)
    
    dict_file = tmp_path / "medical.zdict"
    dict_file.write_bytes(dictionary.as_bytes())

    monkeypatch.chdir(tmp_path)
    (tmp_path / "lexicons").mkdir()
    (tmp_path / "lexicons" / "medical.zdict").write_bytes(dictionary.as_bytes())

    adapter = RealLexiconAdapter()
    loaded_dict = adapter._get_zstd_dict("medical")
    assert loaded_dict is not None
    assert loaded_dict.dict_id() == dictionary.dict_id()

    # Test compression and lossless decompression roundtrip
    test_payload = samples[-1]
    compressed = adapter.compress(test_payload, tags=["medical"])
    decompressed, meta = adapter.decompress(compressed, tags=["medical"])

    assert decompressed == test_payload
    assert meta["bandwidth_savings_pct"] > 30.0
    assert meta["domain"] == "medical"


def test_medical_lexicon_lossless_roundtrip_on_all_domains():
    adapter = RealLexiconAdapter()
    for domain in ["medical", "disaster_relief", "technical"]:
        sample = generate_domain_samples(domain, count=5)[0]
        compressed = adapter.compress(sample, tags=[domain])
        decompressed, meta = adapter.decompress(compressed, tags=[domain])
        assert decompressed == sample
        assert meta["domain"] == domain
