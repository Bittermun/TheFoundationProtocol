# SPDX-License-Identifier: Apache-2.0
"""Phase E tests: Browser AudioWorklet pipeline, buffer reuse, bounded queue contention, and UI vs. Worklet stall observability."""

from __future__ import annotations

import base64
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
from tfp_client.lib.audio.afsk_modulator import AFSKModulator

from tfp_core_v4.visualizer_server import get_static_assets_dir

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


@pytest.fixture(scope="module")
def browser_server():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SimpleHTTPRequestHandler, directory=str(get_static_assets_dir())),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser, f"http://127.0.0.1:{server.server_port}/acoustic_receiver.html"
        browser.close()
    server.shutdown()
    server.server_close()
    thread.join()


def _make_bulletin_wav(sample_rate: int = 48000, rev: int = 1, title: str = "Phase E Worklet Bulletin", body: str = "Verified over AudioWorklet pipeline.") -> tuple[dict, bytes]:
    payload = {
        "v": 2,
        "id": "phase-e-worklet-bulletin",
        "rev": rev,
        "title": title,
        "body": body,
    }
    raw = json.dumps(payload).encode("utf-8")
    wav = AFSKModulator(sample_rate=sample_rate).synthesize_wav(raw)
    return payload, wav


def _setup_real_worklet_capture(page):
    """Configure getUserMedia to return a silent Web Audio MediaStream track so real AudioContext + AudioWorklet initialize."""
    page.evaluate("""() => {
      navigator.mediaDevices.getUserMedia = async () => {
        const helperCtx = new (window.AudioContext || window.webkitAudioContext)();
        const dest = helperCtx.createMediaStreamDestination();
        const osc = helperCtx.createOscillator();
        const gain = helperCtx.createGain();
        gain.gain.value = 0.0;
        osc.connect(gain);
        gain.connect(dest);
        osc.start();
        window.__helperAudioCtx = helperCtx;
        return dest.stream;
      };
    }""")
    started = page.evaluate("() => window.startMicrophoneCapture()")
    assert started is True


def _feed_wav_blocks(page, wav_bytes: bytes):
    b64 = base64.b64encode(wav_bytes).decode("ascii")
    page.evaluate("""b64 => {
      const raw = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const {samples, sampleRate} = parseWavSamples(raw.buffer);
      const leading = Math.round(sampleRate * 0.12);
      const signal = new Float32Array(leading + samples.length + 4096);
      signal.set(samples, leading);
      for (let start = 0; start < signal.length; start += 2048) {
        const block = signal.slice(start, start + 2048);
        window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
      }
    }""", b64)


def test_real_audio_worklet_live_capture_and_timing_instrumentation(browser_server):
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    page.wait_for_function("() => window.getReceiverReadiness().offlineAssetsState === 'offline_assets_ready'")

    _setup_real_worklet_capture(page)
    diag0 = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag0["captureMode"] == "AudioWorklet"
    assert diag0["maxQueueSize"] == 32
    assert diag0["maxPoolBuffers"] == 32
    assert diag0["overloadPolicy"] == "drop_newest"
    assert diag0["activePipelineCount"] == 1

    sample_rate = diag0["sampleRate"]
    payload, wav = _make_bulletin_wav(sample_rate=sample_rate, body="AudioWorklet live decode verification body.")
    _feed_wav_blocks(page, wav)

    assert page.locator("#contentArea .content-body").text_content() == payload["body"]
    diag1 = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag1["callbackCount"] > 20
    assert diag1["lastProcessingTimeMs"] >= 0.0
    assert diag1["maxProcessingTimeMs"] >= diag1["lastProcessingTimeMs"]
    assert diag1["meanProcessingTimeMs"] > 0.0
    assert diag1["expectedCallbackIntervalMs"] == pytest.approx((2048.0 / sample_rate) * 1000.0, rel=1e-3)
    assert diag1["droppedBlocks"] == 0
    assert diag1["sequenceGapsDetected"] == 0
    assert diag1["sampleGapsDetected"] == 0

    page.evaluate("() => window.stopMicrophoneCapture()")
    context.close()


