# Reproducible Offline-Library Updates Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task. This is a planning deliverable, not authorization to implement or publish. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Independently demonstrate an interrupted TFP archive update that recovers after restart, verifies the publisher and bytes, and becomes readable through Kiwix; then package that workflow for an IIAB pilot.

**Architecture:** Reuse the existing media fountain wire protocol and checkpoint receiver. Treat archives and patches as opaque transfer artifacts; keep signed update authorization, patch reconstruction, and Kiwix activation separate. Deliver a bounded laptop demonstration first, a pinned Linux/Kiwix integration second, and IIAB deployment third.

**Tech Stack:** Existing Python runtime, FastCDC/SHA3-256, existing Ed25519 dependency, SQLite, existing FM/FD fountain packets, Kiwix tools, optional Linux systemd deployment.

**Spec:** The design brief and boundaries below are the proposed specification. User requested an explicit code/integration/avoidance plan following the adoption review. Existing anchors are verified against commit `d8fc066`; re-query the AST and refresh line references before execution.

## Design brief and decisions

- Intended users: offline-library operators and developers evaluating whether TFP improves update delivery.
- Success: a third party can install a wheel outside the checkout, transfer a real update through separate processes, interrupt/restart reception, and open a changed page in Kiwix. Tampered or unauthorized updates never replace accepted content.
- First scope: one library, one pinned publisher, one update at a time, local UDP; USB/file import uses the same verification/activation path. No new transport protocol.
- Proposed initial caps: base and target archives 64 MiB each; artifact 16 MiB; patch header 1 MiB; 4,096 target chunks; 128 KiB per patch chunk; 256 MiB peak receiver-process RSS. Exceeding a cap produces an explicit failure before activation. These are pilot limits, not claims about the existing repository or performance already achieved.
- Prefer a delta only if complete artifact bytes, including metadata, are at most 80% of full archive bytes; otherwise use a full archive if it fits the artifact cap. Reject when neither fits. Report actual wire bytes separately.
- Options considered: another standalone viewer duplicates Kiwix; an immediate upstream IIAB change depends on maintainer acceptance; an independently installable integration gives a reviewable pilot first. Select the third.
- Deferred: archive-scale multi-gigabyte support, cluster-aware ZIM parsing, acoustic onboarding, automatic key discovery, multi-publisher governance, ODK and DPG submission, upstream publishing.

## Existing code map

| Area | Verified anchors | Intended action |
|---|---|---|
| Patch creation/reconstruction | `tfp_core_v4/zim_sync.py:43`, `:163`, `:190`, `:236`, `:285` | Fix payload retention and unsafe direct output; bound parsing; validate base and target; remove unsupported cluster-aware/O(1) claims. |
| CLI | `tfp_core_v4/cli.py:200`, `:205`, `:974`, `:996` | Preserve current commands; delegate new update subcommands to a focused module. |
| Fountain sender | `tfp-foundation-protocol/tfp_client/lib/media/fountain_streamer.py:238`, `:363`, `:392` | Reuse authenticated FM/FD packets and UDP transport; consume generators without materializing a packet list. |
| Checkpoint receiver | `tfp-foundation-protocol/tfp_client/lib/media/receiver.py:73`, `:178`, `:567`, `:638`, `:662` | Reuse bounded admission/checkpoints; inspect limits before configuring larger pilot transfers. `assemble()` returns bytes, so budget that allocation explicitly. |
| Prior verification | `scripts/verify_offline_lifecycle.py:57`; `tests/test_udp_process_boundary.py:49` | Reuse patterns; retain old smoke test. Directory export and in-process simulation do not prove real ZIM interoperability. |
| Packaging | `pyproject.toml:108`, `:119`; `tests/test_package_asset_resolution.py` | Include only required pilot assets; test the installed wheel outside the checkout. |
| LoRa prerequisite | `tfp_transport/meshtastic_bridge.py:54`, `:423`, `:460`, `:506` | Separate follow-up: stock Meshtastic framing/protobuf compatibility before hardware claims. |
| Photo claim | `phone_download/index.html:249`, `:324` | Separate correction: label server-side hashing accurately; no automatic client-verification claim. |

## Global constraints

