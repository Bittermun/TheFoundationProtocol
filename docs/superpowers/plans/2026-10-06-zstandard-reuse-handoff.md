# Optional Zstandard Delta Adapter Implementation Plan

> **For the coding AI:** This document is a self-contained implementation brief. Execute the primary tasks in order. If available, use `superpowers:executing-plans`; otherwise follow the equivalent test-first workflow below. The later integration briefs are separate projects, not instructions to implement everything together.

**Goal:** Reuse the project's existing Zstandard dependency to provide a bounded, explicitly selected archive-delta backend, while preserving existing patch formats, authentication, recovery and poor-phone operation.

**Architecture:** Add an operator-only codec and a signed descriptor version identifying it. Reuse the existing FM/FD artifact transport and Kiwix activation journal. Keep CDC as the default; add explicit `zstd` and experimental `auto` selection.

**Tech Stack:** Python 3.11+, installed `zstandard`, existing Ed25519/SHA3 utilities, existing FM/FD receiver, real Kiwix/openZIM tooling, pytest, Ruff, Mypy and Bandit.

**Spec:** This document's decisions and acceptance criteria are the executable specification. Context and sources are in `docs/adoption/2026-10-06-reuse-review.md` in the main checkout. Do not interpret earlier planning documents' unchecked boxes as authorization to implement unrelated integrations.

## 1. Repository state and authorization

The Windows main checkout is `C:/Users/msunw/Downloads/TheFoundationProtocol`. At planning time it is on `main`, commit `39e1268`. The existing library adapter implementation is in:

`C:/Users/msunw/.codex/worktrees/offline-library-adapters/TheFoundationProtocol`

Branch: `codex/offline-library-adapters`; implementation commit: `5486bb9`.

**Do not start from main and accidentally rebuild the previous adapter.** Run `git status --short`, `git log -3 --oneline` and `git worktree list`. Verify the implementation commit is available. Prefer a fresh isolated branch `codex/zstd-library-adapter` based on the existing adapter branch. Reuse an appropriate clean worktree if the host manages worktrees. Do not discard, reset, overwrite or merge unrelated work. If the adapter commit is absent, locate it before coding; explain a genuinely unavailable prerequisite instead of substituting a different starting point.

For an AI without that local branch, the user can supply the companion `prerequisite-offline-library-adapters.patch`. It is a binary-capable diff from main `39e1268` to the adapter implementation `5486bb9`, excluding only the generated graph snapshot. It was checked with `git apply --check` against main. Apply it only in an isolated compatible checkout, after another successful `git apply --check`; regenerate the AST snapshot and run the gate before committing the prerequisite import. Do not force a patch whose context fails. This is a source handoff, not proof that tooling/runtime binaries are installed. Local companion path: `C:/Users/msunw/Downloads/TheFoundationProtocol/.dist_verify/ai-handoff/prerequisite-offline-library-adapters.patch`.

The user wants the coding AI to make ordinary implementation decisions. Proceed through the primary plan without repeated preference questions. Keep meaningful progress updates. External publication, upstream contacts, service installation, project relicensing and unrelated feature implementation are outside this brief. Preserve the local branch for review at completion; do not merge or push automatically.

Windows runtime: `.dist_verify/runtime/Scripts/python.exe`. If missing, use the repository's `scripts/agent/bootstrap_env.ps1`. Do not rely on the Windows Store `python` alias. Read applicable `AGENTS.md`. Query `scripts/code_graph.py --query SYMBOL` before broad searches, then follow exact definitions/callers/tests. Re-query all line anchors below in the actual execution checkout.

## 2. Evidence and limits

A disposable probe using `zstandard==0.25.0`, compression level 3 and the previous archive as `DICT_TYPE_RAWCONTENT` reconstructed our controlled real-ZIM target exactly. Target: 363,989 bytes; Zstandard payload: 243 bytes; current CDC patch: 83,337 bytes. These exclude descriptor/signature/transport bytes. The probe loaded whole files and did not measure RSS. Do not advertise those savings as representative.

Pinned zim-tools 3.8.0 `zimpatch` rejected its own generated diff for this fixture, returned zero and created no output. Do not replace our patcher with those tools merely because their commands exist. Never equate exit status with reconstructed-file validity.

Global constraints:

