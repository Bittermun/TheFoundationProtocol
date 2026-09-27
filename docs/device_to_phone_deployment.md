# Device-to-Phone Acoustic Broadcast: Supported Deployment & Onboarding Specification

**Document Version:** 1.0 (Phase B Baseline)  
**Target Path:** Laptop or Raspberry Pi $\rightarrow$ loudspeaker, PA, or radio speaker $\rightarrow$ smartphone microphone $\rightarrow$ browser receiver $\rightarrow$ verified bulletin display.

---

## 1. Scenario Separation & Baseline Selection

The Foundation Protocol (TFP) strictly separates two operational scenarios for smartphone browser reception:

1. **Scenario 1 — Prepared-Phone Scenario (Supported Baseline):**
   - The smartphone user loads the acoustic receiver web application from a **secure origin** (`https://` with a valid, trusted certificate, or local device loopback `http://127.0.0.1` / `http://localhost`) *before* internet or network connectivity is lost.
   - Required static assets (`acoustic_receiver.html`, `acoustic_stream.js`, `acoustic_sw.js`) and trusted publisher Ed25519 public keys (`receiver_config.json` or manual key pinning) are cached and provisioned during preparation.
2. **Scenario 2 — Fresh-Phone Scenario (Separate Feasibility Task — Not Claimed Over Sound Alone):**
   - A person arrives during an active outage with an ordinary smartphone browser that has **never** loaded the receiver application.
   - **Hard Constraint:** A browser cannot bootstrap its own HTML/JavaScript execution context over sound alone. Furthermore, serving the page over an ad-hoc local Wi-Fi hotspot via plain `http://<private-ip>:8080` does **not** grant microphone access (`navigator.mediaDevices.getUserMedia`), because W3C Secure Context rules restrict `getUserMedia` to `https://` or the phone's own `localhost` (not a remote laptop/Pi's IP).

**Selected Baseline:** **Scenario 1 (Prepared-Phone Scenario)** is the supported baseline for live microphone reception.

---

## 2. Named Browser & Device Targets

Rather than claiming "works on any phone," this baseline targets the following explicit browser and OS combinations:

| Target Class | Operating System | Supported Browser | Required Web APIs | Notes |
|---|---|---|---|---|
| **Primary Mobile Target A** | Android 11+ | Chrome 113+ / Edge 113+ / Firefox 115+ | `SecureContext`, `ServiceWorker`, `MediaDevices.getUserMedia`, `AudioContext` (`AudioWorklet`), `localStorage`, `SubtleCrypto` | Native `SubtleCrypto` Ed25519 supported in Chrome 113+ / Firefox 129+; deterministic JS Ed25519 + SHA3-256 verifier ensures parity across all listed versions. |
| **Primary Mobile Target B** | iOS / iPadOS 16.4+ | Safari 16.4+ (WebKit) | `SecureContext`, `ServiceWorker`, `MediaDevices.getUserMedia`, `AudioContext` (`AudioWorklet`), `localStorage`, `SubtleCrypto` | Requires explicit user tap to start/resume `AudioContext` after page load or background interruption; aggressive aggressive ITP storage eviction rules apply if unused $>7$ days unless added to Home Screen (PWA). |
| **Desktop / Operator Reference** | Windows 10/11, macOS 13+, Linux (Raspberry Pi OS Bookworm) | Chromium / Chrome 113+, Firefox 115+, Safari 16.4+ | Same as above | Used for broadcaster verification, loopback testing, and local `http://127.0.0.1:8080` testing. |

---

## 3. Prepared-Phone Scenario Specification (Six Mandatory Dimensions)

