# Foundation: preserve the mission and evidence

Read `AI_HANDOFF.md` for the user's intended mechanisms, then the latest dated entries in `docs/planning/execution-review-2026-09-14.md` and `docs/planning/manual-and-mock-audit.md`. Inspect the current worktree before assuming a reported repair or test result is current. Do not repeat completed repairs solely because an older handoff lists them.

The goal is affordable useful contributed work improving reusable lexicon resources, benefiting modest devices and outside projects, with demand-directed video delivery and independently operated networks. The notebook demo and Zstandard experiment are partial demonstrations, not replacements for that goal. The final lexicon representation is unresolved; do not silently define it as abbreviation expansion or a single compression dictionary.

## Interpretation rules

- User instructions and the intended outcome govern scope. Code and reproducible evidence establish behavior. Plans and the execution board coordinate work; they cannot override either or prove their own completion.
- The 6.1% result is from one standalone dictionary experiment on project documentation, against independent Zstandard compression, with modeled application-byte costs. It is neither an integrated Foundation result nor a ceiling on Lexicon performance. Retain its failed candidate threshold; do not lower it after seeing results or retune on its held-out set.
- `RealLexiconAdapter` currently returns input bytes with metadata, and its semantic search is a placeholder. Class names such as `Real`, a successful demo, and a passing test suite do not establish the intended capability.
- Browser reads of locally stored content bypass Lexicon reconstruction. The demo launcher intentionally disables external bridges/RAG/real adapters. Do not use it to claim network interoperability, real adapter execution, or end-to-end Lexicon performance.
- The v4 local fetch helper can replenish simulated losses from its own droplet store. Its legacy `bandwidth_saved_pct` measures local chunk reuse, not observed traffic. Repair/control/resource delivery costs must be included in later measurements.
- Expected task output hashes remain public. Agreement and successful local accounting do not prove useful computation or resistance to dishonest workers. Rewards are experimental accounting, not evidence of resource utility or a distributed economy.
- `HybridWallet.transfer` creates a local simulated recipient; it is not a durable cross-node payment. The new reward-entitlement table does not retroactively backpay historical completed tasks.
- Current source spans root and nested Python trees. Root `setup.py` is the unified package build, root `tfp_cli` is the packaged CLI, and the server source is `tfp-foundation-protocol/tfp_demo/server.py`. Check imported paths and build the root package before diagnosing contradictory behavior.

## Work discipline

- Preserve the existing uncommitted source, assets, and tests. Do not reset or discard another session's work, delete old lexicon/network components because they are unfinished, or restore fabricated success to make a demonstration look complete.
- Fix discovered behavioral defects with a reproducing check. Never convert a crash, missing dependency, skipped action, or missing artifact into success. Missing optional services must be visible.
- Keep working tests and deployment checks, but bound adjacent cleanup. Prioritize completing a useful worker-to-artifact-to-consumer path and measuring its benefit; additional abstractions and repeated audits are not substitutes.
- Apply verification to the changed scope. Rebuild installed artifacts after runtime changes; distinguish prior full-suite results from subsequent focused checks. Report source, workload, environment, and limitations with performance claims.
- Preserve cold-start, compatibility, version retention, offline recovery, per-device budgets, user choice, and independently operated network policies. Do not trade them away for an easier benchmark win without surfacing the tradeoff.
- Keep experiment packages optional. Keep secrets, databases, virtual environments, raw local logs, and generated builds out of commits. Record reproducible commands and portable summaries for evidence otherwise stored under ignored `.dist_verify/`.
- A local green run is not remote CI or Docker validation. Completion requires the full user objective and applicable gates, not merely a green subset. Do not add automatic publishing or external messaging as a consequence of these notes.