- Existing adapter caps stay: archives 64 MiB; artifact 16 MiB; descriptor 4 KiB; existing receiver one session/256 chunks of 64 KiB.
- New Zstandard backend base-dictionary cap: **16 MiB**. Target cap: **64 MiB**. Artifact cap: **16 MiB**. Decoder-window cap: **16 MiB**, expressed to `max_window_size` as **16,384 KiB**. These additional caps apply only to this backend.
- Maximum measured individual operator process-tree RSS: **256 MiB**, including launcher children. Bound source/output sizes before allocation. One-shot processing is acceptable within these caps if real subprocess memory tests pass; do not claim constant-memory or large-archive support.
- Existing CDC behavior, `TFPZIMP1`, schema-v1 packages, normal CLI commands, browser assets, acoustic paths and shared receiver defaults remain compatible.
- No new required phone software, JavaScript, WebAssembly, archive reconstruction, SDK or dependency. Operator-side codecs remain optional paths.
- Do not add a production dependency: Zstandard is already present. Verify supported installed-library APIs and project version floor; test the minimum supported version as well as the pinned evidence environment if practical. If an API is unavailable at the floor, provide a compatible implementation or explicitly document a narrowly justified version-floor change; do not silently upgrade everything.
- Digest/secret comparisons use `hmac.compare_digest`; keys/IDs use `secrets`/`os.urandom`; network/subprocess calls have deadlines; asynchronous tasks retain references and handle exceptions; no production mocks.
- Preserve locally pinned publisher keys, signatures, signed exact base/target hashes, monotonically accepted revisions, exclusive output installation and old-library recovery.
- Keep the dedicated adapter catalog. Do not modify IIAB's existing catalog/services or delete old archives.

## 3. File and interface map

All anchors refer to the existing adapter worktree and must be refreshed before execution.

| File | Intended change |
|---|---|
| New `tfp_core_v4/library_updates/zstd_delta.py` | Bounded codec; no transport, trust policy or catalog management |
| `tfp_core_v4/library_updates/manifest.py:47,68` | Backward-compatible schema-v2 admission and fixed artifact naming |
| `tfp_core_v4/library_updates/prepare.py:11` | Backend candidates, explicit selection, verified package creation |
| `tfp_core_v4/library_updates/activation.py:164` | Codec dispatch after existing authorization/base checks |
| `tfp_core_v4/library_updates/cli.py:11,43` | `--delta-backend` on `library-prepare` only |
| `scripts/verify_library_update.py` | Use verified artifact naming; support tiny and multi-chunk proof scenarios |
| New `scripts/benchmark_library_delta.py` | Measured, comparable candidate/artifact/package/RSS report |
| New `tests/test_library_zstd_delta.py` | Codec admission and byte-exact behavior |
| Existing `tests/test_library_update_manifest.py`, `test_library_update_cli.py`, `test_library_update_activation.py` | New schema/selection/activation behavior and compatibility |
| `tests/library_update_support.py` | Additional real-ZIM multi-chunk fixture generation without changing existing fixture behavior |
| New `tests/test_library_delta_benchmark.py` | Report arithmetic, real subprocess outcomes, failure reporting |
| `docs/offline_library_pilot.md`, `docs/library_update_results.md`, optional Linux workflow | Usage, real evidence, limitations and new integration coverage |

Do not refactor `tfp_core_v4/zim_sync.py`, the shared receiver, radio bridge or phone application for this feature.

## 4. Review focus

1. A tiny compressed input can declare an enormous output/window: reject before decompression allocation.
2. A different base can yield an apparently valid decoded stream: require both exact base and target integrity.
3. Extra frames/trailing bytes can be silently accepted by library defaults: require exactly one complete frame.
4. A 243-byte artifact finishes in one chunk: do not manufacture a restart claim from the existing multi-chunk harness.
5. New dataclass fields can silently change old signed JSON: preserve schema-v1 canonical bytes and duplicate acceptance.

Each item has explicit tests in the tasks below.

## Task 1 — Establish baseline and benchmark evidence

Deliverable: a reproducible benchmark script and report before changing signed formats.

