# TFP: separate opportunity scan

September 22, 2026. Brief exploratory research against local revision `f8122d7` and linked primary sources. OTA means over-the-air software updates; weights means model artifacts. Recommendations and proposed integrations below are hypotheses, not demonstrated compatibility. No outreach was performed.

**Where I would start**

The most coherent opportunity is trustworthy delivery over unreliable connections: optional security feeds, software updates, and complete model bundles. These share content identification, resumable transfer, publisher authorization, and version tracking. Monetization can sit at service and access boundaries. Useful-compute-for-access deserves a separate experiment because it adds a buyer, scheduler, verifier, and accounting system.

| Direction | Initial priority | First useful result |
|---|---|---|
| Opt-in hash security/advisory feeds | High | Two independently selected publishers; signed updates; understandable local decisions |
| Offline-capable OTA delivery | High | An interrupted update resumes, validates, installs, and recovers from failed boot |
| Model-weight and adapter delivery | High | A complete, pinned model bundle moves with bounded RAM and reliable resumption |
| Managed delivery, support, and sponsored access | Medium | One operator or sponsor agrees that a measurable service is worth paying for |
| Paid API/content access | Medium | One entitlement survives retries without duplicate charging |
| Useful compute exchanged for access | Experimental | Validated work produces more value than verification and coordination cost |

**1. Opt-in hash security lists**

Treat these as signed assertions from chosen publishers: known-malicious bytes, recalled releases, approved versions, or reviewed educational collections. A hash establishes byte identity; the publisher supplies the claim. Absence from a list does not establish safety.