- Use `.dist_verify/runtime/Scripts/python.exe` on Windows. AST-query changed symbols before locating callers/tests; refresh the snapshot after Python symbol changes.
- Keep existing commands and valid patch fixtures compatible. Because legacy patches omit chunker parameters, signed pilot descriptors explicitly carry the parameters used to create them; generic patch commands must reject incompatible reconstruction rather than silently guess.
- Publisher authorization is Ed25519 against locally pinned public keys. Transport HMAC admission uses an explicitly provisioned nonempty secret; it is not publisher identity. Do not embed secrets or private keys in public demo assets or reports.
- Compare digests with `hmac.compare_digest`; use `secrets` for identifiers/keys; track async tasks and handle failures; give every network/subprocess operation an explicit deadline.
- Stage on the destination filesystem. Never overwrite a base, patch, existing accepted archive, or accepted catalog during validation. Reject resolved aliases, symlink escapes, and output/input collisions.
- Failures retain the old readable library. Filesystem rename is not a multi-file transaction or a universal power-loss guarantee; use a durable activation journal and recovery rules.
- No production mocks. Linux/Kiwix-dependent tests may be explicitly unavailable locally, but must pass in the integration lane before claiming reader/IIAB compatibility.

## Review focus

1. Untrusted patch length/count fields must be rejected before oversized reads or allocations (Task 1).
2. A valid signature from an unpinned key, stale revision, or signed wrong-base update must not activate (Task 2).
3. Restart with changed authentication context must not reuse incompatible checkpoints (Task 3).
4. Disk-full, process death, or two competing updaters must leave the accepted catalog recoverable (Task 4).
5. A favorable synthetic delta must not stand in for real compressed-ZIM savings or actual reader success (Task 5).

## Task 1 — Make patch operations safe within declared limits

**Files:** Modify `tfp_core_v4/zim_sync.py:163-310`; extend `tests/test_zim_delta_sync.py`; create `tests/test_zim_patch_admission.py`.

**Interfaces:** Preserve `create_patch(base_path, target_path, patch_out, metadata=None) -> ZimPatchManifest` and `apply_patch(base_path, patch_path, out_path) -> None`. Add keyword-only `limits: ZimPatchLimits | None = None` to both. Define frozen `ZimPatchLimits(max_header_bytes=1048576, max_chunks=4096, max_chunk_bytes=131072, max_target_bytes=67108864)` in this module. Pilot always supplies these limits; decide and document bounded defaults for legacy CLI use.

- [ ] Write tests for mostly novel content, exact-base mismatch, malformed/truncated records, oversized header/count/chunk/target, duplicate conflicting records, unsupported parameters, input/output aliases, and a preexisting output surviving hash failure.
- [ ] Run tests and confirm each new assertion fails for the intended reason before editing implementation.
- [ ] Spool novel payloads to a temporary file instead of `dict[str, bytes]`; retain bounded hash/offset metadata only. Cleanup spool on success and failure. Validate integer types including rejection of bool, lengths against remaining file size, base digest before reconstruction, each referenced chunk digest, final size and final digest. Reject trailing malformed data.
- [ ] Write patch and reconstructed output to exclusive temporary siblings; flush/fsync before installation. Default to refusing an existing output. Reject output paths resolving to either input. Remove only temporary files on failure.
- [ ] Replace cluster-aware and O(1) wording with generic binary CDC and measured/capped memory behavior. The hash indexes and target sequence still scale with chunk count.
- [ ] Run the focused suite and a subprocess RSS check using streamed fixture generation, not a giant parent-process bytes object. Review and commit only this task after the repository gate.

## Task 2 — Define signed update authorization and artifact selection

**Files:** Create `tfp_core_v4/library_updates/__init__.py`, `manifest.py`, `prepare.py`; create `tests/test_library_update_manifest.py`; modify CLI parser near `:200` and dispatch near `:974`.

**Interfaces:** `prepare_update(base: Path, target: Path, output_dir: Path, library_id: str, revision: int, signing_key: Path) -> Path`; `verify_update(manifest_path: Path, artifact_path: Path, trusted_keys: dict[str, bytes], accepted_revision: int) -> VerifiedUpdate`. Define frozen `VerifiedUpdate(library_id: str, revision: int, base_sha3: str, target_sha3: str, target_size: int, artifact_sha3: str, artifact_size: int, artifact_kind: str, chunker_params: tuple[int, int, int], publisher_key_id: str)`.

