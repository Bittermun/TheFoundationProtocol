# Critical review of the device-to-phone proposal

Reviewed September 27, 2026 against `main` at `d53f5f7fbe4de97feeedb09f7b2ce5dd4ab2fea8`. A fast-forward-only pull from origin reported already up to date. The checkout was clean before review. An independent reviewer assessed the proposal in parallel.

**Verdict:** retain the emphasis on actual phones, realistic audio conditions, bounded work, and short useful bulletins. Treat the proposed profile and architecture as hypotheses. Several claimed prerequisites do not exist in the current browser path, and the suggested HTTP onboarding does not enable ordinary remote-phone microphone capture.

## Highest-priority findings

### 1. Solve receiver bootstrap before tuning fountain symbols

`tfp_core_v4/cli.py:628` binds the acoustic receiver server to `127.0.0.1`. Another phone cannot reach that listener over the LAN. Changing the bind address alone would still leave the suggested `http://<ip>:8080` page without the secure context normally required for microphone capture. The phone's localhost exception refers to the phone itself, not the broadcasting Pi.

HTTPS with a trusted certificate, a genuinely preloaded offline receiver, and managed/native deployment are different deployment choices. mDNS supplies discovery, not certificate trust. A service worker must first be registered from a secure context; it is not a first-contact decoder bootstrap for a new phone with no connection. See [getUserMedia requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [W3C secure contexts](https://www.w3.org/TR/secure-contexts/), and [service workers](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API).

Define two separate acceptance cases: an already-prepared phone receiving during an outage, and an unfamiliar phone joining for the first time during that outage. The second is substantially harder. The current receiver does not register a service worker. The offline archive test reloads the page before disconnecting (`tests/test_browser_acoustic_acceptance.py:148`), so it does not prove offline cold launch.

### 2. The architecture diagram combines separate implementations

`tfp-foundation-protocol/tfp_demo/static/acoustic_stream.js` demodulates Bell 202 frames, checks CRC, and emits payload bytes. The HTML decodes those bytes as text/JSON. There is no GF(2) fountain reconstruction stage in this browser path. Browser fountain support would be a new integration, including manifest handling, framing, session limits, reconstruction, and validation.

`tfp_core_v4/profiles.py` does not exist at the reviewed revision. Adding a profile enum in isolation would not connect the current media, acoustic, and browser implementations.

The browser explicitly reports signed bulletins as signature-unverified (`acoustic_receiver.html:419`). Python bulletin verification is a different path. Before presenting received emergency content as authenticated, implement and test browser signature verification plus publisher trust, or preserve the explicit unverified status.

The Python core already has a systematic fast path (`tfp_core_v4/fountain.py:307`). Reusing its behavior in a browser is distinct from inventing it. Concatenating K symbols of T bytes still entails O(KT) byte work; it avoids elimination but is not literally instantaneous.

### 3. Simulation is useful, and the existing simulations are not clean-byte-only

The proposal's categorical claim that physical hardware always invalidates simulation assumptions is too strong. Hardware measurements establish which model assumptions and parameter ranges are adequate. Simulation remains valuable for reproducible regressions, including channel behavior too expensive to reproduce physically every run.

The current channel simulator models noise, reflections, attenuation, and clipping. `test_acoustic_multipath_sweep.py` includes a clock-drift case. These contradict the blanket assertion that the project only feeds clean arrays with no analog impairments.

However, the cited tests do not capture a real microphone: they synthesize WAVs and pass them through `AcousticChannelSimulator`. The operator rehearsal also simulates the audio transmission. Browser acceptance tests substitute microphone/AudioContext behavior and feed synthetic PCM through callbacks. Running them cannot turn them into physical loopback tests.

Use three evidence levels: synthetic impairment tests; real recorded audio replayed through the decoder; live capture on actual phones. An electrical sound-card loopback is also distinct from speaker-to-microphone propagation through a room.

### 4. The packet arithmetic omits a framing layer

There are multiple serializers. The media streamer has a real 40-byte header (`tfp_client/lib/media/fountain_streamer.py:48`). The core `FountainDroplet.serialize()` instead uses a 10-byte prefix plus two bytes per index and the symbol. Choose the wire format before selecting an MTU.

With the existing media header, default acoustic framing adds another 24 bytes: 16 preamble flags, 2 length bytes, 2 CRC bytes, and 4 postamble flags. Measurements below come from synthesizing WAVs with the current modulator at 16 kHz/1200 baud, with no chirp:

| Composition | Complete frame bytes | Synthesized duration |
|---|---:|---:|
| 64-byte symbol + 40-byte media header | 128 | 0.8533125 s |
| 128-byte symbol + 40-byte media header | 192 | 1.2800000 s |
| 512-byte acoustic payload, without a media header | 536 | 3.5733125 s |

An optional chirp and guard add 60 ms. The proposed 104-byte/700 ms calculation counts only the inner packet. A 128-byte on-air MTU fits the first row exactly under these defaults, not the second. Manifest packets, signatures, repair traffic, repetitions, and any inter-frame gaps need separate budgets.

At 1200 bit/s, decimal raw payload lower bounds are 10 s for 1.5 kB, 66.7 s for 10 kB, and 111.1 minutes for 1 MB. The proposal's 12 s, 80 s, and 2.5 hours could be budgets under particular overhead assumptions, but are not direct consequences of the stated bit rate. The current browser/bulletin path caps a wire payload at 4096 bytes, so a 10 kB article already requires segmentation that this path does not supply.

### 5. Smaller symbols are a parameter sweep, not a universal improvement

Smaller frames reduce the amount lost when a short disturbance corrupts a frame, but spend a larger fraction of airtime on headers and synchronization. A long burst can erase several consecutive small frames. More frequent repair packets also consume capacity. Interleaving across blocks, repetition scheduling, late-join manifest frequency, and recovery after a burst matter alongside size.

K is the number of source symbols and normally follows `ceil(chunk_bytes/T)`. With T=64 and chunks from 512 to 2048 bytes, K ranges from 8 to 32; a 1024-byte chunk has K=16. A target K of 32 or 64 is therefore not independent of the proposed chunk boundaries. State whether K is a maximum or a fixed size requiring padding.

FastCDC storage deduplication boundaries and FEC transmission blocks serve different purposes. Avoid changing global chunking merely to obtain a small acoustic block. Compare transport segmentation of existing objects with a profile-specific chunker, and measure the effect on identity, reuse, metadata, and interoperability.

The less-than-2-ms mobile solve target has no benchmark behind it. The current browser runs demodulation and several timing hypotheses through a main-thread ScriptProcessor callback. Measure capture scheduling, demodulation, UI responsiveness, and background/screen-lock behavior before treating matrix solving as the bottleneck. [ScriptProcessorNode is deprecated](https://developer.mozilla.org/en-US/docs/Web/API/ScriptProcessorNode); evaluate an AudioWorklet and worker boundary with measurements rather than assuming WASM alone fixes scheduling.

## Other distinctions the proposal needs

- **Simplex is a deployment constraint, not a universal device property.** A passive acoustic listening session can deliberately have no return channel; phones also have speakers, Wi-Fi, and BLE. BLE and LoRa systems may be bidirectional. Specify whether acknowledgments are unavailable, prohibited, or merely undesirable at broadcast scale.
- **An ordinary phone microphone does not receive arbitrary RF.** A radio speaker can turn an RF broadcast into sound for the phone. A direct LoRa path requires appropriate radio hardware; BLE has different hardware/API and throughput properties. Do not treat their rates and browser support as one channel profile.
- **No Internet, no native installation, no prior preparation, and no infrastructure are different promises.** Serving a portal over local Wi-Fi introduces a local network and a bootstrap service. If that network can carry the content, compare direct Wi-Fi delivery with acoustic delivery and identify why sound is needed.
- **CRC and shared-secret packet tags are not public publisher authentication.** CRC checks errors. A key shared with every receiver permits those receivers to create tags too. A public broadcast needs an explicit publisher trust and anti-pollution design when introducing fountain reconstruction.
- **Compressed speech and text optimize different uses.** A 1200-bit/s voice codec over a 1200-bit/s modem leaves no room for transport overhead in real time. Store-and-forward may still work, but compare intelligibility, time to comprehension, retransmission cost, and ordinary spoken audio. The current browser voice-note button is a simulation; it does not establish decoding of Python's vocoder format.
- **Python fallback is not browser fallback.** Python has 300-baud modes, whereas `IncrementalAFSKReceiver` is hard-coded for 1200 baud. Do not advertise an interoperable fallback until both ends and profile signaling are tested.

## Recommended replacement action plan

1. **Define one concrete deployment.** Example: laptop speaker to previously prepared Android/iOS browsers in the foreground, no data-channel uplink, bounded bulletin size. Separately document the fresh-phone onboarding case and certificate/bootstrap requirements.
2. **Prove bootstrap and trust behavior.** Test fresh load, offline cold reopen, microphone permission, origin security, and explicit signed/unsigned/unverified states on named physical devices. Avoid treating browser development exceptions as a deployment plan.
3. **Obtain a physical baseline using the existing bulletin path.** Prepare a short novel bulletin, play its generated WAV, capture it on a real phone, and compare the result. Keep the raw recording and device/browser/sample-rate/distance/noise settings. Include failures and repeated trials; do not require a new fountain implementation for this first measurement.
4. **Replay physical captures through automated tests.** Add phone handling, speech overlap, clipping, different orientations, and reverberant rooms. Request audio-processing constraints where supported and record effective settings. Measure interruption and resume behavior when capture is suspended.
5. **Sweep packetization with an explicit wire budget.** Compare 64/128/256/512-byte symbols where supported, with and without interleaving, against repeated small complete bulletins. Measure useful verified bytes per second, completion probability, time to first usable bulletin, memory, and battery cost. Include manifest and authentication overhead.
6. **Add browser fountain support only if the measured use case needs it.** Specify manifests, resource caps, supported K/T combinations, authentication, partial-object handling, and test vectors shared with Python. Preserve the simpler bulletin path as a baseline.
7. **Then package a one-command operator workflow.** Reuse `bulletin-prepare`, airtime estimation, existing WAV artifacts, and revision handling. Sound playback, web hosting, trust provisioning, and listener confirmation are separate responsibilities even when coordinated by one command. Broadcast preparation or playback must not claim reception.

## Verification performed

Ran `python -m pytest tests/test_acoustic_multipath_sweep.py tests/test_acoustic_bulletin_verification.py tests/test_browser_acoustic_acceptance.py -q`: **23 passed in 21.07 seconds**, with 791 deprecation warnings under the installed Python 3.14 environment. This is a focused software check, not the whole regression suite or a supported-version matrix.

Also inspected the current receiver, CLI server, bulletin framing, both fountain serializers, and rehearsal implementation; synthesized three WAV sizes to calculate actual duration from their sample counts. The standalone sizing check explicitly added `tfp-foundation-protocol` to its import path, matching the repository's pytest path configuration.

No physical audio trial, ARM benchmark, microphone recording, or battery measurement was performed. No runtime code or dependencies were changed by this review.
