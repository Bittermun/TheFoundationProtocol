# Device-to-phone acoustic receiver

The `acoustic-receiver` command serves a browser receiver for signed
bulletins carried over audio. The receiver accepts live microphone input and
PCM WAV files.

## Prepared-Phone Scenario

### How the Application Is Obtained

Open `/acoustic_receiver.html` while connected to a trusted HTTPS origin.
For local Android development, USB port forwarding with
`adb reverse tcp:8080 tcp:8080` makes the workstation's receiver available
on the phone's own loopback address.

The service worker installs a release-specific cache with the receiver, audio
engine and worklet, cryptography bundle, and publisher configuration. A failed
install discards the incomplete release. Changing the server's provisioned
keys produces a different release ID. Close old receiver tabs after an online
update, then reopen and check the new release ID and offline readiness.

### How Microphone Access Becomes Available

Live capture requires a secure context and browser microphone permission.
Select **Start Listening** and allow microphone access. The receiver requests
one channel and asks the browser to disable echo cancellation, noise
suppression, and automatic gain control. The readiness panel shows the
negotiated sample rate and DSP settings where available.

### What the User Must Do

While connected, confirm that the receiver reports a secure origin, a ready
offline cache, and the intended publisher keys. Grant microphone permission
and confirm capture starts. After reopening offline, select **Start Listening**
again to start capture.

### How the Publisher Key Becomes Trusted

The server's `/receiver_config.json` can provision known Ed25519 public
keys. The receiver also accepts a verified 64-character hex public key in
**Trusted Publisher Keys**. Provisioning adds to the phone's stored key list.
To revoke a prior key, clear the stored keys, provision the intended keys, and
verify the list before disconnecting.

Signature verification establishes that a message was signed by the
corresponding key. The `trusted_publisher` state and trusted replay
watermarks require a provisioned key.

### What Must Remain Available During the Outage

Offline reopen uses the completed service-worker cache. Trusted publisher keys,
replay watermarks, and received bulletins use browser local storage. Live
capture also requires battery power, a working microphone, permission, and a
browser session that keeps the audio pipeline running.

### Lifecycle Behavior Under Closure, Reboot, Permission Revocation, or Storage Eviction

| Event | Receiver behavior |
| --- | --- |
| Tab closed or phone restarted | A new tab can reopen offline if the installed cache survives. Start listening again to create a new audio session. |
| Audio session interrupted or track ended | Inspect readiness and resume or restart capture when back in the receiver. |
| Microphone permission revoked | Re-enable site permission to resume capture. Stored bulletins can be read while site data is available. |
| Site data cleared or evicted | Cold reopen and local trust state depend on the retained cache and storage. Reload and provision the receiver online after those are cleared. |

## Fresh-Phone Scenario

A phone that has never opened the receiver needs a way to load the web
application. A local HTTP server can supply the app and its scripts for PCM WAV
file import. Live microphone access requires a secure browser context, such as
a trusted HTTPS origin or the phone's own loopback. Provision trusted publisher
keys through a verified channel for either input method.

## Validation scope

Automated Chromium checks exercise MediaStream, AudioWorklet, and the decoder
with synthetic input. Physical-device validation is pending.