- [ ] Test signed canonical serialization, byte tampering, unknown publisher, wrong library ID, stale/equal-conflicting revisions, exact duplicate idempotence, signature changes to every field, and selection immediately above/below the 80% threshold.
- [ ] Canonical signed JSON body: schema version, library ID, monotonic revision, base/target/artifact SHA3 digests, sizes, artifact kind, chunker parameters, publisher key ID. Use sorted keys, compact separators, UTF-8, no NaN, strict field/type validation; detached signature covers these exact bytes. Reject duplicate JSON keys and oversized descriptors. Public-key pinning is local configuration, not metadata supplied by the sender.
- [ ] Artifact lives beside `update.json` and `update.sig`; use fixed local filenames selected from `artifact_kind`, never paths from untrusted metadata. Full archive activation still requires signed base/revision checks. Ordinary rollback is a separate explicit local operator action, not an accepted stale update.
- [ ] Add `tfp library-prepare BASE TARGET --library-id ID --revision N --signing-key FILE --out DIR`; errors return nonzero and do not leave a publishable partial package.
- [ ] Run tests and the gate; commit this independently testable preparation/verification task.

## Task 3 — Reproducible transport, interruption, and restart proof

**Files:** Create `scripts/verify_library_update.py`, `tfp_core_v4/library_updates/receive.py`, `tests/test_library_update_delivery.py`; extend `tests/test_receiver_checkpoints.py` only if receiver behavior changes.

**Interfaces:** `async receive_artifact(expected_size: int, expected_sha3: str, destination: Path, checkpoint_dir: Path, host: str, port: int, timeout_seconds: float, transport_key: bytes) -> Path`. Consume verified descriptor expectations; transfer only the artifact through FM/FD. Descriptor/signature provisioning is explicit local file transfer in v1, not claimed to occur automatically over UDP.

- [ ] Test real separate sender/proxy/receiver processes: seeded 30% test packet loss; stop receiver after a completed checkpoint chunk; restart; finish; independently stream-hash received artifact. Check 100% loss times out nonzero and never reports success.
- [ ] Test wrong transport key, changed restart context, corrupt artifact, duplicate packets, wrong declared size, and oversized manifest. Preserve existing receiver admission behavior and covered tests.
- [ ] Keep packet generation lazy. Configure receiver chunk/session bounds from the signed descriptor within local caps; account for `assemble()` and chunk retention in RSS. Never turn off authentication to make a demonstration pass.
- [ ] Report JSON schema v1: commit, wheel hash, tool versions, fixture hashes, scenario, loss seed/rate, deadline, sent/received wire bytes, artifact/full sizes, RSS, elapsed time, restart count, per-stage pass/fail/unavailable and failure reason. Never report secrets, local private-key contents, or unsupported hardware success.
- [ ] Add `tfp library-receive --manifest FILE --signature FILE --trusted-key FILE --transport-key-file FILE --checkpoint-dir DIR --out FILE --host HOST --port PORT --timeout SECONDS`. Cap endpoint exposure to the explicitly supplied bind address.
- [ ] Verify clean-wheel installation and execution from an unrelated directory, plus corrupt/incomplete asset failures. Gate and commit.

## Task 4 — Kiwix adapter with recoverable activation

**Files:** Create `tfp_core_v4/library_updates/kiwix.py`, `activation.py`; create `tests/test_library_update_activation.py`, `tests/integration/test_library_update_kiwix.py`; create `deploy/iiab/tfp-library-update.service`, `deploy/iiab/README.md`, and sample operator configuration.

**Interfaces:** `activate_update(update: VerifiedUpdate, artifact: Path, config: KiwixConfig) -> ActivationResult`; `recover_activation(config: KiwixConfig) -> ActivationResult`. Define `KiwixConfig(library_id: str, archive_dir: Path, library_xml: Path, state_dir: Path, kiwix_manage: Path, zimcheck: Path, serve_base_url: str, probe_article_path: str, command_timeout_seconds: float)` and `ActivationResult(status: str, revision: int, target_path: Path, recovered: bool)`.