- [ ] Query `prepare_update`, `verify_descriptor`, `activate_package`, `receive_artifact`, `ZimDeltaEngine.create_patch` and `ZimDeltaEngine.apply_patch`; run their covered tests and the existing adapter tests.
- [ ] Add `scripts/benchmark_library_delta.py` with CLI `--base PATH --target PATH --out REPORT.json --python PATH`. Use separate measured subprocesses for CDC, Zstandard and full-file baselines. Generate/copy input fixtures outside measured children. Apply each candidate and independently stream-hash reconstruction.
- [ ] Initially the Zstandard worker may use the small direct-library research probe. After Task 2, make it call the public codec functions; do not retain a second authoritative encoder/decoder in the benchmark. A full-file baseline here measures local artifact size/copy/RSS, not impaired-link HTTP efficiency.
- [ ] Define report schema version 1: source commit/dirty state, Python/library/tool versions, input hashes/sizes/license provenance, backend, artifact bytes, descriptor/signature/package bytes when available, elapsed encode/decode time, sampled process-tree RSS, reconstructed hash, status and explicit failure reason. Raw-payload and complete-package measurements must have distinct fields.
- [ ] Test report size arithmetic, subprocess nonzero/no-output failure reporting, and reconstruction mismatch. Never record private/transport keys.
- [ ] Test three controlled pairs: existing real ZIM, mostly changed/incompressible content, and dictionary-limit boundary. Attempt a independently produced historical ZIM pair with documented provenance if download/time budgets permit; mark unavailable if not obtained. Do not replace that claim with random bytes.
- [ ] Run the known 243-byte probe as an observation, not a brittle cross-version size assertion. Required assertion is byte equality/digest equality. Report actual size.
- [ ] Set subprocess timeout 120 seconds per bounded case and report timeouts cleanly. Sample RSS with optional test/benchmark `psutil`, never as a new production requirement.
- [ ] Stop codec advancement if reconstruction fails or RSS exceeds 256 MiB. Diagnose the cause; adjust implementation/window strategy within declared caps rather than increasing limits to hide it.

## Task 2 — Implement the bounded standalone codec

Create frozen `ZstdDeltaInfo` with `base_sha3: str`, `target_sha3: str`, `target_size: int`, `artifact_sha3: str`, `artifact_size: int`.

Interfaces in `zstd_delta.py`:

```python
def create_zstd_delta(base: Path, target: Path, output: Path) -> ZstdDeltaInfo: ...
def apply_zstd_delta(base: Path, artifact: Path, output: Path, *,
                     base_sha3: str, target_sha3: str, target_size: int) -> None: ...
```

- [ ] Write failing `test_zstd_roundtrip_is_byte_exact`, `test_wrong_base_retains_existing_files`, `test_existing_output_not_overwritten`, `test_oversized_dictionary_rejected_before_read`, and `test_input_output_alias_rejected`.
- [ ] Run those tests and observe the intended failures before implementation.
- [ ] Use raw-content dictionary mode and compression level 3. Encode exactly one ordinary Zstandard frame with known content size and content checksum. Require a compression window no greater than 16 MiB using the supported library parameters. Return hashes computed from the actual bytes used, not a later unrelated reread.
- [ ] Reuse bounded reads and `new_output`/collision checks. Reject nonregular/symlink leaves, empty inputs and limits before loading data. Never overwrite input, existing output or accepted archives. Remove temporary outputs on failure.
- [ ] Before decoding, bound artifact/base bytes, parse frame parameters, require declared content size exactly equal to signed `target_size` and no greater than 64 MiB, require window at most 16 MiB, checksum present, and dictionary-ID semantics compatible with this raw-content format. Reject unknown-size and skippable-frame formats.
- [ ] Decode with the admitted dictionary/window/output policy; explicitly reject extra data/concatenated frames using supported library behavior. Do not rely solely on `max_output_size` when a frame supplies its own declared size. Verify final size and SHA3 before exclusive output installation.
- [ ] Add failing tests for wrong target hash, truncated header/body/checksum, forged excessive content size, oversized window, absent content size, absent checksum, corrupt payload, appended garbage and a second valid frame. For bomb tests, use a small crafted header, not an enormous allocated fixture.
- [ ] Run codec tests plus fresh subprocess memory tests at 16 MiB base/64 MiB target boundary. Record RSS for both encode and decode. No leaked partial output is allowed.

## Task 3 — Add signed schema v2 without changing v1

Keep all existing common fields and strict type/duplicate-key/canonical validation. Append optional in-memory dataclass fields `schema_version: int = 1` and `patch_format: str | None = None` without breaking current positional construction.

