# Foundation: current review and smallest high-impact focus plan

Prepared 2026-09-12 from `AI_HANDOFF.md`, direct source inspection, and the external references below. This is an assessment and proposed plan. No runtime fixes, benchmarks, full-suite validation, commits, or pushes were performed for this review. Earlier validation results in the handoff remain historical.

The subsequent [execution megaplan](FOUNDATION_MEGAPLAN.md) adds eight reproducible component observations, artifact identity/update prerequisites, the full mission dependency map, and explicit work packets. Use that plan for execution order; this document remains the initial assessment.

**Recommendation: preserve the reliability work, then prove that contributed work creates a shared resource worth reusing. Measure the value of sharing and the value of pooling separately.**

## Intended outcome

Foundation is intended as shared infrastructure for useful computation and content across devices and independently operated networks. A device contributes affordable work; that work improves a versioned lexicon resource; other devices and projects reuse it; demand guides where further work is useful. The content library demonstrates only part of this intention.

The working interpretation of lexicon is a family of reusable priors, dictionaries, or adapters, with explicit versions and compatibility. Its final representation is unresolved. A small compression dictionary would be a bounded experiment within that space, not a definition of the whole lexicon.

## What the evidence supports

| Area | Evidence | Current conclusion |
| --- | --- | --- |
| Local content demo | Handoff records successful HTTP, browser, and earlier installed-wheel checks | Useful repaired baseline, awaiting final validation after later edits |
| Compute pool | `TaskSpec` supports hash preimage, matrix verification, and content verification; task APIs expose expected hashes and accept reported output hashes | Task mechanics exist; this does not deliver or validate a new reusable artifact |
| Shared lexicon | HLT models domains, versions, and adapter hashes; `RealLexiconAdapter.reconstruct` returns supplied bytes with metadata | Representation scaffolding exists; measured shared reconstruction benefit is unproved |
| Weak devices | `ComputeMesh` selects among supplied bids; safety checks consume supplied metrics | No demonstrated live measurement, bounded execution, or useful low-power participation |
| Demand allocation | `schedule_from_aggregator` converts demand into broadcast slots; observed call sites were tests | A scheduling component exists; a demand-to-delivery runtime path is unproved |
| External use | Web bridge registers handlers and parses addresses | Integration scaffolding exists; an independent application consuming a compute-produced resource is unproved |

Direct source inspection supports the handoff's two repair targets: the mutation subprocess has no timeout despite the global 30-second test budget, and automatic task rewards span completion, replay recording, minting, supply updates, and persistence without one surrounding settlement operation. The latter is a failure/retry and concurrency risk to reproduce, not a newly demonstrated exploit.

Existing uncommitted source changes were present when this review began. They should be preserved. No final all-green or production-readiness claim follows from this review.

## Inferences and speculation

**Strong inference: the highest-value missing piece is a connection between existing components.** Adding more disconnected modules cannot establish that pooled computation makes the lexicon useful. An actual result must become a stored artifact that another client consumes.

**Working hypothesis: the first efficiency gain is more likely within a narrow content family.** Repeated structure in related records offers a plausible starting point. Zstandard's documentation specifically describes this case and cautions that dictionaries are data-specific. This does not predict a percentage gain for Foundation. [Zstandard small-data documentation](https://facebook.github.io/zstd/#small-data)

**Speculation: Foundation's distinctive value could be the lifecycle around shared resources.** Creating, checking, selecting, distributing, updating, and retiring reusable artifacts across projects may be more valuable than a new compression algorithm. Existing codecs can test that proposition without settling the eventual generative-prior design.

**Speculation: demand can become a common way to prioritize useful work.** The same eventual pipeline could prepare a popular resource, replicate a hot video segment, or refresh an adapter. Start with observable jobs and completed outputs. The optimal demand policy and video mechanism remain open questions.

**Weak-device hypothesis: small independent jobs and local reuse may matter more than raw speed.** A modest device could build or evaluate a small artifact, retain useful shared resources, and benefit directly from less repeated transfer or preparation. Whether this outweighs dispatch, verification, and energy costs must be measured on actual hardware.

Hashes identify and check resources. Exact reconstruction still needs the shared resource, a compatible decoder, and enough content-specific information to recover the original. A learned prior alone must not silently substitute plausible content for the original bytes.

## Three areas of focus, in order

### 1. Make the existing checkpoint trustworthy

Keep this to the known repair boundary:

- Bound mutation subprocess execution and give the parent test a justified total budget. A timeout or broken test collection must not count as successful fault detection.
- Reproduce task settlement failures and retries. Ensure task completion, reward claims, receipts, supply, and persisted balances recover consistently; a lock alone does not establish crash recovery.
- Run focused checks, then the final full suite, installed-wheel smoke check outside the checkout, and browser journey. Record actual outcomes and remaining limitations.
- Make a small README/UI copy correction that presents pooled work, shared lexicon resources, demand, and integration as the intended mechanism. Use one demonstrated/component/intended status table. This review fills the previously missing README review link.

**Done:** the repaired demo is reproducible, accounting survives the tested failure cases, and a visitor can distinguish the current demonstration from the research vision. Avoid using this step as a reason for a broad refactor.

### 2. Test one shared resource before expanding the live system

Start with one real workload of related small text or structured records. Use content the project is allowed to process and keep training, candidate selection, and final evaluation data separate. Freeze the final evaluation set before tuning. Include unrelated or already-compressed content as a negative control.

**Proposed experimental artifact:** a small versioned compression dictionary for that workload. Use an established implementation. This is a test of reusable shared state, not a claim that the full lexicon has been designed.

