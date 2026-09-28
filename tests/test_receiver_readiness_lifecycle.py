# SPDX-License-Identifier: Apache-2.0
"""Phase C tests: receiver readiness states, lifecycle handling, and offline cold reopening."""

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


def test_readiness_distinguishes_all_required_states(browser_server):
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    page.wait_for_function("() => window.getReceiverReadiness().offlineAssetsState === 'offline_assets_ready'")

    # 1. Initial state on localhost: secure_context, offline_assets_ready, missing_trusted_publisher, permission_unresolved
    r0 = page.evaluate("() => window.getReceiverReadiness()")
    assert r0["originState"] == "secure_context"
    assert r0["microphoneApiState"] == "available"
    assert r0["offlineAssetsState"] == "offline_assets_ready"
    assert r0["offlineCacheVersion"] == "tfp-acoustic-receiver-v2"
    assert r0["trustedPublisherState"] == "missing_trusted_publisher"
    assert r0["permissionState"] == "permission_unresolved"
    assert r0["primaryState"] == "missing_trusted_publisher"

    # 2. Configure trusted publisher key -> transitions to permission_unresolved
    pub_key = "11" * 32
    page.evaluate("k => window.addTrustedPublisher(k)", pub_key)
    r_trusted = page.evaluate("() => window.getReceiverReadiness()")
    assert r_trusted["trustedPublisherState"] == "trusted_publisher_configured"
    assert r_trusted["trustedPublishers"] == [pub_key]
    assert r_trusted["primaryState"] == "permission_unresolved"

    # 3. Partial cache corruption -> offline_assets_unavailable
    page.evaluate("""async () => {
      const c = await caches.open('tfp-acoustic-receiver-v2');
      await c.delete('./acoustic_stream.js');
      await window.verifyOfflineAssetsCache();
    }""")
    r_partial = page.evaluate("() => window.getReceiverReadiness()")
    assert r_partial["offlineAssetsState"] == "offline_assets_unavailable"
    assert r_partial["primaryState"] == "offline_assets_unavailable"

    # Restore coherent cache
    page.evaluate("""async () => {
      const c = await caches.open('tfp-acoustic-receiver-v2');
      const resp = await fetch('./acoustic_stream.js', {cache: 'no-cache'});
      await c.put('./acoustic_stream.js', resp);
      await window.verifyOfflineAssetsCache();
    }""")
    assert page.evaluate("() => window.getReceiverReadiness().offlineAssetsState") == "offline_assets_ready"

    # 4. Permission denied
    page.evaluate("""() => {
      navigator.mediaDevices.getUserMedia = async () => {
        const err = new Error('Permission dismissed or denied by user');
        err.name = 'NotAllowedError';
        throw err;
      };
    }""")
    page.click("#listenBtn")
    r_denied = page.evaluate("() => window.getReceiverReadiness()")
    assert r_denied["permissionState"] == "permission_denied"
    assert r_denied["primaryState"] == "permission_denied"
    assert "Permission Denied" in page.locator("#readinessPermission").inner_text()

    # 5. Missing audio input
    page.evaluate("""() => {
      readinessState.permissionState = 'permission_unresolved';
      navigator.mediaDevices.getUserMedia = async () => {
        const err = new Error('Requested device not found');
        err.name = 'NotFoundError';
        throw err;
      };
    }""")
    page.click("#listenBtn")
    r_no_input = page.evaluate("() => window.getReceiverReadiness()")
    assert r_no_input["audioInputState"] == "missing_audio_input"
    assert r_no_input["primaryState"] == "missing_audio_input"
    assert "Missing or Unavailable Input" in page.locator("#readinessAudioInput").inner_text()

    # 6. Missing microphone API
    page.evaluate("""() => {
      window._origMediaDevices = navigator.mediaDevices;
      Object.defineProperty(navigator, 'mediaDevices', {value: undefined, configurable: true});
    }""")
    r_no_api = page.evaluate("() => window.getReceiverReadiness()")
    assert r_no_api["microphoneApiState"] == "missing_microphone_api"
    assert r_no_api["primaryState"] == "missing_microphone_api"
    page.evaluate("""() => {
      Object.defineProperty(navigator, 'mediaDevices', {value: window._origMediaDevices, configurable: true});
    }""")

    # 7. Insecure origin
    page.evaluate("() => { window.__tfpTestForceInsecureOrigin = true; }")
    r_insecure = page.evaluate("() => window.getReceiverReadiness()")
    assert r_insecure["originState"] == "insecure_origin"
    assert r_insecure["primaryState"] == "insecure_origin"
    assert "Insecure Origin" in page.locator("#readinessOrigin").inner_text()
    page.evaluate("() => { window.__tfpTestForceInsecureOrigin = false; }")

    context.close()