- [ ] `VerifiedUpdate.body()` for v1 must omit `patch_format`, retain `schema_version: 1`, and serialize exactly as before. Add a checked-in v1 descriptor/signature compatibility test using a fixed test-only key. Require canonical byte identity, successful verification and unchanged exact-duplicate behavior.
- [ ] V2 adds one signed field `patch_format`. Support only `(artifact_kind='delta', patch_format='zstd-rawdict-v1')` and `(artifact_kind='full', patch_format='none')` for this release. Other combinations/versions fail closed. Existing v1 delta means `tfpzimp1`; v1 full means `none`.
- [ ] Add `VerifiedUpdate.format_name` property exposing the normalized codec identifier. Fixed artifact names: old CDC `artifact.tfp`; Zstandard `artifact.zst`; full archive `artifact.zim`. No manifest-supplied filename/path.
- [ ] Descriptor parser must use explicit allowed field sets for each version rather than assuming every new dataclass field belongs in v1. Continue validating the legacy `chunker_params` compatibility field; Zstandard does not use it as decoder configuration.
- [ ] Test format/version tampering invalidates signatures, unknown/missing/extra fields fail, v1 with added format fails, unsupported v2 formats fail, wrong publisher/library/base/revision fails, and equal-conflicting descriptors cannot activate.
- [ ] All v1 manifest/CLI tests must pass unchanged. An old client rejecting v2 is expected; never disguise v2 as v1.

## Task 4 — Add explicit preparation and selection

Extend only the existing preparation interface:

```python
def prepare_update(base: Path, target: Path, output_dir: Path,
                   library_id: str, revision: int, signing_key: Path,
                   *, delta_backend: str = 'cdc') -> Path: ...
```

- [ ] Add `library-prepare --delta-backend {cdc,zstd,auto}` with default **cdc**. No changes to send/receive flags, transport wire or endpoint exposure.
- [ ] `cdc`: preserve current v1 preparation and fallback. `zstd`: try only the Zstandard delta; reject an oversized dictionary explicitly. `auto`: compare eligible CDC and Zstandard candidates; skip Zstandard with a recorded reason when its base exceeds 16 MiB.
- [ ] A delta is eligible only if artifact is at most 16 MiB and at most 80% of full target bytes, retaining the current integer threshold `artifact_size * 5 <= target_size * 4`. If none is eligible, use an existing v1 full package only when target fits 16 MiB; otherwise fail cleanly.
- [ ] In auto mode rank eligible candidates by artifact + actual canonical descriptor + 64-byte signature size. Break exact ties in favor of CDC for compatibility. Report skipped candidates/reasons in benchmark JSON and operator diagnostics; do not add unsigned package sidecars as an authority source. Do not silently fall back after integrity, signature or malformed-input failures; only declared size/economics ineligibility is a normal fallback.
- [ ] Sign v2 only when selecting the new delta. Sign ordinary CDC/full as existing v1. Reconstruct the new candidate locally before publishing the package and verify exact target hash/size.
- [ ] Bind signed hashes to bytes actually encoded. Detect input changes between candidate creation and signing by comparing captured hashes with current inputs; fail without a package rather than signing mismatched metadata. Test an input changing during preparation.
- [ ] Preserve staged/exclusive output-directory installation and clean failures. Test zstd selected for similar content, full fallback for low reuse, auto choosing CDC when zstd is ineligible, no eligible artifact failure, threshold boundary and existing output-directory refusal.
- [ ] Add CLI subprocess tests: old help/commands work, explicit backend works, invalid backend exits nonzero and no broken package is left.

## Task 5 — Integrate with real activation and opaque delivery

- [ ] In `activation.py:185`, dispatch normalized format after the existing verified-descriptor/artifact and accepted-base checks: `tfpzimp1` -> existing engine; `zstd-rawdict-v1` -> new codec with signed hashes/size; `none` -> existing full copy. Unknown format fails before catalog changes.
- [ ] Keep lock, disk checks, target naming, zimcheck, ownership/mode preservation, journal, real reader probe, accepted-state commit and external-edit guards intact. No alternate activation shortcut.
- [ ] Parameterize real Kiwix tests across CDC and new delta where meaningful. Assert actual changed-page contents; digest-only success is insufficient.
- [ ] Exercise corrupt/truncated new artifacts, wrong base, stale/equal-conflicting revision, competing updater, failed reader rollback, external catalog edit and abrupt process death after catalog switch. Old accepted content/state must remain intact or recover through the existing journal rules.
- [ ] FM/FD carries opaque artifact bytes: reuse existing send/receive implementation. Do not add codec-specific network packets or shared-receiver branches.
- [ ] Update verification-script artifact naming through a verified `VerifiedUpdate.artifact_name`; remove duplicated hardcoded delta/full filename logic. Do not obtain output paths from raw descriptor JSON.