First compare ordinary compression/caching with a shared dictionary built on one machine. If there is no useful benefit after distribution and update costs, stop this candidate before wiring it into the task pool.

If the candidate is useful, add one bounded job that produces actual artifact bytes. For example, build one small dictionary from a fixed sample batch and fixed parameters. Start on a supported modest computer; do not assume a phone can run the existing Python worker. If the job does not fit that device, shrink or change the job based on measurements. Do not assume independently trained dictionaries can be merged.

The minimum job contract needs input references and hashes, algorithm/version/parameters, execution and memory bounds, an output artifact reference/hash, and a validation rule. A copied expected hash is not an output. Verify the returned bytes and their required behavior. Full deterministic re-execution is acceptable for an initial controlled correctness demonstration, with its entire cost counted; it does not establish efficient permissionless verification.

Use the existing task dispatch, blob storage, and HLT interfaces where they fit. Connect them through a small result-validation-and-installation path rather than introducing another scheduler. Require:

1. A modest worker performs a bounded job and returns the artifact.
2. A malformed, incompatible, or otherwise invalid output is rejected.
3. An accepted output is stored with an explicit version and decoder requirements.
4. A second client fetches the artifact and uses it to recover previously unseen content exactly.
5. Missing or incompatible shared resources trigger a defined fallback.

Compare three configurations under equivalent workloads and delivery conditions:

| Configuration | What it isolates |
| --- | --- |
| A: ordinary compression plus normal caching/deduplication | Competitive baseline |
| B: shared artifact built centrally | Incremental value of reusable shared state |
| C: the same artifact-building algorithm dispatched to contributors | Incremental value and cost of pooling |

Where the workload permits batching or persistent compression, include that competitive baseline too. Do not win only by comparing against raw uncompressed transfers.

Report total transferred bytes, preparation/verification CPU time, elapsed time, peak worker/client memory, fallback frequency, and energy where directly measurable. Count training input transfers, every required artifact delivery, metadata, redundant validation, failures, updates, and normal content traffic. Show cold and warm clients separately; global popularity is not a substitute for reuse within each client's cache.

For network traffic, the basic break-even condition is:

`cumulative payload bytes avoided > job traffic + artifact deliveries/updates + extra protocol traffic`

CPU time, memory, energy, and latency remain separate budgets. Choose a practical minimum benefit and device limits before the final comparison, based on the workload owner's needs.

**Done:** the report can distinguish “sharing helped” from “pooling helped.” If B wins but C loses, retain shared-resource reuse and reconsider the pooled job. A negative result is a useful decision, not a reason to relabel the experiment successful.

### 3. Prove reuse outside the demo, then attach demand

The smallest integration test is a separate client application that fetches a versioned artifact and uses it without relying on the demo UI. Start with an ordinary HTTP-facing adapter and a stable artifact/job contract. This tests whether Foundation can reduce work for another project without requiring its users to adopt the whole application.

After that works, give one existing demand counter a concrete consequence: above a threshold, schedule one preparation or replication job; verify the job completes and later requests actually use its result. Include a budget, deduplication, expiry, and cancellation so manufactured or vanished demand cannot cause unlimited work.

For video, test one pre-encoded clip's segments under increasing demand. Compare automatic preparation/replication and request coalescing against ordinary caching, with the same media quality. Measure origin traffic, total network traffic, preparation work, startup delay, and stalls. If broadcast or multicast is simulated, identify that explicitly. This tests one plausible demand mechanism; it does not settle the user's broader video design.

**Done:** one external consumer can reuse the resource; a subsequent demand experiment shows a real change in completed work and delivery cost. Two independently operated nodes exchanging the same artifact contract are the next federation gate, not a prerequisite for the first proof.

## Outside resources with the highest likely return

| Resource | Concrete use | Boundary |
| --- | --- | --- |
| One potential adopter with a repetitive content workload | Supply representative records, update frequency, request/reuse patterns, and a definition of useful savings | Highest-priority external input; no one was contacted for this review |
| One borrowed modest device | Measure job duration, memory, responsiveness, interruption, and the benefit of reusing artifacts | Hardware evidence must precede broad weak-device claims; no purchase needed to start |
| [Zstandard](https://facebook.github.io/zstd/#small-data) | Ready-made dictionary training and decoding for the first experiment | A comparison tool and candidate component, not proof of Foundation's novelty |
| [RFC 9842: Compression Dictionary Transport](https://www.rfc-editor.org/rfc/rfc9842.html) | Study existing HTTP dictionary negotiation, identification, caching, and compatibility rules | A reference for a later web adapter; do not assume a trained Zstd dictionary is directly its raw-dictionary wire format, or that this supplies cross-network federation |
| [BOINC volunteer-computing design](https://boinc.berkeley.edu/boinc_papers/crossroads.pdf) | Learn from replicated validation, heterogeneous devices, and the cost of verification | Reuse design lessons; installing a second compute platform is unnecessary for the first proof |

Once a real result exists, seek one focused review from a compression or distributed-computing practitioner. Give them the corpus description, baseline, job contract, and full cost accounting. That is a more concrete external request than asking someone to assess the entire protocol vision.

## Scope discipline

Defer a new codec, model training, a new consensus design, economic expansion, server decomposition, broad SDK work, and multiple bridges until an experiment identifies a need. Keep video scaling and independently built networks visible as intended outcomes.

The immediate next action is the bounded reliability pass, followed by the three-configuration shared-resource experiment. Keep a separate gate for each claim: a working artifact, a useful shared artifact, useful pooled construction, useful weak-device participation, and useful demand-driven delivery.