def test_sustained_listening_buffer_ownership_and_reuse_bounds(browser_server):
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)

    _setup_real_worklet_capture(page)
    sample_rate = page.evaluate("() => window.liveAcousticDiagnostics().sampleRate")

    # Push 200 blocks (409,600 samples = ~8.5s of continuous audio + noise)
    page.evaluate("""() => {
      const block = new Float32Array(2048);
      for (let i = 0; i < 200; i++) {
        for (let j = 0; j < 2048; j++) {
          block[j] = Math.sin((i * 2048 + j) * 0.17) * 0.25;
        }
        window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
      }
    }""")

    diag = page.evaluate("() => window.liveAcousticDiagnostics()")
    # Buffer ownership & reuse: in synchronous drain mode, only 1 pool buffer is allocated and reused >= 199 times
    assert diag["poolAllocatedBuffers"] == 1
    assert diag["poolFreeBuffers"] == 1
    assert diag["bufferReuseCount"] >= 199
    # IncrementalAFSKReceiver internal buffer must remain strictly bounded
    assert diag["maxBufferedSamples"] <= 2048 + (sample_rate // 1000) + 64
    assert diag["droppedBlocks"] == 0
    assert diag["overloadEvents"] == 0

    page.evaluate("() => window.stopMicrophoneCapture()")
    context.close()


def test_bounded_queue_overload_and_drop_policy(browser_server):
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)

    _setup_real_worklet_capture(page)

    # Enable consumer backpressure and push 40 blocks into a maxQueueSize=32 queue
    page.evaluate("""() => {
      window.setDecoderQueueBackpressure(true);
      const block = new Float32Array(2048);
      for (let i = 0; i < 40; i++) {
        window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
      }
    }""")

    diag_overloaded = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag_overloaded["consumerBackpressure"] is True
    assert diag_overloaded["queueDepth"] == 32
    assert diag_overloaded["maxQueueDepth"] == 32
    assert diag_overloaded["poolAllocatedBuffers"] == 32
    assert diag_overloaded["poolFreeBuffers"] == 0
    assert diag_overloaded["droppedBlocks"] == 8
    assert diag_overloaded["droppedSamples"] == 8 * 2048
    assert diag_overloaded["overloadEvents"] == 8
    assert "[AUDIO OVERLOAD]" in page.locator("#packetFeed").inner_text()

    # Release backpressure -> drains the 32 queued blocks and returns all 32 buffers to freePool
    page.evaluate("() => window.setDecoderQueueBackpressure(false)")
    diag_drained = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag_drained["queueDepth"] == 0
    assert diag_drained["poolFreeBuffers"] == 32

    # Push 1 post-overload block (seq=40 after seq=0..31 were processed and 32..39 were dropped)
    # Must detect the 8-block / 16384-sample discontinuity!
    page.evaluate("""() => {
      const block = new Float32Array(2048);
      window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
    }""")
    diag_after = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag_after["sequenceGapsDetected"] == 1
    assert diag_after["sampleGapsDetected"] == 1
    assert diag_after["totalMissedSamples"] == 8 * 2048
    assert "[AUDIO GAP]" in page.locator("#packetFeed").inner_text()

    page.evaluate("() => window.stopMicrophoneCapture()")
    context.close()


def test_deliberate_ui_stall_is_observable_not_silent(browser_server):
    """Separate test that deliberately stalls the UI thread and verifies the stall is observable."""
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)

    _setup_real_worklet_capture(page)
    sample_rate = page.evaluate("() => window.liveAcousticDiagnostics().sampleRate")

    # Feed initial block, then deliberately stall UI thread for 180 ms, then feed next block
    page.evaluate("""() => {
      const block = new Float32Array(2048);
      window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
      window.simulateUiStall(180);
      window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
    }""")

    diag = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag["uiStallDetected"] is True
    assert diag["uiStallEvents"] >= 1
    assert diag["lastUiStallDurationMs"] >= 150.0
    assert diag["maxCallbackIntervalMs"] >= 150.0
    assert "[UI STALL DETECTED]" in page.locator("#packetFeed").inner_text()

    # Verify a subsequent bulletin transmission still decodes after UI recovery
    payload, wav = _make_bulletin_wav(sample_rate=sample_rate, rev=2, body="Decoded after UI stall recovery.")
    _feed_wav_blocks(page, wav)
    assert page.locator("#contentArea .content-body").text_content() == payload["body"]

    page.evaluate("() => window.stopMicrophoneCapture()")
    context.close()


def test_deliberate_worklet_stall_is_observable_not_silent(browser_server):
    """Separate test that deliberately stalls the worklet/producer and verifies audio gaps are observable."""
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)

    _setup_real_worklet_capture(page)
    sample_rate = page.evaluate("() => window.liveAcousticDiagnostics().sampleRate")

    # Feed 2 normal blocks, inject a worklet stall of 6144 samples (3 blocks), then feed next block
    page.evaluate("""() => {
      const block = new Float32Array(2048);
      window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
      window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
      window.simulateWorkletStall(6144);
      window.testProcessor.onaudioprocess({inputBuffer: {getChannelData: () => block}});
    }""")

    diag = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag["workletStalled"] is True
    assert diag["workletStallEvents"] >= 1
    assert diag["sequenceGapsDetected"] == 1
    assert diag["sampleGapsDetected"] == 1
    assert diag["totalMissedSamples"] == 6144
    feed_text = page.locator("#packetFeed").inner_text()
    assert "[WORKLET STALL]" in feed_text
    assert "[AUDIO GAP]" in feed_text

    # Verify clean shutdown and restart resets contention/stall counters and restores clean decoding
    page.evaluate("() => window.restartMicrophoneCapture()")
    diag_restarted = page.evaluate("() => window.liveAcousticDiagnostics()")
    assert diag_restarted["activePipelineCount"] == 1
    assert diag_restarted["tracksReleasedCount"] >= 1
    assert diag_restarted["workletStalled"] is False
    assert diag_restarted["sequenceGapsDetected"] == 0
    assert diag_restarted["sampleGapsDetected"] == 0
    assert diag_restarted["droppedBlocks"] == 0

    payload, wav = _make_bulletin_wav(sample_rate=sample_rate, rev=3, body="Decoded after worklet stall and clean restart.")
    _feed_wav_blocks(page, wav)
    assert page.locator("#contentArea .content-body").text_content() == payload["body"]

    page.evaluate("() => window.stopMicrophoneCapture()")
    context.close()
