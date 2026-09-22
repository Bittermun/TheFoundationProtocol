# SPDX-License-Identifier: Apache-2.0
"""Real Chromium callbacks and UI paths, with synthetic PCM rather than hardware."""
import base64
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from tfp_client.lib.audio.afsk_modulator import AFSKModulator

from tfp_core_v4.visualizer_server import get_static_assets_dir

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


@pytest.fixture(scope="module")
def browser_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(get_static_assets_dir())))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser, f"http://127.0.0.1:{server.server_port}/acoustic_receiver.html"
        browser.close()
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def page(browser_server):
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    yield page
    context.close()


def wire(revision=1, body="A previously unseen correction."):
    return {"v": 2, "id": "a-bulletin-with-a-long-stable-identity", "rev": revision,
            "title": f"Notice revision {revision}", "body": body, "pub": None, "sig": None}


def decode(page, data):
    wav = AFSKModulator().synthesize_wav(json.dumps(data).encode())
    return page.evaluate("b64 => window.decodeAcousticWav(b64)", base64.b64encode(wav).decode())


def test_revision_update_survives_shared_prefix_and_duplicate_replay(page):
    assert decode(page, wire())["count"] == 1
    assert decode(page, wire(2))["count"] == 1
    assert "Notice revision 2" in page.locator("#contentArea").inner_text()
    decode(page, wire(2))
    archive = page.evaluate("JSON.parse(localStorage.getItem('tfp_transmissions'))")
    assert len(archive) == 2
    assert archive[0]["revision"] == 2
    assert archive[0]["bulletinId"] == wire()["id"]


def test_simulation_provenance_survives_reload(page):
    page.click("#testBtn")
    page.wait_for_selector(".simulation-banner")
    page.reload()
    page.locator("#historyFeed .packet-line").first.click()
    assert "SIMULATION DEMO" in page.locator("#contentArea").inner_text()
    assert "AUTHENTIC" not in page.locator("#contentArea").inner_text()
    assert "Packets: 0 | CRC Valid: 0" in page.locator("#packetCount").inner_text()


def test_signed_packet_is_explicitly_unverified_in_browser_and_archive(page):
    packet = {**wire(), "pub": "a1" * 32, "sig": "b2" * 64, "title": "Modified signed headline"}
    decode(page, packet)
    for reopened in (False, True):
        if reopened:
            page.reload()
            page.locator("#historyFeed .packet-line").first.click()
        text = page.locator("#contentArea").inner_text()
        assert "SIGNATURE UNVERIFIED" in text
        assert "AUTHENTIC" not in text
        assert packet["pub"] in text


def start_live_capture(page, sample_rate):
    page.evaluate("""sampleRate => {
      window.AudioContext = class {
        constructor() { this.sampleRate = sampleRate; this.destination = {}; }
        createMediaStreamSource() { return {connect() {}}; }
        createAnalyser() { return {frequencyBinCount: 256, getByteTimeDomainData(a) {a.fill(128);}}; }
        createScriptProcessor() { window.testProcessor = {connect() {}}; return window.testProcessor; }
        close() {}
      };
      navigator.mediaDevices.getUserMedia = async () => ({getTracks: () => [{stop() {}}]});
    }""", sample_rate)
    page.click("#listenBtn")
    page.wait_for_function("() => Boolean(window.testProcessor && window.testProcessor.onaudioprocess)")


def feed_live_audio(page, wav):
    page.evaluate("""b64 => {
      const raw = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const {samples, sampleRate} = parseWavSamples(raw.buffer);
      const leading = Math.round(sampleRate * 0.137);
      const signal = new Float32Array(leading + samples.length + 4096);
      signal.set(samples, leading);
      for (let start = 0; start < signal.length; start += 2048) {
        const block = signal.slice(start, start + 2048);
        window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
      }
    }""", base64.b64encode(wav).decode())