def test_capture_lifecycle_settings_interruption_and_no_duplicate_pipelines(browser_server):
    browser, url = browser_server
    context = browser.new_context()
    page = context.new_page()
    page.goto(url)
    page.wait_for_function("() => window.getReceiverReadiness().offlineAssetsState === 'offline_assets_ready'")

    page.evaluate("""() => {
      window.capturedConstraints = [];
      window.AudioContext = class {
        constructor() {
          this.sampleRate = 48000;
          this.state = 'running';
          this.destination = {};
        }
        createMediaStreamSource() { return {connect() {}, disconnect() {}}; }
        createAnalyser() { return {frequencyBinCount: 256, getByteTimeDomainData(a) {a.fill(128);}, disconnect() {}}; }
        createScriptProcessor() {
          window.testProcessor = {connect() {}, disconnect() {}};
          return window.testProcessor;
        }
        async resume() { this.state = 'running'; }
        async close() { this.state = 'closed'; }
      };
      navigator.mediaDevices.getUserMedia = async (constraints) => {
        window.capturedConstraints.push(constraints);
        await new Promise(r => setTimeout(r, 30));
        return {
          getAudioTracks: () => [{
            stop() {},
            getSettings: () => ({
              sampleRate: 48000,
              channelCount: 1,
              echoCancellation: false,
              noiseSuppression: false,
              autoGainControl: false
            })
          }]
        };
      };
    }""")

    # Trigger two concurrent starts to verify mutex prevents duplicate pipelines
    results = page.evaluate("() => Promise.all([window.startMicrophoneCapture(), window.startMicrophoneCapture()])")
    assert results == [True, False]

    r_active = page.evaluate("() => window.getReceiverReadiness()")
    assert r_active["captureLifecycleState"] == "capture_active"
    assert r_active["primaryState"] == "capture_active"
    assert r_active["actualSampleRate"] == 48000
    assert r_active["activePipelineCount"] == 1
    assert r_active["effectiveCaptureSettings"] == {
        "sampleRate": 48000,
        "trackSampleRate": 48000,
        "channelCount": 1,
        "echoCancellation": False,
        "noiseSuppression": False,
        "autoGainControl": False,
    }
    assert "48000 Hz | ch=1 | AEC=false | NS=false | AGC=false" in page.locator("#readinessCaptureSettings").inner_text()

    # Verify requested constraints disabled voice DSP filters
    constraints = page.evaluate("() => window.capturedConstraints[0]")
    assert constraints["audio"]["echoCancellation"] == {"ideal": False}
    assert constraints["audio"]["noiseSuppression"] == {"ideal": False}
    assert constraints["audio"]["autoGainControl"] == {"ideal": False}

    # Simulate audio interruption / suspension and resume
    page.evaluate("() => window.simulateAudioInterruption('suspended')")
    r_susp = page.evaluate("() => window.getReceiverReadiness()")
    assert r_susp["captureLifecycleState"] == "audio_suspended_or_interrupted"
    assert r_susp["primaryState"] == "audio_suspended_or_interrupted"
    assert "Audio Suspended" in page.locator("#readinessCaptureState").inner_text()

    page.evaluate("() => window.resumeMicrophoneCapture()")
    r_resumed = page.evaluate("() => window.getReceiverReadiness()")
    assert r_resumed["captureLifecycleState"] == "capture_active"

    # Restart capture -> must release old track and keep activePipelineCount == 1
    page.evaluate("() => window.restartMicrophoneCapture()")
    r_restarted = page.evaluate("() => window.getReceiverReadiness()")
    assert r_restarted["activePipelineCount"] == 1
    assert r_restarted["tracksReleasedCount"] == 1

    # Stop capture -> releases track and sets activePipelineCount == 0
    page.evaluate("() => window.stopMicrophoneCapture()")
    r_stopped = page.evaluate("() => window.getReceiverReadiness()")
    assert r_stopped["captureLifecycleState"] == "stopped"
    assert r_stopped["activePipelineCount"] == 0
    assert r_stopped["tracksReleasedCount"] == 2

    context.close()


def test_offline_cold_reopen_with_networking_disabled_before_navigation(browser_server):
    """
    Phase C requirement:
    Test offline cold reopening with networking disabled BEFORE navigation or reopening.
    (Distinct from loading a page online and then disconnecting.)
    """
    browser, url = browser_server
    context = browser.new_context()

    # 1. Prepared-phone initial online load: cache assets & provision trusted key + archive item
    prep_page = context.new_page()
    prep_page.goto(url)
    prep_page.wait_for_function("() => window.getReceiverReadiness().offlineAssetsState === 'offline_assets_ready'")
    prep_page.evaluate("k => window.addTrustedPublisher(k)", "22" * 32)
    prep_page.close()

    # 2. Disable networking BEFORE opening a new page and navigating (true cold reopen)
    context.set_offline(True)
    cold_page = context.new_page()
    cold_page.goto(url, wait_until="domcontentloaded")
    cold_page.wait_for_selector("#readinessCard")

    readiness = cold_page.evaluate("() => window.getReceiverReadiness()")
    assert readiness["offlineAssetsState"] == "offline_assets_ready"
    assert readiness["trustedPublisherState"] == "trusted_publisher_configured"
    assert readiness["trustedPublishers"] == ["22" * 32]

    # 3. Verify the cold-opened offline receiver demodulates a novel WAV bulletin
    bulletin = {
        "v": 2,
        "id": "COLD-OFFLINE-BULLETIN-01",
        "rev": 1,
        "title": "Cold Offline Reopen Verified",
        "body": "Receiver loaded from Service Worker cache with network disabled before navigation.",
        "pub": None,
        "sig": None,
    }
    wav = AFSKModulator().synthesize_wav(json.dumps(bulletin).encode("utf-8"))
    res = cold_page.evaluate(
        "b64 => window.decodeAcousticWav(b64)",
        base64.b64encode(wav).decode("ascii"),
    )
    assert res["count"] == 1
    assert bulletin["body"] in cold_page.locator("#contentArea .content-body").inner_text()

    context.close()