## Task 6 — Prove both tiny delivery and real restart

The original 243-byte artifact is one chunk. The existing script kills a receiver after a completed chunk and requires an unfinished transfer. It therefore cannot legitimately prove that tiny artifact's restart behavior.

- [ ] Add verification CLI `--scenario {delivery,restart}` with default `restart` to preserve existing invocation behavior. Both scenarios use verified artifact naming and genuine separate processes. Their report values must identify the selected scenario.
- [ ] Tiny case: separate installed-wheel sender/receiver processes, real seeded 30% loss, independent hash and real Kiwix changed-page activation. Report `restart_count=0`; do not claim restart.
- [ ] Multi-chunk case: extend `create_zim` support with optional `changed_asset_bytes=0`, leaving default behavior unchanged. Generate an additional original CC0 asset of 150 KiB using deterministic, revision-dependent SHAKE bytes in each edition. Require actual chosen new delta greater than 64 KiB and target/dictionary within caps. Do not pad the encoded artifact to force more chunks.
- [ ] With that real ZIM pair, stop the receiver process tree after one persisted completed chunk, restart with the same keys/checkpoint namespace, finish through real UDP loss and activate/read the changed page. Assert the pre-restart checkpoint remains useful. Test changed-key context cannot reuse incompatible checkpoints using existing receiver coverage.
- [ ] Build/install a fresh wheel into a separate environment. Child commands use `-I` and unrelated working directory. Report the imported module path to prove installation rather than checkout imports. Include the optional library extra for hardened XML parsing.
- [ ] Preserve the Windows loss-proxy pause/recreation across process restart and process-tree cleanup. Use a fresh test catalog/state for each activation proof; duplicate activation does not substitute for first activation.
- [ ] Record artifact/package/wire bytes, rounds/pacing/loss assumptions, time, full process-tree RSS, tool versions and stage outcomes. Correctly distinguish raw artifact savings from total link cost.

## Task 7 — Final verification, documentation and handoff

- [ ] Refresh `CODE_GRAPH_SNAPSHOT.json` after symbol changes. Redirect `code_graph.py --json` explicitly to the file; the command prints JSON and does not itself save the snapshot. Do not print the enormous snapshot into the chat. Ensure scratch environments remain excluded.
- [ ] Run focused and graph-covered tests, then full pytest on the final source tree. Do not fabricate counts from a preceding commit or silently retry random failures. Diagnose any failure and preserve reproducible fixtures/assertions.
- [ ] Run the mandatory repository gate and explicit checks for the root-level new code:

```powershell
.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_library_zstd_delta.py tests/test_library_update_manifest.py tests/test_library_update_cli.py tests/test_library_update_delivery.py tests/test_library_update_activation.py tests/test_library_delta_benchmark.py -q --tb=short
.\.dist_verify\runtime\Scripts\python.exe -m ruff check tfp_core_v4/library_updates scripts/benchmark_library_delta.py scripts/verify_library_update.py --select E4,E7,E9,F
.\.dist_verify\runtime\Scripts\python.exe -m mypy tfp_core_v4/library_updates --ignore-missing-imports
.\.dist_verify\runtime\Scripts\python.exe -m bandit -c bandit.ini -r tfp_core_v4/library_updates -ll
.\.dist_verify\runtime\Scripts\python.exe -m pytest -q --tb=short
powershell -ExecutionPolicy Bypass -File scripts/agent/run_agent_gate.ps1
```

- [ ] Run real-tool Linux CI coverage if available; mark physical Pi/IIAB/weak-phone trials unavailable until performed. Do not equate supplied workflow YAML with a successful workflow run.
- [ ] Update operator documentation with backend choices, v1/v2 compatibility, dictionary/window caps, failure/fallback behavior, measured outcomes and installation/recovery commands. Preserve historic results and add a clearly dated new section.
- [ ] Inspect `git diff`: no added phone assets/dependencies, changed receiver defaults, unrelated radio changes, private keys, generated sidecars or ignored tool binaries included. Run `git diff --check`.
- [ ] Obtain an independent final code review if supported and authorized by the execution workflow. Address concrete findings with meaningful tests. Commit only after gates/checks pass; preserve branch/worktree and report commit, files, test counts, measured results and unverified claims.

Primary work is complete only when both v1 and v2 behavior pass, hostile codec inputs fail without installed partial output, real Kiwix reads the new page, installed-wheel tiny/restart proofs pass, and resource caps pass. Historical edition/hardware/platform evidence may remain unavailable, but must be explicitly distinguished from software checks and must not support adoption claims.