- [ ] Acquire one local updater lock; resolve approved roots and reject aliases/symlink escapes. Verify signature/artifact/base and available disk space; disk budget includes retained base, artifact, reconstructed target and temporaries. Do not promise in-place updates.
- [ ] Reconstruct into a versioned temporary target; verify exact size/digest and run real `zimcheck`. A correct hash is not structural ZIM validation. Use argument arrays and explicit subprocess deadlines, never shell strings from metadata.
- [ ] Journal states `staged -> target_verified -> catalog_prepared -> catalog_switched -> reader_checked -> committed`. Prepare a copy of the accepted catalog and use `kiwix-manage` to register the versioned archive. Swap the catalog only after all local checks; record old catalog and accepted revision for recovery. Keep the predecessor archive.
- [ ] With the pinned Kiwix version, use `--monitorLibrary` or a narrowly configured SIGHUP integration. Probe public OPDS catalog and `/raw` article access with deadlines. Never scrape private reader UI endpoints or restart every installed service.
- [ ] On reader-probe failure restore the old catalog and verify the old page remains readable. On restart, reconcile journal/catalog/archive before accepting another update. Duplicate activation is idempotent. Test process exit after each journal transition, catalog permissions failure, disk-full, stale updates and two competing updaters.
- [ ] Add `tfp library-activate PACKAGE_DIR --config FILE` and `tfp library-status --config FILE --json`; status distinguishes received, signature verified, reconstructed, reader checked and committed. None is implied by another.
- [ ] Package as a separately installable IIAB add-on under a dedicated service account. Discover/configure actual IIAB paths and installed Kiwix versions; do not assume directory watching or write IIAB-managed catalogs without coordinating its content manager. Validate one pinned IIAB release in a disposable Linux instance before writing a support claim.
- [ ] Run the real Kiwix integration lane, gate and review; commit. Local tests without installed Kiwix must say unavailable, never silently pass the integration requirement.

## Task 5 — Release evidence and adoption package

**Files:** Create `tests/fixtures/library_update/README.md`, `fixtures.json`, `docs/offline_library_pilot.md`, `docs/library_update_results.md`; update README claims and CI integration lane after inspecting existing workflow files.

- [ ] Include a small deterministic real ZIM pair generated with pinned openZIM tools and licensed content, with one visibly changed article. Record source license, tool version, checksums and generation command. Also benchmark a genuine independently produced compressed-ZIM edition pair; if historical pairs are unavailable, disclose that gap rather than substituting random bytes.
- [ ] Publish measured patch savings and total wire cost, including retransmission and metadata, against an interrupted ordinary full-file copy/resume baseline using the same link assumptions. Include a low-dedup case and report full fallback honestly. Favorable savings are evidence, not a mandatory result to manufacture.
- [ ] Run demonstration offline after installation: interruption/restart, correct changed article, old library readable on failure, publisher rejection, peak RSS within 256 MiB, installed-wheel reproducibility. Repeat on physical Raspberry Pi before adding Pi performance claims.
- [ ] Produce release-local evidence bundle: commands, hashes, report JSON, readable results, known limitations, installation/uninstall instructions and one short optional recording. Public release, upstream PR and partner contact remain separate user-authorized actions.
- [ ] Update README test badge to a verified CI result rather than a hand-maintained count. Correct photo wording to `Server computed SHA3-256 Merkle root` until client verification is actually implemented.
- [ ] Run AST-covered tests for every touched symbol, snapshot regeneration for added Python symbols, the official gate and explicit checks on the new root-level package. Review that no integration requirement is represented only by skipped tests.

## Separate follow-ups — explicit boundaries

### Stock Meshtastic compatibility

Modify `tfp_transport/meshtastic_bridge.py:54-154` and serial handling `:423-520`; update `tests/test_transport_meshtastic_bridge.py` and optional dependency declarations. Replace custom device-facing SLIP/custom metadata with official `ToRadio`/`FromRadio` protobuf envelopes and `0x94 0xC3` length framing, preferably through the maintained SDK. Preserve TFP payload authentication inside the application packet. Confirm application-port allocation, firmware payload ceiling, channel selection, hop fields, reconnect behavior and actual airtime from pinned firmware documentation. Test with official protobuf fixtures and two physical stock-firmware radios on an explicitly configured private channel. Do not send archive-scale updates over LoRa or claim simulated roundtrips prove radio compatibility. This can ship independently and is not a dependency of the UDP library pilot.