@pytest.mark.parametrize("sample_rate,payload_size", [(8000, 700), (16000, 700), (44100, 700), (48000, 700), (16000, 4096), (48000, 4096)])
def test_live_callback_decodes_long_message_with_leading_silence(page, sample_rate, payload_size):
    payload = wire(body="")
    payload["body"] = "X" * (payload_size - len(json.dumps(payload).encode()))
    encoded = json.dumps(payload).encode()
    assert len(encoded) == payload_size
    wav = AFSKModulator(sample_rate=sample_rate).synthesize_wav(encoded)
    assert len(wav) / (2 * sample_rate) > 2.5
    start_live_capture(page, sample_rate)
    feed_live_audio(page, wav)
    assert payload["body"] == page.locator("#contentArea .content-body").text_content()
    assert "CRC VALID" in page.locator("#contentArea").inner_text()
    diagnostics = page.evaluate("window.liveAcousticDiagnostics()")
    assert diagnostics["maxBufferedSamples"] <= 2048 + sample_rate / 1000
    assert diagnostics["bufferedSamples"] <= sample_rate / 1000


def test_live_callback_accepts_correction_without_restarting_capture(page):
    start_live_capture(page, 16000)
    for revision in (1, 2, 2, 1):
        payload = wire(revision, body=f"Unseen continuous revision {revision}")
        wav = AFSKModulator().synthesize_wav(json.dumps(payload).encode())
        feed_live_audio(page, wav)
    assert "Notice revision 2" in page.locator("#contentArea").inner_text()
    assert page.evaluate("JSON.parse(localStorage.getItem('tfp_transmissions')).length") == 2


def test_file_upload_and_offline_archive_reopen(page, tmp_path):
    payload = wire(body="Unseen uploaded bulletin with a persisted identity.")
    wav = tmp_path / "received.wav"
    wav.write_bytes(AFSKModulator().synthesize_wav(json.dumps(payload).encode()))
    page.set_input_files("#wavFileInput", str(wav))
    page.wait_for_selector("#contentArea .content-body")
    assert page.locator("#contentArea .content-body").text_content() == payload["body"]
    page.reload()
    page.context.set_offline(True)
    page.locator("#historyFeed .packet-line").first.click()
    assert page.locator("#contentArea .content-body").text_content() == payload["body"]
    assert "UNSIGNED" in page.locator("#contentArea").inner_text()
    assert "Revision: 1" in page.locator("#contentArea").inner_text()


@pytest.mark.parametrize("junk", [b"x", b"abc"])
def test_file_upload_accepts_padded_riff_chunks(page, tmp_path, junk):
    import struct

    payload = wire(body="Bulletin in a recording with padded metadata.")
    wav = AFSKModulator().synthesize_wav(json.dumps(payload).encode())
    chunk = b"JUNK" + struct.pack("<I", len(junk)) + junk + b"\x00"
    recording = bytearray(wav[:12] + chunk + wav[12:])
    struct.pack_into("<I", recording, 4, len(recording) - 8)
    path = tmp_path / "padded.wav"
    path.write_bytes(recording)
    page.set_input_files("#wavFileInput", str(path))
    page.wait_for_selector("#contentArea .content-body", timeout=5000)
    assert page.locator("#contentArea .content-body").text_content() == payload["body"]


def test_conflicting_same_revision_does_not_replace_display_or_archive(page):
    decode(page, wire(body="Original"))
    decode(page, wire(body="Forged correction with no revision bump"))
    assert page.locator("#contentArea .content-body").text_content() == "Original"
    assert page.evaluate("JSON.parse(localStorage.getItem('tfp_transmissions')).length") == 1


def test_legacy_archive_is_not_presented_as_authenticated(page):
    page.evaluate("localStorage.setItem('tfp_transmissions', JSON.stringify([{type:'text', title:'Old entry', snippet:'Unknown origin'}]))")
    page.reload()
    page.locator("#historyFeed .packet-line").first.click()
    assert "PROVENANCE UNKNOWN" in page.locator("#contentArea").inner_text()
    assert "AUTHENTIC" not in page.locator("#contentArea").inner_text()
