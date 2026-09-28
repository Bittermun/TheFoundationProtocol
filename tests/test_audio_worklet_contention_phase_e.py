# SPDX-License-Identifier: Apache-2.0
"""Real AudioWorklet integration plus explicitly isolated controller tests.

Synthetic MediaStream audio exercises browser wiring, not physical acoustics.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tfp_client.lib.audio.afsk_modulator import AFSKModulator
from tfp_core_v4.bulletin_identity import sign_bulletin_content
from tfp_core_v4.visualizer_server import get_static_assets_dir

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright


@pytest.fixture(scope="module")
def browser_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(get_static_assets_dir())))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser, f"http://127.0.0.1:{server.server_port}/acoustic_receiver.html"
        browser.close()
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.fixture
def page(browser_server):
    browser, url = browser_server
    context = browser.new_context(service_workers="block")
    pg = context.new_page()
    pg.goto(url)
    yield pg
    context.close()


def _start_real_capture(page):
    page.evaluate("""() => {
      navigator.mediaDevices.getUserMedia = async () => {
        if (window.testSourceContext) await testSourceContext.close();
        window.testSourceContext = new AudioContext();
        window.testDestination = testSourceContext.createMediaStreamDestination();
        const silence = testSourceContext.createConstantSource();
        silence.offset.value = 0;
        silence.connect(testDestination);
        silence.start();
        await testSourceContext.resume();
        return testDestination.stream;
      };
    }""")
    assert page.evaluate("() => startMicrophoneCapture()")
    page.evaluate("() => resumeMicrophoneCapture()")
    assert page.evaluate("() => liveAcousticDiagnostics().captureMode") == "AudioWorklet"


def _play_signed_bulletin(page, rev=1):
    """Input goes through MediaStream -> AudioWorklet -> MessagePort -> decoder."""
    sk = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    body = f"Real port bulletin revision {rev}."
    pub, sig = sign_bulletin_content("real-port", rev, hashlib.sha3_256(body.encode()).hexdigest(), sk, title="Port test")
    payload = dict(v=2, id="real-port", rev=rev, title="Port test", body=body, pub=pub, sig=sig)
    page.evaluate("k => addTrustedPublisher(k)", pub)
    rate = page.evaluate("() => liveAcousticDiagnostics().sampleRate")
    wav = AFSKModulator(sample_rate=rate).synthesize_wav(json.dumps(payload).encode())
    page.evaluate("""b64 => {
      const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const {samples, sampleRate} = parseWavSamples(bytes.buffer);
      // An acoustic station repeats a bulletin. Browser audio clocks can
      // start at a different symbol phase, so exercise the repeated broadcast.
      const silence = Math.round(sampleRate * 0.18);
      const buffer = testSourceContext.createBuffer(1, samples.length * 3 + silence * 2, sampleRate);
      const channel = buffer.getChannelData(0);
      for (let repeat = 0; repeat < 3; repeat++) {
        channel.set(samples, repeat * (samples.length + silence));
      }
      const source = testSourceContext.createBufferSource();
      source.buffer = buffer;
      source.connect(testDestination);
      source.start(testSourceContext.currentTime + 0.2);
    }""", base64.b64encode(wav).decode())
    page.wait_for_function("body => document.querySelector('#contentArea .content-body')?.textContent === body", arg=body, timeout=15000)
    assert page.evaluate("() => lastBulletinDecision.verification") == "trusted_publisher"


def test_real_audio_worklet_decodes_signed_bulletin_and_returns_buffers(page):
    _start_real_capture(page)
    _play_signed_bulletin(page)
    diag = page.evaluate("() => liveAcousticDiagnostics()")
    assert diag["callbackCount"] > 32  # More than the entire producer pool.
    assert diag["bufferReuseCount"] > 32
    assert 1 <= diag["workletAllocatedBuffers"] <= 32
    assert diag["maxProcessingTimeMs"] > 0
    assert diag["droppedSamples"] == 0
    assert diag["sampleGapsDetected"] == 0
    assert diag["maxBufferedSamples"] <= 2048 + diag["sampleRate"] // 1000 + 64


def test_real_worklet_pool_exhaustion_reports_drops_and_recovers(page):
    _start_real_capture(page)
    page.evaluate("""() => {
      window.overloadReports = 0;
      activeWorkletNode.port.addEventListener('message', event => {
        if (event.data.type === 'overload_drop') overloadReports++;
      });
    }""")
    page.evaluate("() => activePipelineController.setConsumerBackpressure(true)")
    page.wait_for_function("() => liveAcousticDiagnostics().droppedSamples > 0", timeout=6000)
    page.wait_for_timeout(600)
    diag = page.evaluate("() => liveAcousticDiagnostics()")
    assert 0 < diag["queueDepth"] <= 32
    assert diag["workletAllocatedBuffers"] <= 32
    assert diag["overloadEvents"] > 0
    assert page.evaluate("() => overloadReports") < max(16, diag["droppedBlocks"] // 4)
    page.evaluate("() => activePipelineController.setConsumerBackpressure(false)")
    page.wait_for_function("() => liveAcousticDiagnostics().sampleGapsDetected > 0")
    assert page.evaluate("() => liveAcousticDiagnostics().totalMissedSamples") > 0
    _play_signed_bulletin(page)


def test_actual_ui_stall_is_observed_and_reception_continues(page):
    _start_real_capture(page)
    page.wait_for_function("() => liveAcousticDiagnostics().callbackCount > 3", timeout=5000)
    # No production helper writes its own success counters.
    page.evaluate("() => { const end = performance.now() + 250; while(performance.now() < end) {} }")
    page.wait_for_function("() => liveAcousticDiagnostics().uiStallEvents > 0")
    assert page.evaluate("() => liveAcousticDiagnostics().lastUiStallDurationMs") >= 150
    _play_signed_bulletin(page)


def test_real_worklet_scheduling_delay_and_restart(page):
    # Inject the stall in the processor's own thread, only in the test-served module.
    original = (get_static_assets_dir() / "acoustic_worklet.js").read_text(encoding="utf-8")
    instrumented = original.replace("super();", """super();
      this.port.addEventListener('message', event => {
        if (event.data.type === 'test_busy_wait') {
          const end = Date.now() + 180;
          while (Date.now() < end) {}
        }
      });
      this.port.start();""", 1)
    # AudioWorklet.addModule requests are outside Playwright's page.route.
    # Supply a Blob module through the browser's real addModule operation.
    page.evaluate("""source => {
      const originalAddModule = AudioWorklet.prototype.addModule;
      AudioWorklet.prototype.addModule = function() {
        return originalAddModule.call(this, URL.createObjectURL(new Blob([source], {type:'text/javascript'})));
      };
    }""", instrumented)
    _start_real_capture(page)
    page.wait_for_function("() => liveAcousticDiagnostics().callbackCount > 3", timeout=5000)
    page.evaluate("() => activeWorkletNode.port.postMessage({type: 'test_busy_wait'})")
    page.wait_for_function("() => liveAcousticDiagnostics().workletStallEvents > 0", timeout=4000)
    assert page.evaluate("() => liveAcousticDiagnostics().lastWorkletDelayMs") >= 100
    assert page.evaluate("() => restartMicrophoneCapture()")
    page.evaluate("() => resumeMicrophoneCapture()")
    page.wait_for_function("() => liveAcousticDiagnostics().callbackCount > 3", timeout=5000)
    diag = page.evaluate("() => liveAcousticDiagnostics()")
    assert diag["activePipelineCount"] == 1
    assert diag["tracksReleasedCount"] >= 1
    _play_signed_bulletin(page)
    page.evaluate("() => stopMicrophoneCapture()")
    assert page.evaluate("() => getReceiverReadiness().activePipelineCount") == 0


def test_isolated_controller_bounds_queue_and_discards_partial_frame_on_gap(page):
    # Explicit controller unit test, no claim of live capture.
    result = page.evaluate("""() => {
      const decoder = new IncrementalAFSKReceiver(48000, () => {});
      const c = new BoundedAudioPipelineController(48000, decoder, s => decoder.push(s), {maxQueueSize:32, maxPoolBuffers:32});
      c.setConsumerBackpressure(true);
      for(let i=0;i<40;i++) c.ingestScriptProcessorBlock(new Float32Array(2048));
      const full = c.snapshot();
      c.setConsumerBackpressure(false);
      const h = decoder.hypotheses[0];
      h.state = 3; h.payload = new Uint8Array(8); h.index = 4;
      c.ingestScriptProcessorBlock(new Float32Array(2048));
      return {full, after:c.snapshot(), partialFrameRetained: h.state === 3};
    }""")
    assert result["full"]["queueDepth"] == 32
    assert result["full"]["droppedSamples"] == 8 * 2048
    assert result["after"]["totalMissedSamples"] == 8 * 2048
    assert result["after"]["queueDepth"] == 0
    assert not result["partialFrameRetained"]


def test_overload_log_keeps_recent_events_without_unbounded_dom_growth(page):
    page.evaluate("""() => {
      for (let i = 0; i < 250; i++) logPacket(`Audio overload event ${i}`);
    }""")
    lines = page.locator("#packetFeed .packet-line")
    assert lines.count() <= 100
    assert "Audio overload event 249" in lines.last.inner_text()


def test_partial_worklet_quantum_reports_exact_lost_samples(page):
    result = page.evaluate("""() => {
      const c = new BoundedAudioPipelineController(48000, null, () => {}, {blockSize:2048});
      c.ingestWorkletMessage({type:'overload_drop', droppedBlocks:1, droppedSamples:128});
      return c.snapshot();
    }""")
    assert result["droppedBlocks"] == 1
    assert result["droppedSamples"] == 128


def test_decoder_gap_reset_preserves_symbol_phase_hypotheses(page):
    result = page.evaluate("""() => {
      const decoder = new IncrementalAFSKReceiver(48000, () => {});
      const original = decoder.hypotheses.map(h => h.next);
      decoder.push(new Float32Array(1024));
      decoder.resetAfterGap();
      return {original, after: decoder.hypotheses.map(h => h.next)};
    }""")
    assert len(set(result["original"])) > 1
    assert result["after"] == result["original"]


@pytest.mark.parametrize("gap_type,first_frame", [("frame_jump", 2048), ("missing_input", 1152)])
@pytest.mark.skipif(not shutil.which("node"), reason="Node is needed to run the actual AudioWorklet processor in isolation")
def test_worklet_discards_partial_pcm_when_hardware_frames_jump(gap_type, first_frame):
    worklet_path = get_static_assets_dir() / "acoustic_worklet.js"
    script = """