### 3.1 How the Application Is Obtained
- **While Connectivity Exists (Pre-Outage):**
  1. **Production / Field Preparation:** The user navigates to a HTTPS origin trusted by the phone's OS root store (e.g., `https://broadcast.example.org/acoustic_receiver.html` or an intranet HTTPS endpoint signed by an organization CA already installed in the device trust store).
  2. **Developer / USB-Tethered Preparation:** When preparing a phone directly connected to a workstation via `adb reverse tcp:8080 tcp:8080` (Android), the phone accesses `http://127.0.0.1:8080/acoustic_receiver.html` (which satisfies the phone's own `localhost` secure-context exception).
- Upon initial load, `acoustic_receiver.html` registers `acoustic_sw.js` (Service Worker), which atomically fetches and caches a versioned manifest of required assets (`acoustic_receiver.html`, `acoustic_stream.js`, `receiver_config.json`).
- **Readiness Confirmation:** The receiver UI displays `Offline Cache: Ready (v1)` only after the Service Worker reaches the `activated` state and confirms all assets are cached.

### 3.2 How Microphone Access Becomes Available
- Because the application was loaded from a W3C Secure Context (`window.isSecureContext === true`), `navigator.mediaDevices.getUserMedia` is exposed by the browser.
- When the user taps **Start Listening**, the receiver requests:
  ```javascript
  navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: { ideal: false },
      noiseSuppression: { ideal: false },
      autoGainControl: { ideal: false },
      channelCount: { ideal: 1 }
    },
    video: false
  })
  ```
- Disabling voice-oriented DSP (`echoCancellation`, `noiseSuppression`, `autoGainControl`) prevents the mobile OS from attenuating continuous 1200 Hz / 2200 Hz Bell 202 tones.
- The receiver inspects `MediaStreamTrack.getSettings()` and displays the actual negotiated `sampleRate` and DSP flags in the Readiness View.

### 3.3 What the User Must Do
1. **Before an Outage (Preparation Phase — ~30 seconds):**
   - Open the receiver URL on the phone browser.
   - Verify the Readiness Panel shows:
     - **Origin Security:** `Secure Context`
     - **Offline Assets:** `Cached & Ready for Offline Reopen`
     - **Trusted Publishers:** `Configured (<N> trusted key(s))`
   - Tap **Start Listening** once and grant Microphone Permission when prompted by the browser so the origin's permission state is established.
   - *(Recommended on iOS Safari)*: Tap **Share $\rightarrow$ Add to Home Screen** to protect Service Worker cache storage from 7-day WebKit eviction.
2. **During an Outage (Reception Phase):**
   - Open the browser tab (or Home Screen icon / cached URL) even with Airplane Mode or Wi-Fi/Cellular completely disabled.
   - Tap **Start Listening** (required by mobile browser autoplay/audio-context policies to unlock `AudioContext`).
   - Hold or place the phone within acoustic range of the speaker/PA/radio with the screen in the foreground.

### 3.4 How the Publisher Key Becomes Trusted
- **Strict Separation of Verification and Trust:**
  - Receiving a public key (`pub`) and signature (`sig`) inside an over-the-air bulletin only allows verifying that *the holder of `pub` signed the message* (`valid_signature_unknown_key`). It **never** establishes that `pub` is an authorized emergency broadcaster.
- **Supported Provisioning Mechanisms:**
  1. **Origin Config Provisioning (`/receiver_config.json`):** During the pre-outage preparation load from the trusted HTTPS origin, the receiver fetches `/receiver_config.json` containing the broadcaster's 64-character hex Ed25519 public key(s) and persists them in `localStorage['tfp_trusted_publishers']`.
  2. **Out-of-Band Operator Pinning:** The user pastes or scans a verified 64-hex Ed25519 public key into the Receiver's **Trusted Publisher Keys** configuration panel prior to or during the outage.
- Only bulletins signed by a key present in `tfp_trusted_publishers` achieve the **`trusted_publisher`** state and are permitted to advance authoritative trusted watermarks.

### 3.5 What Must Remain Available During the Outage
- **Device Battery & Audio Hardware:** Functioning smartphone speaker/microphone ADC and battery.
- **Browser Storage & Cache:**
  - Service Worker Cache Storage (`tfp-acoustic-receiver-v1`) holding `acoustic_receiver.html`, `acoustic_stream.js`, and `receiver_config.json`.
  - `localStorage` holding `tfp_trusted_publishers` (trusted Ed25519 public keys), `tfp_bulletin_watermarks` (replay/downgrade watermarks), and `tfp_transmissions` (received bulletin archive).
- **Foreground Execution:** The browser tab must remain in the foreground while actively listening (mobile OSes suspend background tab microphone capture and `AudioContext` threads when the screen locks or another app takes audio focus).

### 3.6 Lifecycle Behavior Under Closure, Reboot, Permission Revocation, or Storage Eviction

| Event | Observed Browser Behavior | Receiver Recovery & User Action |
|---|---|---|
| **Browser Tab Closed or Phone Rebooted (While Offline)** | Memory and `AudioContext` are destroyed; Service Worker and `localStorage` persist on disk. | User reopens the bookmarked URL or Home Screen icon while offline. The Service Worker serves `acoustic_receiver.html` and `acoustic_stream.js` from local cache (`cold reopen`). `localStorage` restores trusted keys, watermarks, and archived bulletins. User taps **Start Listening** to resume. |
| **Screen Lock / Incoming Call / App Switch** | Mobile OS transitions `AudioContext.state` to `suspended` or `interrupted`, or ends the `MediaStreamTrack`. | Receiver detects `onstatechange` / `track.onended`, transitions Readiness status to **`Audio Processing Suspended / Interrupted`**, records a sequence gap in diagnostics, and prompts the user to tap **Resume / Restart Listening** once back in foreground. |
| **Microphone Permission Revoked** | `navigator.mediaDevices.getUserMedia` rejects with `NotAllowedError` (`PermissionDeniedError`). | Receiver transitions Readiness status to **`Permission Denied or Unresolved`** with explicit instructions to re-enable microphone access in browser site settings. Previously archived bulletins remain readable offline. |
| **Browser Storage / Cache Eviction** | If the user manually clears "Site Data & Cached Images/Files" while offline (or iOS evicts non-PWA cache after $>7$ days of inactivity), both Service Worker cache and `localStorage` are wiped. | Cold reopening while offline will fail (`Receiver Assets Unavailable`), and trusted keys/watermarks are lost. The readiness documentation explicitly warns operators to verify offline readiness within 48 hours of an anticipated event or install as a Home Screen PWA. |

---

## 4. Fresh-Phone Scenario (Feasibility & Outage Fallback Analysis)

When an unprepared phone arrives during an outage with zero internet connectivity:

1. **Why Plain HTTP over Local Wi-Fi Fails for Live Microphone Capture:**
   - If the broadcaster runs `python -m tfp_core_v4.cli acoustic-receiver --host 0.0.0.0 --port 8080` on a local Wi-Fi access point (`http://192.168.4.1:8080`), the phone can download `acoustic_receiver.html`.
   - However, because `http://192.168.4.1:8080` is an **insecure origin**, mobile browsers set `window.isSecureContext = false` and `navigator.mediaDevices` is `undefined`. Live microphone capture is blocked by the browser security model.
   - **Rule:** Do not instruct users to bypass TLS certificate warnings (`NET::ERR_CERT_AUTHORITY_INVALID`) or enable `chrome://flags/#unsafely-treat-insecure-origin-as-secure` as a production deployment procedure (moreover, Service Workers still refuse to register on untrusted self-signed certificates even if a user clicks through a warning).

2. **What *Does* Work on an Unprepared Phone Over Local HTTP (Recorded WAV Import Fallback):**
   - If a local Wi-Fi AP serves `acoustic_receiver.html` over plain HTTP (or if `acoustic_receiver.html` is shared peer-to-peer as a standalone file), `<input type="file" accept=".wav,audio/wav">` **does not require `getUserMedia` or a Secure Context**.
   - A fresh phone user can record the acoustic broadcast using the phone's built-in native **Voice Recorder / Voice Memos** app (when saved as or converted to PCM WAV) and load the file into `acoustic_receiver.html` for local demodulation and signature verification.

3. **Requirements for Full Live-Mic Fresh-Phone Onboarding in Outages (Future Feasibility Task):**
   - Requires either:
     - Pre-installed enterprise/community Root CA on participating devices + local DNS/mDNS resolving to the local HTTPS server, **or**
     - An offline-cached public HTTPS domain (where only DNS/IP routing is local via split-horizon DNS for a publicly valid TLS certificate held by the field appliance).
