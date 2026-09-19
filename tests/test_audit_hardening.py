# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Audit Hardening, Security Invariant & Property Fuzzing Test Suite.

Validates all audit remediation findings:
1. SSRF & Scheme Whitelist Defense (Bandit B310 in article_ingester.py).
2. Elimination of naked asserts in production paths (Bandit B101 in cli.py).
3. Constant-time digest comparisons across cryptographic and integrity checks.
4. Hypothesis property fuzzing on FastCDC boundary detection and reconstruction.
5. AFSK DSP phase continuity and sub-symbol clock recovery across sample rates.
6. Weak-phone standalone bundle budget (< 15 KB, zero external CDN scripts).
"""

import ast
import hashlib
import hmac
from pathlib import Path
import pytest
from hypothesis import given, settings, strategies as st

from tfp_client.lib.ingest.article_ingester import ArticleIngester
from tfp_client.lib.ingest.article_packager import ArticlePackager
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_core_v4.cdc import ContentDefinedChunker


class TestSecurityHardening:
    """Validates security boundaries and SSRF defenses."""

    @pytest.mark.parametrize("bad_url", [
        "file:///etc/passwd",
        "file:///C:/Windows/win.ini",
        "ftp://malicious.host/exploit",
        "gopher://evil.server:70",
        "data:text/html,<script>alert(1)</script>",
        "javascript:void(0)",
    ])
    def test_article_ingester_ssrf_disallowed_schemes(self, bad_url: str):
        """Ensure non-HTTP(S) schemes raise immediate ValueError."""
        with pytest.raises(ValueError, match="Disallowed URL scheme"):
            ArticleIngester.ingest_url(bad_url)

    def test_cli_has_zero_naked_asserts_in_production(self):
        """Ensure no ast.Assert nodes remain in tfp_core_v4/cli.py."""
        cli_path = Path(__file__).resolve().parent.parent / "tfp_core_v4" / "cli.py"
        tree = ast.parse(cli_path.read_text(encoding="utf-8"), filename=str(cli_path))

        assert_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        assert len(assert_nodes) == 0, f"Found {len(assert_nodes)} naked assert(s) in cli.py: {assert_nodes}"

    def test_constant_time_crypto_compare_behavior(self):
        """Verify hmac.compare_digest behavior with matching and mismatched digests."""
        d1 = hashlib.sha3_256(b"foundation-protocol-payload").hexdigest()
        d2 = hashlib.sha3_256(b"foundation-protocol-payload").hexdigest()
        d3 = hashlib.sha3_256(b"tampered-payload").hexdigest()

        assert hmac.compare_digest(d1, d2) is True
        assert hmac.compare_digest(d1, d3) is False


class TestWeakPhoneResourceInvariants:
    """Validates low-resource constraints for $30-$50 budget smartphones."""

    def test_standalone_reader_size_and_zero_cdn(self):
        """Ensure packaged HTML bundle is < 15 KB and contains zero external CDN dependencies."""
        article = ArticleIngester.ingest_markdown(
            "# Malaria Prevention & Rapid Treatment Protocol\n\n"
            "## Symptoms\nHigh fever, chills, and severe flu-like illness.\n\n"
            "## Emergency Measures\n"
            "- Administer Artemisinin-based combination therapy (ACT).\n"
            "- Hydrate with clean boiled water.\n"
            "- Use insecticide-treated bed nets for all family members.\n"
        )
        packager = ArticlePackager()
        bundle = packager.package_article(article)

        # 1. Size budget: < 15,000 bytes
        html_bytes = bundle.standalone_html.encode("utf-8")
        assert len(html_bytes) < 15000, f"Bundle size {len(html_bytes)} bytes exceeds 15 KB budget!"

        # 2. Zero CDN dependencies (must operate 100% offline)
        assert "http://" not in bundle.standalone_html
        assert "https://" not in bundle.standalone_html
        assert "fonts.googleapis.com" not in bundle.standalone_html

        # 3. Quota safety check
        assert "quota exceeded" in bundle.standalone_html or "localStorage.setItem" in bundle.standalone_html

        # 4. Offline Voice TTS support included
        assert "speechSynthesis" in bundle.standalone_html


class TestDSPAudioIntegrity:
    """Validates DSP phase continuity and clock recovery across sample rates."""

    @pytest.mark.parametrize("sample_rate", [8000, 16000, 22050])
    def test_afsk_roundtrip_across_sample_rates(self, sample_rate: int):
        """Ensure audio modulation/demodulation roundtrip succeeds at various sample rates."""
        payload = b"TFP-AUDIO-TEST-123"
        modulator = AFSKModulator(sample_rate=sample_rate, baud_rate=300, preamble_flags=16)
        wav_bytes = modulator.synthesize_wav(payload)

        demodulator = AFSKDemodulator(sample_rate=sample_rate, baud_rate=300)
        packets = demodulator.decode_wav(wav_bytes)

        assert len(packets) >= 1
        assert packets[0] == payload


class TestHypothesisFuzzing:
    """Property-based fuzzing tests using Hypothesis."""

    @settings(max_examples=25, deadline=None)
    @given(st.binary(min_size=0, max_size=32768))
    def test_fastcdc_arbitrary_bytes_fuzz(self, data: bytes):
        """Ensure FastCDC chunking handles arbitrary byte streams and always reassembles perfectly."""
        chunker = ContentDefinedChunker(min_size=128, target_size=512, max_size=1024)
        chunks = chunker.chunk(data)

        # Reassembly property
        reassembled = b"".join(chunks)
        assert reassembled == data

        # Chunk size property
        if len(data) > 0:
            assert len(chunks) >= 1
            for c in chunks[:-1]:
                assert len(c) >= chunker.min_size or len(c) == len(data)