const fs = require('fs'), vm = require('vm');
const events = [];
global.AudioWorkletProcessor = class { constructor() { this.port = { postMessage: m => events.push(m), onmessage: null }; } };
global.registerProcessor = (_name, klass) => { global.Processor = klass; };
global.sampleRate = 48000;
global.currentFrame = 0;
global.currentTime = 0;
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
const processor = new Processor({processorOptions:{blockSize:2048,maxPoolBuffers:32,maxQueueSize:32}});
function quantum() {
  processor.process([[new Float32Array(128)]]);
  global.currentFrame += 128;
  global.currentTime = global.currentFrame / 48000;
}
for(let i=0;i<8;i++) quantum(); // half a transfer buffer
if(process.argv[2]==='missing_input') {
  processor.process([[]]);
  global.currentFrame += 128;
  global.currentTime = global.currentFrame / 48000;
} else {
  global.currentFrame += 1024; // missing hardware frames
}
for(let i=0;i<8;i++) quantum();
const afterHalf = events.filter(e => e.type === 'audio_block').length;
for(let i=0;i<8;i++) quantum();
const blocks = events.filter(e => e.type === 'audio_block');
process.stdout.write(JSON.stringify({afterHalf, firstFrame:blocks[0]?.frameStart,
  blockCount:blocks.length, gapEvents:events.filter(e => e.type==='sample_gap').length}));
"""
    completed = subprocess.run([shutil.which("node"), "-e", script, str(worklet_path), gap_type], capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    assert result["gapEvents"] == 1
    assert result["afterHalf"] == 0
    assert result["blockCount"] == 1
    assert result["firstFrame"] == first_frame
