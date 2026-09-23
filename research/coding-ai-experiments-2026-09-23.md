# Coding-AI guidance: test the boundaries before combining systems

September 23, 2026. Companion to the [opportunity scan](opportunity-scan-2026-09-22.md).

Explore the opportunities through bounded experiments. Treat existing stubs, comments, and advertised capabilities as things to verify. The objective is to find which assumptions hold, where integration is practical, and which ideas should stop before they become unnecessary infrastructure.

## Distinctions to preserve

| Distinction | Consequence for implementation and evaluation |
|---|---|
| Identity, authenticity, trust, and safety | A matching hash establishes byte identity. A valid signature establishes that a key signed a statement. Trusting that key and authorizing its action are policy decisions. None of these alone establishes safe content. |
| Content and representation | Plaintext, ciphertext, compressed archives, chunks, and manifests have different identities. Specify which object each signature, advisory, entitlement, and receipt covers. |
| Advisory and enforcement | Warning, refusing storage, refusing relay, and refusing execution are different actions. Test them separately and explain the decision to the operator. |
| Historical validity and current authorization | A correctly signed release may later be withdrawn. A disconnected receiver cannot learn a revocation it has never received; make its last-known state and uncertainty visible. |
| Delivery and successful use | Receiving, verifying, installing, booting, and successfully loading a model are separate milestones. A receipt must state which one it reports. |
| Local atomicity and distributed agreement | A local database transaction cannot make payment, remote delivery, and remote activation one atomic operation. Model independent records and recovery. |
| Computation and economic value | Expensive work need not be useful; useful work need not be cheaply verifiable or worth buying. Identify an output, buyer, and acceptance rule. |
| Entitlement and copy control | A grant can authorize key delivery. It cannot reliably revoke plaintext already obtained. |
| Simulation and physical evidence | Generated packets, process termination, and synthetic audio answer narrower questions than device power loss, real radio links, or physical field deployment. Label the evidence accordingly. |

## Ordered experiments

### 1. Map the actual implementation

Trace publication, transport, reconstruction, verification, storage, and use. Label each stage implemented, stubbed, tested, or unknown, citing the relevant code and tests. Identify adapter boundaries that can preserve the wire protocol.

Start by inspecting `tfp_core_v4/node.py`, `tfp_core_v4/bulletin_identity.py`, `tfp_security/heuristic/behavioral_engine.py`, and `tfp_plugins/access_control/license_manager.py`. These are investigation entry points, not a claim that all required functionality exists there. Recheck the code at the revision used for the experiment.

Deliverable: a short capability map with evidence, missing behaviors, and one proposed integration seam per experiment.

### 2. Build an interruption harness

Prioritize this as shared infrastructure for later experiments. Interrupt transfer or update processing after each persisted transition, then restart. Exercise duplicate messages, disk exhaustion, corrupt chunks, conflicting versions, and acknowledgment loss.

Record what survives, whether retries repeat side effects, and whether inconsistent content becomes visible. Test the persistence boundary before claiming durability. Distinguish process-termination tests from physical power-loss guarantees. Use disposable fixtures for fault injection.

Deliverable: reproducible failure scenarios, observed state transitions, and explicit recovery invariants. A failed recovery should be a visible result rather than silently retried until the test passes.

### 3. Prototype two independent security feeds

Include contradictory assertions, withdrawn entries, stale metadata, key rotation, and local overrides. Exercise forged signatures and replayed versions. Show the issuer, affected identifier, applied policy, and reason for each decision.

Test whether a shared-chunk rule unexpectedly affects unrelated objects. Define whether an entry addresses a complete object, manifest, path, or chunk. Unknown and stale must remain distinct from approved.

Deliverable: a small opt-in feed prototype and a decision table covering disagreement, expiration, and overrides.

### 4. Measure real model-transfer reuse

Compare related checkpoints, quantized variants, and base-plus-adapter bundles. Measure transferred bytes, peak memory, temporary disk use, and recovery time against a straightforward resumable download under the same conditions.

Pin complete bundles, including weights, tokenizer, configuration, and exact base-model identity. Measure actual byte reuse; do not infer savings from parameter counts. Verify both native upstream identifiers and TFP identifiers where applicable.

Deliverable: commands, artifact versions, channel conditions, raw measurements, and a comparison. If the approach is slower or uses more memory, preserve that result.

### 5. Implement a transaction simulator

Model payment accepted, entitlement issued, bytes received, and activation confirmed as separate durable records. Use simulated payment events initially. Reorder and duplicate events, and restart between transitions.

Demonstrate recovery when payment succeeds but delivery fails, and when delivery succeeds but its acknowledgment is lost. Bind retries to a stable operation identifier. State what is trusted about a receiver's report; a signed report does not itself prove honest execution.

Deliverable: state transitions, duplicate-event handling, reconciliation behavior, and explicit refund or credit policy choices. Do not describe the whole workflow as exactly-once without defining and demonstrating the scope of that claim.

### 6. Test one useful-compute job

Choose a specific buyer-valued output and acceptance rule. Begin with a bounded, sandboxed workload and explicit resource limits. Measure honest execution, verification, fabricated results, duplicate submissions, retries, and coordination overhead.

Track reader energy and latency separately from publisher costs. Stop or revise the idea if verification and coordination consume the proposed benefit, or if there is no credible buyer for the output. Do not treat proof-of-work puzzles or volunteer-computing credits as demonstrated revenue.

Deliverable: measured unit economics with assumptions separated from observed costs, plus a continue/revise/stop recommendation.

## Ambitious follow-on questions

- Can a receiver advertise missing content without exposing its entire library?
- Can relays earn compensation without rewarding fabricated or self-generated demand?
- Can small adapters deliver useful model improvements while retaining an exact, verified base?
- Can software, model, and tokenizer versions activate together without mixed-version states?
- Can community-funded release cover costs while leaving readers anonymous?

Each question needs its own falsifiable hypothesis before implementation. A useful answer can be a counterexample or an experiment that rules an idea out.

## Evidence and handoff contract

For each experiment, record the hypothesis, repository revision, smallest prototype, baseline, relevant environment, reproducible procedure, raw results, failure cases, and recommendation. Separate observed behavior from assumptions and proposed designs.

Use meaningful tests for security, persistence, retry behavior, and correctness. Avoid tests that merely repeat the implementation. Run checks appropriate to the changed behavior; do not claim a documentation-only change validates a runtime feature.

Keep experiments independently reviewable. Describe any wire-format, trust-policy, dependency, or compatibility change explicitly. A negative result that prevents unnecessary infrastructure is a successful research outcome.
