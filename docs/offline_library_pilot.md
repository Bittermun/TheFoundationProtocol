# Optional offline-library update adapter

This adapter runs on the operator's computer or library appliance. It carries an opaque archive or delta through TFP's existing FM/FD protocol, verifies a locally pinned publisher, and stages a Kiwix catalog update. It adds no phone JavaScript, assets, cryptography, application installation, or phone-side archive reconstruction. Existing acoustic, browser, photo and CLI paths continue to operate independently.

## Scope and resource policy

The pilot accepts base/target archives up to 64 MiB, transfer artifacts up to 16 MiB, patch headers up to 1 MiB and 4,096 target chunks. The transfer wrapper uses at most 256 chunks of 64 KiB, one session, and bounded per-chunk decoder admission. These settings apply to the operator adapter; the shared receiver's default limits are unchanged. Packet generation is lazy, but the bounded artifact is retained on the operator computer. This is not a claim of constant-memory multi-gigabyte support.

Delta selection includes patch overhead: use a patch only when it is at most 80% of the full target; otherwise select the full archive if it fits. Poor deduplication is an ordinary fallback outcome, not an error to conceal. Patch/application limits can be supplied programmatically using `ZimPatchLimits`; default generic patch commands now reject oversized inputs rather than exhausting memory. Legacy v1 patches without chunker parameters are admitted only using original default parameters.

## Change map and risk

| Code area | Shipped change | Risk boundary |
|---|---|---|
| `tfp_core_v4/zim_sync.py:223` and `:269` | Bounded patch creation/reconstruction, spooled payloads, exclusive output installation | Shared patch code; strict parsing and oversized-input rejection are deliberate compatibility changes. Larger programmatic jobs need explicit `ZimPatchLimits`. |
| `library_updates/manifest.py:68`, `prepare.py:11` | Pinned signatures, revisions and delta/full selection | Sensitive authorization logic; keep canonical schema and trust provisioning stable. |
| `library_updates/receive.py:67` | Existing FM/FD transport with authenticated checkpoints | Optional operator path; shared receiver defaults and wire format are unchanged. |
| `library_updates/activation.py:164`, `:157` | Real ZIM/tool checks, reader probe, journaled switch and recovery | Most sensitive integration area; retain single-writer ownership, old archives and recovery journal. |
| `library_updates/cli.py:11` and main CLI delegation | Optional command registration and lazy imports | No background adapter starts with ordinary phone or CLI use. |
| `deploy/iiab/` | Sample separately managed catalog/config and manual service | Deployment template; actual IIAB/Pi operation still requires a pilot. |

Future integrations should reuse signed artifact verification/delivery and add a separate operator module. Avoid changing phone UI, shared decoder limits, radio framing, or trust/schema behavior merely to fit another integration. Small edits in authorization, patch bounds or journal ordering deserve focused design and fault tests; documentation and isolated adapters can use short implementation/test cycles. No protocol redesign is required to exercise this pilot.

## Trust decisions

- A single Ed25519 public key is pinned locally for one named library. A sender-provided key never establishes authority.
- A separate 32-byte shared transport key filters unauthenticated FM/FD packets. This does not identify the publisher.
- Revisions increase monotonically. An equal revision is accepted only when its signed descriptor is exactly the previously committed descriptor. The adapter has no automatic downgrade command.
- The signed descriptor binds library ID, revision, exact base/target/artifact hashes and sizes, artifact type, and patch parameters. Both delta and full updates must match the accepted base.
- Descriptors and signatures are provisioned locally before reception in this pilot. UDP carries the artifact; it does not bootstrap phone software or distribute trust automatically.
- SHA3 hashes establish byte integrity. Real `zimcheck --checksum --integrity` establishes basic ZIM structural integrity. Kiwix catalog/article probes establish reader availability; these checks are reported separately.

## Prepare and deliver

Generate private/public publisher files and a transport key locally. Do not commit or publish private/transport keys. This example writes raw binary keys without printing them:

```python
from pathlib import Path
import secrets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
key = Ed25519PrivateKey.generate()
Path('publisher.key').write_bytes(key.private_bytes_raw())
Path('publisher.pub').write_bytes(key.public_key().public_bytes_raw())
Path('transport.key').write_bytes(secrets.token_bytes(32))
```

On the operator sender:

```text
tfp library-prepare base.zim target.zim --library-id school --revision 1 --signing-key publisher.key --out package
tfp library-send package --library-id school --trusted-key publisher.pub --transport-key-file transport.key --host 192.168.1.20 --port 9876 --rounds 3 --timeout 120
```