### ODK adapter — next integration after library proof

Create `tfp_integrations/odk/submissions.py`, `outbox.py`, `tests/integration/test_odk_delivery.py`; reuse TFP artifact delivery and add a dedicated CLI module instead of expanding the main CLI dispatch indefinitely. Start with one fixed form: immutable instance ID, submission XML, photo attachment hash and local durable outbox state. Send XML and expected attachments through ODK Central's documented APIs with operator-provisioned credentials, explicit deadlines, retry state and duplicate reconciliation; mark complete only after every required attachment is confirmed. Test disconnects between XML/attachment upload, already-existing IDs, invalid forms, expired credentials and actual Central roundtrip. Do not build a competing form designer, assume KoBo API equivalence, or expose field photos through the unrestricted prototype photo server. Pin the actual Central release and form before implementation.

### DPG eligibility — documentation work, not a code badge

Create `docs/adoption/dpg-readiness.md` mapping each current standard criterion to repository evidence and gaps: ownership/license, documentation, platform independence, privacy, safety and relevant public benefit. Use results from the pilot, not intended behavior, as evidence. No automatic nomination, certification claim or guaranteed funding; nomination and external messaging need user authorization.

## Things to avoid across the work

- Do not fork Kiwix, replace its viewer, invent a ZIM-like format, or call a directory of HTML a real ZIM.
- Do not silently change the patch wire format or let a decoder guess chunker parameters.
- Do not promise fixed-memory multi-gigabyte updates based on small fixture tests; preserve explicit pilot caps.
- Do not equate CRC, Merkle hashes, transport HMAC, publisher signature and local publisher trust.
- Do not activate unsigned descriptors, accept arbitrary output paths, execute commands from manifests, or leak shared secrets into artifacts.
- Do not delete old archives automatically; catalog activation and later garbage collection are separate operations.
- Do not rewrite the shared receiver to add speculative scale features before measuring the bounded pilot.
- Do not contact maintainers or publish compatibility badges before producing the exact evidence they would review.

## Sources to revalidate at implementation time

- [Kiwix serving, library monitoring and public HTTP API](https://kiwix-tools.readthedocs.io/en/latest/kiwix-serve.html).
- [IIAB deployment defaults](https://github.com/iiab/iiab/blob/master/vars/default_vars.yml): paths are configuration, not a universal contract.
- [Meshtastic device API](https://meshtastic.org/docs/development/device/client-api/).
- [ODK submission and attachment API](https://docs.getodk.org/central-api-submission-management/).
- [Digital Public Goods Standard](https://www.digitalpublicgoods.net/standard).

## Verification commands

During implementation, for each task: write failing behavioral tests, confirm failure, implement, run focused tests plus graph-covered tests, review, then gate before committing. The commands below are future execution requirements, not assertions that unimplemented tests exist or pass today.

```powershell
.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_zim_delta_sync.py tests/test_zim_patch_admission.py tests/test_library_update_manifest.py tests/test_library_update_delivery.py tests/test_library_update_activation.py -q --timeout=30
.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_checkpoint_admission.py tests/test_receiver_checkpoints.py tests/test_udp_process_boundary.py tests/test_package_asset_resolution.py -q --timeout=30
.\.dist_verify\runtime\Scripts\python.exe -m mypy tfp_core_v4/library_updates --ignore-missing-imports
.\.dist_verify\runtime\Scripts\python.exe -m bandit -c bandit.ini -r tfp_core_v4/library_updates -ll
.\.dist_verify\runtime\Scripts\python.exe scripts/code_graph.py --json
powershell -ExecutionPolicy Bypass -File scripts/agent/run_agent_gate.ps1
```

Linux integration lane: run `tests/integration/test_library_update_kiwix.py` with pinned real Kiwix/openZIM tools, then the complete installed-wheel demonstration and a disposable pinned IIAB installation. Release is blocked by unavailable/failing required integration checks, failed recovery checks, or unmeasured memory.
