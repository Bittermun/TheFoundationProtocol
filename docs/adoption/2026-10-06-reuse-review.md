# Reuse opportunities — 2026-10-06

Research used Context7, Firecrawl, official documentation/source and disposable local probes. No production code, dependency or service changed. Main is `39e1268`; the optional library adapters remain on `codex/offline-library-adapters`, commit `5486bb9`.

## Ranked opportunities

| Priority | Reuse | Custom work removed | Remaining work | Rough effort |
|---|---|---|---|---|
| 1 | Existing Zstandard dependency, raw-content dictionary | Much binary-delta encoding/decoding | Explicit artifact format/version, bounded decoding, base/target integrity, real-edition and RSS tests | Half–one day benchmark; 2–4 days hardened optional backend |
| 2 | Official Meshtastic Python SDK | Device Serial/TCP framing, protobuf envelopes, binary-data API and ACK plumbing | Licensing decision, TFP mapping, bounded callback queue, payload budget, pacing, reconnect and two-radio tests | 1–2 days proof; 3–7 days adapter with hardware available |
| 3 | Official pyODK client | Central authentication/API and XML/attachment upload plumbing | One pinned form/server, durable outbox, instance-ID duplicate reconciliation, incomplete-attachment recovery | 1–2 days proof; 3–5 days reliable adapter after server provisioning |
| 4 | zsync; casync if its storage model is needed | Ordinary HTTP partial-file/chunk distribution machinery | Separate optional HTTP lane, signed final-file checks, fair baseline measurement | About one day baseline; 2–4 days acquisition adapter |
| 5 | Testcontainers / Linux CI service fixtures | Disposable external-service startup/cleanup | Working Docker daemon, pinned images, actual readiness and behavior tests | 1–2 days simple harness; Central stack setup additional |
| Later | python-tuf | Inventing multi-key authority, root rotation, delegation and rollback workflow | Metadata/repository lifecycle, offline expiry/clock policy, fetcher and schema migration; retain activation journal | Several days prototype; 1–2+ weeks careful integration |

Estimates assume an experienced engineer and readily available fixtures/hardware. They are not measured delivery commitments. Reuse simplifies operations; it does not make reliable end-to-end delivery trivial.

## Local probe: Zstandard is the first experiment to pursue

The installed `zstandard==0.25.0` reconstructed the controlled real-ZIM target byte-for-byte using the full base as `DICT_TYPE_RAWCONTENT`, compression level 3. Target size: **363,989 bytes**. Dictionary-compressed payload: **243 bytes**. Existing CDC patch for the same pair: **83,337 bytes**.

These are artifact payload sizes, excluding signed descriptors, signatures, FM/FD packets, repeats and packet loss. The probe retained base/target bytes in memory and did not measure RSS. It does not establish savings for independently produced historical editions or large archives. Changed compression/layout may reduce reuse significantly.

Zstandard is already a production dependency. Candidate optional-adapter anchors in the separate worktree: `tfp_core_v4/library_updates/prepare.py:11`, `manifest.py:68`, `activation.py:164`. Keep `TFPZIMP1` compatible; identify a new artifact format/schema explicitly, and reject it on unsupported clients. Do not rewrite the shared receiver.

Admission must inspect frame size before allocation, enforce an independent output budget, reject trailing bytes and verify signed base/target size/hash. `max_window_size` uses KiB. Do not assume one-shot `max_output_size` alone bounds every frame with a declared content size. A streamed decoder still needs memory for the base dictionary.