Copy only `update.json` and `update.sig` to a new receiving package directory, and provision the public/transport keys privately. Start the receiver before the sender. It binds loopback unless an operator explicitly selects a LAN interface:

```text
tfp library-receive received-package --library-id school --trusted-key publisher.pub --transport-key-file transport.key --host 192.168.1.20 --port 9876 --checkpoint-dir checkpoints --timeout 120
```

Restart the same command after interruption to reuse authenticated completed-chunk checkpoints. Changed transport keys invalidate old checkpoint context. For later revisions supply `--accepted-revision` consistently with `library-status`; final activation independently checks persistent accepted state and rejects stale/conflicting updates. A successful receive means artifact integrity, not activation or reader availability.

For USB/file delivery, copy the complete package and use the same `library-activate` command. No network transport is required.

## Kiwix integration and recovery

Install the optional operator extra with `pip install "tfp[library]"` (includes hardened XML parsing). Install Kiwix/openZIM tools separately on the operator host. Windows integration was exercised with Kiwix tools 3.8.1 and zim-tools 3.8.0; the Linux CI lane uses these pinned versions. The fixture generator uses optional libzim 3.13.0. None becomes a new default production dependency.

Create an explicitly managed **adapter catalog**, initially registering the current base archive with `kiwix-manage`. Start a Kiwix instance using that catalog and `--monitorLibrary`. Use a separate port/catalog for an initial IIAB pilot, leaving IIAB's existing content-manager catalog and services under its control. Do not point the adapter at a live IIAB-managed catalog until ownership and update coordination have been established.

The JSON config follows `deploy/iiab/config.example.json`. Paths may be absolute or relative to the config file. `base_archive` bootstraps revision zero; subsequent accepted bases come from the journaled state. `probe_article_path` must exist in every accepted archive, for example `index.html`. Tool paths are local operator configuration, never executable instructions from an update.

```text
tfp library-activate received-package --config config.json --json
tfp library-status --config config.json --json
tfp library-recover --config config.json --json
```

Activation validates the package, reconstructs a versioned target, checks ZIM integrity, prepares a catalog, writes a recovery journal, switches the catalog, checks public OPDS and `/raw` article access, then commits accepted state. A process lock prevents competing adapter updates. Old archives are retained. A failed reader check restores the old catalog; an unexpected external catalog/state edit prevents automatic overwrite and leaves evidence for operator inspection. No rollback requires deletion of the old archive.

Catalog replacements preserve existing access mode/ownership. If the updater cannot preserve ownership, activation fails before catalog replacement. Archive content is intentionally local-reader-accessible (directory 0755, files 0644); private state is 0700. Provision parent-directory traversal and shared catalog ownership/group access explicitly when using separate service accounts. This pilot serves public library content, not sensitive field reports.

Recovery rolls back an uncommitted catalog switch, or finalizes cleanup if accepted state was committed after reader success. These operations use fsync and atomic file replacement; they are not a multi-file transaction or a universal power-loss guarantee. Unreferenced staged archives/catalog temporaries can remain after process death. Inspect them before manual cleanup; automatic garbage collection is deliberately absent.

## Evidence and remaining deployment gates

Run `scripts/verify_library_update.py` from an installed test environment with optional psutil. It starts separate installed-wheel sender/receiver processes, applies seeded loss through a real UDP proxy, kills the receiver process tree after a persisted chunk, restarts it, hashes the recovered artifact and activates it through a running real Kiwix server. `-I` prevents checkout/PYTHONPATH imports from masquerading as a wheel installation.

The report records artifact/full/wire bytes, loss assumptions, checkpoint count, sampled peak operator process-tree RSS, deadlines and stage outcomes. Wire measurements include the configured carousel rounds; they must not be described as minimum bandwidth required to recover. RSS sampling is evidence from the tested process/fixture, not a universal device guarantee. The ordinary full/resume baseline and low-dedup cases require separate measurement on the same impairment before claiming superiority.

Real independently produced historical ZIM editions, physical Raspberry Pi trials, IIAB deployment coordination and weak-phone/device usability remain explicit adoption gates. Generated fixtures validate mechanics, not those claims. Existing automated browser regression checks protect the original receiver path, but do not replace physical low-end-phone trials.

Official integration references: [Kiwix tools public API](https://kiwix-tools.readthedocs.io/en/latest/kiwix-serve.html), [IIAB configured paths](https://github.com/iiab/iiab/blob/master/vars/default_vars.yml).