## 5. Separate follow-up projects

These are follow-up briefs for another run. Do not start them while the primary adapter is unfinished.

### A. Stock Meshtastic SDK adapter

Re-query main `tfp_transport/meshtastic_bridge.py:54,423,445,482`. The current custom SLIP framing is not stock Meshtastic's device protobuf framing. Official SDK source/license is GPL-3.0 while TFP declares Apache-2.0. Establish an acceptable redistribution/combined-work design before importing or bundling the SDK. A separately provisioned gateway is an option, not a blanket licensing exemption.

Preferred boundaries: a separate `tfp_integrations/meshtastic_gateway/` operator package with bounded queues and a local IPC contract for opaque authenticated TFP payloads; retain existing simulation codec and transport tests. Let official SerialInterface/TCPInterface handle the device envelope. Use configured private application port, channel/hop values, real firmware payload ceiling and existing airtime pacing. Handle bounded callback delivery, ACK/NAK, reconnect and orderly shutdown. Pin SDK/firmware versions and test two physical stock radios. No archive-scale LoRa or default phone SDK. Estimate: 3–7 engineering days after licensing/hardware prerequisites.

### B. One-form ODK delivery adapter

Create `tfp_integrations/odk/submissions.py`, `outbox.py`, a dedicated CLI and real Central integration tests. Use official Apache-2.0 pyODK `Client.submissions.create(xml, attachments=...)`; keep matching attachment names and a pinned form/server/client version. Existing SQLite can store immutable instance ID, payload/attachment hashes, submission state, retry schedule and last error. Never mark complete until the server confirms the instance and required attachments. Reconcile duplicates after ambiguous network responses; do not blindly generate new IDs. Test expired credentials, bad form, response loss after server commit, disconnect between XML and attachment upload, already-existing same content and conflicting duplicate IDs. Keep operator credentials/private field data separate from public Kiwix content. No new form designer or mandatory phone application. Estimate: 3–5 engineering days after provisioning.

### C. Ordinary HTTP baseline and reproducible services

Use zsync or an ordinary resumable HTTP acquisition path as a separate operator lane. Verify exact final signed artifact; do not replace broadcast with HTTP. Compare complete bytes under a defined loss/restart model and report baseline applicability honestly. Use Testcontainers only when Docker works and disposable services simplify real tests; otherwise retain plain-process Kiwix tests. Pin external service versions. Linux/container tests do not establish Pi or poor-phone operation.

### D. TUF authority layer, deferred

Use python-tuf only when multi-key governance, root rotation or delegation is required. Its Metadata API is not the complete update workflow; use/reference ngclient's trust workflow. Specify offline metadata transport, expiration/clock assumptions, bootstrap trust, revocation and rollback/freeze behavior. Retain artifact size limits and activation journal. Never disable expiry to make an offline demo pass. Estimate: 1–2+ weeks with a separate security design/review.

## 6. Explicit exclusions

Do not fork Kiwix, switch to phone-side ZIM processing, make a service depend on the public Internet to operate locally, install containers on phones, add a general task queue for one outbox, change project licensing, silently migrate signed formats, auto-update production catalogs, remove old content, increase limits to conceal memory regressions, publish unsupported compatibility badges, or send messages to external maintainers.

## 7. Sources to verify before implementing APIs

- Zstandard dictionaries: https://python-zstandard.readthedocs.io/en/latest/dictionaries.html
- Zstandard decoder allocation/trailing-data behavior: https://python-zstandard.readthedocs.io/en/latest/decompressor.html
- Meshtastic binary API: https://python.meshtastic.org/mesh_interface.html
- Meshtastic device contract: https://meshtastic.org/docs/development/device/client-api/
- SDK license: https://github.com/meshtastic/python/blob/master/LICENSE.md
- pyODK submissions: https://getodk.github.io/pyodk/submissions/
- pyODK supported Central version: https://github.com/getodk/pyodk
- pyODK license: https://github.com/getodk/pyodk/blob/master/LICENSE.md
- zsync: https://zsync.moria.org.uk/
- Testcontainers: https://github.com/testcontainers/testcontainers-python
- TUF APIs: https://github.com/theupdateframework/python-tuf/blob/develop/docs/api/api-reference.rst

Use Context7 when available, but verify actual installed API signatures and primary documentation. A documentation snippet is not proof of compatibility, memory safety or deployment success.