[NOpfs](https://github.com/ipfs-shipyard/nopfs) is a concrete reference: its Kubo plugin loads local denylist files and supports CID/path rules and exceptions. TFP would need an adapter or its own policy interface; the IPFS addressing scheme is not interchangeable with TFP's SHA3 roots.

Proposed feed fields: issuer, sequence, previous version, algorithm, identifier scope (whole object/chunk/manifest), action, reason, evidence reference, expiry, and signature. Pin trusted publishers explicitly. Let users choose warn, quarantine, or refuse-to-serve behavior, with visible overrides and conflict rules. Apply decisions locally at import, display, execution, or serving boundaries.

Questions that matter: Who can correct a false listing? What happens when subscribed feeds disagree? How does a disconnected device display stale advice? Does blocking a shared chunk accidentally block unrelated objects? Can subscriptions and lookups remain local so readers do not reveal what they possess? Double hashing identifiers does not prevent guessing known candidate content.

Local finding: `tfp_security/heuristic/behavioral_engine.py`, `load_rule_pack`, currently accepts signatures through a stub even when verification is requested. It is a possible integration location, not an authenticated-feed implementation. Use established verification and update machinery rather than treating that flag as protection.

**2. What a compute paywall would entail**

| Mechanism | What the visitor contributes | How the publisher benefits | Main unresolved issue |
|---|---|---|---|
| Proof-of-work challenge | CPU time solving a puzzle | May reduce abusive request volume | No direct revenue; burdens weaker devices |
| Useful compute for access | A validated job, such as a permitted batch transformation | A sponsor buys results, or the publisher avoids its own expense | Finding valuable jobs with cheap verification |
| Monetary access payment | Payment for an entitlement | Revenue from content or service access | Payment, delivery, retries, and refunds must reconcile |
| Sponsored/community access | A funder covers a collection or community | Predictable funding while readers retain access | Proving reach or service quality without tracking readers |

[Anubis](https://github.com/TecharoHQ/anubis) is a challenge-based scraper-defense reference, not evidence that puzzle-solving monetizes content. [BOINC](https://github.com/BOINC/boinc) provides a useful volunteer-computing reference; its published work discusses redundant computation and validation before credit. Its credits are not automatically spendable money. [BOINC scheduling paper](https://boinc.berkeley.edu/boinc_papers/sched/paper.pdf)

For useful compute, specify the buyer and job before designing the currency. Start with a fixed, sandboxed workload, explicit opt-in, resource limits, a stop control, and an alternative access route. Bind each job to its inputs, version, nonce, deadline, and acceptance rule. Test fabricated results, duplicate submissions, and nondeterministic output. Redundancy consumes some of the value earned.

The economic question is: **buyer payment or avoided cost minus verification, retries, coordination, and delivery costs**. Track the reader's energy, latency, and abandonment separately; shifting those costs to readers does not make them disappear.

For paid access, inspect [x402](https://github.com/x402-foundation/x402), which provides HTTP payment tooling including Python support, and [Aperture/L402](https://github.com/lightninglabs/aperture), a Lightning payment reverse proxy. These are alternative connected-gateway integrations; neither automatically provides disconnected settlement.

TFP's `tfp_plugins/access_control/license_manager.py` already sketches paywalls and grants but labels itself a stub; its payment check does not verify a payment. A concrete encrypted-content design needs authenticated encryption, protected key delivery, durable entitlements, and retry-safe accounting. Once a reader receives plaintext or a reusable key, the protocol cannot guarantee that it will never be copied. Selling maintenance, freshness, availability, and support may fit better than relying entirely on copy restriction.

**3. Transactions for OTA and weights**

Keep three receipts distinct: payment accepted, bytes verified, and installation/model activation successful. One does not prove the others. A device's signed report identifies its assertion, not necessarily truthful execution on a compromised device.

Proposed local lifecycle: authorized manifest → fetch missing data → verify complete bundle → stage → activate → health check → commit, or recover to an approved working version. Give attempts stable identifiers and persist transitions so retries are harmless. Payment adds a separate ledger and an explicit refund/credit policy; it is not atomic with a remote device's filesystem.

[TUF](https://theupdateframework.io/) and its [Python implementation](https://github.com/theupdateframework/python-tuf) are the first authorization/security candidates. [Uptane's offline-update specification](https://uptane.org/enhancements/pures/pure2) is particularly relevant to directed updates delivered without the normal online exchange. Design clock trust, expiry, key rotation, rollback resistance, and offline duration deliberately; simply disabling expiry removes protection.

[RAUC](https://github.com/rauc/rauc) covers signed bundles, installation, and boot integration. Its [documented slot and boot-confirmation model](https://rauc.readthedocs.io/en/latest/basic.html) gives a concrete boundary: TFP can transport the bundle; RAUC and the configured bootloader handle device-specific installation and recovery. A recovery boot and authorization to install an older vulnerable version are different policies.

For models, [Xet](https://github.com/huggingface/xet-core) and its [Hub integration](https://huggingface.co/docs/hub/xet/using-xet-storage) provide chunk-based transfer and deduplication references. [Safetensors](https://github.com/safetensors/safetensors) is a tensor format designed to avoid pickle-style arbitrary-code loading. Neither establishes model quality, provenance, or safe behavior.

Pin the weights, tokenizer, configuration, runtime requirements, license, and exact base-model identity for adapters. Verify native upstream digests as well as TFP object hashes; different chunking and hash schemes require an explicit mapping. Measure transfer reuse across actual checkpoints: fine-tuning, quantization, compression, and encryption can change large portions of the bytes. Small parameter updates do not guarantee small transfers.

Use Wi-Fi, wired links, or removable storage for large weights. At an ideal 1,200 bits/second, 1 GiB takes about 83 days before overhead or loss. Acoustic/radio paths are more plausible for announcements, manifests, receipts, and small updates. The local README also notes that completed receiver chunks remain in memory: large-file delivery needs bounded-memory measurement before any scale claim.

**4. Positions most needed, and publicly relevant people**

My staffing order is a security/update engineer and a field integration lead first, followed by storage/transfer engineering, embedded installation expertise, and payment/compute economics. These can begin as fractional collaborators. Need and likely availability are separate questions.

| Needed contribution | Publicly relevant person or community | Why the match is plausible; first conversation |
|---|---|---|
| Update authorization and key lifecycle | **Justin Cappos / NYU Secure Systems Lab** | Public work includes TUF and Uptane. Ask about stale clocks, offline root rotation, and disconnected update authorization. [NYU profile](https://ssl.engineering.nyu.edu/personalpages/jcappos/) |
| Offline library integration and deployment realities | **Emmanuel Engelhart**, listed as Kiwix CTO; **Stéphane Coillet-Matillon**, listed as CEO | Technical fit for real ZIM interoperability; deployment/funding fit for a library pilot. [Kiwix team](https://kiwix.org/en/about/) |
| Model storage and deduplication | **Yucheng Low / Xet contributors** | His public profile links work on Hub chunk/block transfer and deduplication. Ask which workload would meaningfully benefit from disconnected replication. [Public profile](https://huggingface.co/yuchenglow) |
| Useful-compute validation and incentives | **David P. Anderson / BOINC community** | Public work in volunteer computing directly overlaps validation and scheduling. Ask which small jobs remain valuable despite delayed results. [Berkeley profile](https://boinc.berkeley.edu/anderson/) |
| Device installation and recovery | **RAUC maintainers plus an actual fleet operator** | Select collaborators from the device/bootloader in the pilot; require a power-interruption demonstration. [RAUC project](https://github.com/rauc/rauc) |

These are relevance-based leads, not claims that anyone is interested, available, endorsing TFP, or suitable for hiring. Kiwix and an actual disconnected-site operator appear the closest mission fit; TUF/Uptane and Xet contributors are targeted technical conversations. An operator with real devices and authority to run a pilot may be more valuable initially than a prominent advisor.

**5. Further branches worth asking about**

| Ambitious question | Possible integration or smallest useful investigation |
|---|---|
| Could one artifact format carry software, weights, maps, and libraries? | Test an [ORAS/OCI](https://github.com/oras-project/oras) import/export bridge while retaining upstream digests. |
| Could provenance travel with the bytes into disconnected environments? | Examine [Cosign](https://github.com/sigstore/cosign) evidence bundles and define offline trust material and freshness policy. |
| Could a classroom synchronize only its missing lessons? | Compare a [Kolibri](https://github.com/learningequality/kolibri) deployment's needs with TFP's transfer model. |
| Could community Wi-Fi deliver a genuine offline library automatically? | Pilot with [kiwix-tools](https://github.com/kiwix/kiwix-tools); validate actual ZIM files rather than assuming a directory export is equivalent. |
| Could a sponsor buy public release of a collection once a funding target is reached? | Prototype collective unlock with a conventional ledger first; specify refunds and the release authority. |
| Could relays earn compensation for useful delivery? | Distinguish verified possession from new delivery; test colluding sender/receiver receipts and self-generated demand. |
| Could idle community machines perform disconnected batch jobs? | Try signed task/input/result bundles; measure verification cost and usefulness after delay. |
| Could security feeds become a marketplace for competing reviewers? | Pilot independently subscribed advisories with corrections, provenance, and visible disagreement. |
| Could disaster updates reach everyone without revealing who read them? | Compare aggregate delivery evidence, optional receipts, and privacy costs; avoid equating acknowledgments with human readership. |
| Could a model runtime fetch only the tensors it needs? | Measure random-access latency and cache misses; verify that partial availability cannot activate an inconsistent model. |
| Could a model, runtime, and dataset update activate as one compatible release? | Define a dependency manifest and local activation boundary; test interrupted staging. |
| Could paid professional maintenance subsidize freely shared emergency material? | Interview an operator and a sponsor about support, update cadence, and measurable service outcomes. |

**Three small experiments to choose among**

1. **Trust-feed prototype:** accept signed, versioned advisory bundles from two publishers. Exercise forged signatures, replay, stale feeds, contradictory entries, and local overrides. Pass only if decisions are reproducible and explainable.
2. **Delivery pilot:** move one firmware bundle and two related model versions through interrupted connectivity. Record bytes retransmitted, peak RAM, disk needs, energy, verification failures, and recovery. Compare with the incumbent transfer process under identical conditions; no performance improvement is established yet.
3. **Economic pilot:** ask one prospective buyer to value a specific service or compute output. Compare paid delivery, sponsored access, and useful-compute exchange using measured costs. Do not build a broad compute-credit market before identifying a payer and an acceptance rule.

This scan checked documentation and selected local code paths, not full repository maintenance histories, licenses across dependencies, installation compatibility, or production readiness. External evidence came from official repository pages, project documentation, public professional profiles, and the Python TUF documentation retrieved through GitMCP. No runtime code was changed.
