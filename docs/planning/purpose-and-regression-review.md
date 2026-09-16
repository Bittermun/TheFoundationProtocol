# Purpose preservation and downside review

2026-09-15. This review addresses the user's request to prevent regressions, loss of intended capabilities, and misleading instructions to future agents. It is a focused inspection, not certification that every component is correct.

## Highest-consequence risks

| Risk | Why it could hurt Foundation | Action / boundary |
| --- | --- | --- |
| A prototype substitutes for the intended product | A polished notebook or dictionary benchmark could displace pooled computation, weak-device participation, video demand, and independent networks | Root `AGENTS.md` preserves all mission outcomes and identifies which demonstrations do not establish them. Existing modules are retained. |
| One negative experiment becomes a verdict on Lexicon | The 6.1% proxy result could cause premature abandonment or optimization of the wrong representation | Candidate failure is now separate from W04 packet status. No integrated Lexicon result or ceiling is claimed; do not lower the frozen threshold or tune against held-out records. |
| False success hides missing work | Empty CLI commands and local repair loops can appear to prove a functioning network | v4 fetch/inspect now fail explicitly; publish states that storage is ephemeral; verify states its local repair scope and uses a real failure check even under optimized Python. The misnamed telemetry and genuine transport implementation still need W01. |
| Local credits masquerade as proof of useful work | Rewarding all agreeing participants can increase issuance while expected answers remain public | Keep recoverable accounting, but do not claim worker honesty, useful output, Sybil resistance, or distributed supply control. Demo `earn` help now states that it is an allowance, not compute. |
| A local launcher silently narrows integration testing | The new launcher deliberately disables bridges, RAG, and real adapters | Retain its predictable demo behavior; require separately configured integration checks before network claims. Do not remove the underlying integration paths to make tests simpler. |
| Repair and audit work consumes the project | Repeated broad checks and new documentation can delay the central useful-output mechanism indefinitely | Bound repair work to material defects or blockers. Use scoped tests during changes and full/distribution gates at meaningful checkpoints; avoid repeated identical checks with no new uncertainty. |
| Partial evidence gets promoted into completion | A passing browser journey may bypass Lexicon; test counts may predate source changes; a local check is not CI | Evidence is dated and scoped. Current code/evidence and user intent outrank the board. CI's lint scope now includes the whole repository, including newly added scripts. |
| Root/nested package confusion causes repair of the wrong code | Editable installs or old wheels can mask source behavior | Document the root build, actual server path, and installed-wheel check outside the checkout. Retain the separate research CLI but label its limits. |

## Tradeoffs in recent additions

- **Reward entitlements:** fixes loss/duplication across retries and process failure. It follows the existing requirement to pay all qualifying participants, so total payout differs from the previous last-submitter-only bug. No historical backfill is inferred. A database rollback to old software after new entitlements exist needs a deliberate migration review, not a blind checkout reset.
- **Detached credit transactions:** protect cached balances from failed writes. They copy state and serialize local updates. This trades memory/throughput for local consistency; no multi-process or distributed throughput claim is supported. Profile actual contention before replacing the locking strategy.
- **Hybrid-wallet transfers:** now conserve local balances and return their documented result. They remain simulations that create a new recipient wallet. They must not be exposed as authenticated peer payments without a separate design.
- **Pinned search model and instance-local loading:** prevent mutable revisions and wrong-model reuse. Separate instances may use more memory than the old global cache; do not create one model per request. A future shared cache must key by full model identity, and a changed embedding model requires a compatible/rebuilt index.
- **Optional experiment dependencies:** Zstandard and psutil stay in the `experiments` extra, outside the base demo. The experiment adds no production codec, scheduler, or automatic model download. It is a screening tool only.
- **Process and browser checks:** exercise real server paths; failure-injection cases deliberately substitute errors. These tests are useful evidence, but not physical-device, deployed-network, or permissionless-economy evidence.
- **Root packaging and wider CI:** improve reproducibility but do not establish all optional backends are installed or exercised. Keep missing-service behavior visible. Remote CI and Docker remain unverified.

## Remaining negatives to prevent during implementation

1. Do not fetch or activate shared artifacts without checking identity, compatibility, dependencies, and the authority selecting the version. Keep old versions available for retained content and offline recovery. The existing HLT probe failures remain open.
2. Do not declare savings from hashes, reused chunk counts, warm caches alone, or sender data secretly available to the receiver. Count distribution, updates, invalid results, repairs, and verification; separate CPU, latency, memory, and energy.
3. Do not pay for merely copying the public expected hash and call it useful execution. The next worker contract needs actual validated output bytes consumed by another client.
4. Do not claim arbitrary project execution is safely isolated while sandbox fallback/timeout behavior remains unproved. Preserve the user's ability to choose projects and device budgets.
5. Do not treat unchanged/incomplete components as justification to delete the wider ambition. A failed candidate should change the next experiment, not silently change the objective.
6. Do not let an unpublished local worktree become the only handoff mechanism. Preserve source/tests/docs together in a reviewed checkpoint before distribution; exclude credentials, databases, environments, and raw machine-specific files. No commit or push has been claimed here.

## Verification of this review's changes

Three new command regressions failed before the fix and pass afterward: unsupported v4 fetch/inspect must fail explicitly, and `ping` must work with an ASCII console. Whole-repository Ruff passes. Documentation changes align the mission, scope of the 6.1% result, and packet/candidate status. The review did not remove a subsystem or change the frozen experiment result. A new full suite, final wheel, Docker run, and remote CI are not claimed for this small follow-up.