Sources: [dictionary API](https://python-zstandard.readthedocs.io/en/latest/dictionaries.html), [decoder behavior](https://python-zstandard.readthedocs.io/en/latest/decompressor.html).

## Native ZIM tools are not yet a verified shortcut

The already available zim-tools 3.8.0 binaries include `zimdiff` and `zimpatch`. Their help describes incremental updates. In a disposable fixture probe, `zimdiff` returned zero, but `zimpatch` rejected the resulting diff as not matching the base, returned **zero**, and created **no output**. This is evidence about this pinned tool/fixture combination, not every version or input.

A wrapper must check output existence, exact size/hash and real ZIM integrity rather than exit status alone. Diagnose the mismatch before adoption. The successful Zstandard probe is the cheaper next experiment.

Sources: [zimdiff](https://github.com/openzim/zim-tools/blob/main/src/zimdiff.cpp), [zimpatch](https://github.com/openzim/zim-tools/blob/main/src/zimpatch.cpp).

## Code and integration boundaries

**Meshtastic:** Main-checkout `tfp_transport/meshtastic_bridge.py:54` implements custom SLIP; `:423` opens streams; `:445` and `:482` handle broadcast/listen. Stock device interfaces use length-prefixed protobuf envelopes. Let an optional gateway SDK handle that contract; retain TFP payload authentication and airtime pacing. Bridge synchronous/threaded callbacks into asyncio with a bounded queue. Confirm firmware payload limits, private application port/channel behavior, reconnect and actual two-radio exchange. An SDK does not make archive-scale LoRa practical.

Context7 resolved `/meshtastic/python` but supplied no matching documentation for the combined query; official documentation filled the gap. Sources: [binary sendData API](https://python.meshtastic.org/mesh_interface.html), [device framing](https://meshtastic.org/docs/development/device/client-api/).

**ODK:** Proposed next files: `tfp_integrations/odk/submissions.py`, `outbox.py`, a dedicated CLI module and real Central tests. pyODK already exposes `Client.submissions.create(xml, ..., attachments=...)`. Attachment filenames must match the XML. Use an immutable instance ID and Python's SQLite support for the durable outbox; only mark delivered after the server confirms the submission and all required attachments. Handle duplicate IDs, lost upload responses and reconnects. Pin compatible Central/pyODK releases. Keep field-photo privacy separate from public library serving. Do not require ODK Collect on existing phones or build another form designer.

Context7 sources: [submissions](https://getodk.github.io/pyodk/submissions/), [client](https://getodk.github.io/pyodk/client/), [server-version compatibility](https://github.com/getodk/pyodk).

**TUF:** Its Metadata API handles individual metadata objects; ngclient implements the fuller update workflow. Using one signature helper is not implementing that workflow. Offline expiry/clock handling requires design; disabling expiry to make a demo work is not an acceptable shortcut. TUF does not replace reader activation/recovery. Source: [API reference](https://github.com/theupdateframework/python-tuf/blob/develop/docs/api/api-reference.rst).

**HTTP and tests:** [zsync](https://zsync.moria.org.uk/) is an ordinary HTTP distribution baseline; [casync](https://github.com/systemd/casync/blob/main/README.md) adds content-addressed chunk storage. Neither is automatically a substitute for offline broadcast. [Testcontainers](https://github.com/testcontainers/testcontainers-python) can provision disposable service dependencies; it cannot fix an absent Docker daemon or prove physical Pi/IIAB behavior. Keep the existing plain-process Kiwix tests where containers add no benefit.

## Licensing and other factors

TFP declares Apache-2.0. The [Meshtastic SDK](https://github.com/meshtastic/python/blob/master/LICENSE.md) and zim-tools advertise GPL-3.0; [pyODK](https://github.com/getodk/pyodk/blob/master/LICENSE.md) is Apache-2.0; python-tuf offers MIT/Apache-2.0 licensing. Review exact pinned versions and redistribution/combined-work requirements before bundling. A separate gateway/tool is an architectural option, not a blanket licensing guarantee. Content licenses are independent of tool licenses.

Standard artifacts and small runnable interoperability examples reduce the effort others need to evaluate TFP: stock-radio exchange, valid ODK XML, normal Kiwix catalog and installed-wheel examples. They do not guarantee community access or coverage. Existing FastAPI/Prometheus dependencies should supply ordinary schema/metrics before adding another framework. Keep heavy SDKs and services on operators' computers, with no new required phone application or browser assets.

## Recommended order

1. Benchmark Zstandard on independent editions and low-dedup content against the current patcher, including RSS and actual transport overhead.
2. Resolve the Meshtastic SDK licensing approach, then validate an optional stock-radio adapter.
3. Build one pyODK submission/outbox flow when a form and disposable Central server are available.
4. Establish the ordinary HTTP baseline and reproducible service fixtures.
5. Introduce TUF when key rotation/delegation becomes a real requirement.

Authorization, journal ordering, hostile-input bounds, airtime constraints and physical weak-device behavior remain the careful-engineering areas. This research pass added no libraries or product changes, changed no licenses and contacted no external maintainers.
