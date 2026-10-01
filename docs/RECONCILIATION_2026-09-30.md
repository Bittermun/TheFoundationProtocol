# Branch reconciliation, September 30, 2026

`main` is the integration base. The current acoustic receiver repair and the dated opportunity research are combined in `codex/reconcile-foundation-2026-09-30`. No historical branch is a second source of truth.

## Historical work

- `codex/receiver-reliability` and `feat/device-to-phone-broadcast-baseline` both pointed to `e68ef98`. Their changes are integrated once.
- `codex/research-opportunities-and-experiments` supplies dated research. Its proposals are hypotheses, not implemented capability claims.
- `codex/identity-receiver-package` (`73b5ff8`) largely reappears in `65b5225`, with further manifest admission and integrity hardening. Its older receiver implementation is not restored.
- `codex/bulletin-acceptance-recovery` (`d243848`) largely reappears in `f8122d7`; later commits extend migration, watermark, recovery, and browser trust behavior. Its old workflow is not restored.
- `feature/fastcdc-implementation` introduces an alternative `tfp_transport/cdc.py` and template descriptor. Current `tfp_core_v4/cdc.py`, media packaging, and their property/adversarial tests are the maintained implementation. The alternative and its benchmark claims are retired rather than merged.
- `fix/test-failures-ci-cleanup` contains two patches already represented in main. Re-merging it would conflict with newer files without adding a justified fix.
- `postgresdev` changes header extraction and reduces publish text limits. Current handlers already use optional headers with explicit validation/error handling. The old 20,000-character limit would change the current 10 MB contract; that change is not adopted without a present requirement.
- `reactapp`, `copilot/update-react-app-production`, and `ci-opensource-readiness` are ancestors of main and need no integration.
- Dependency proposals are separate maintenance work; old dependency branches are not evidence that their versions fit the current package manifests.

Recoverable original branch refs are retained locally under `refs/codex-backup/2026-09-30/`. Existing clean historical worktrees may be parked on archived branch names after integration. No recordings or datasets are deleted by this reconciliation.

## Validation policy

Reconciliation does not establish real-phone microphone performance or research accuracy. Receiver trust, transferred-buffer handling, offline upgrade/cold reopen, recovery bounds, wheel installation, and the repository quality gate must be verified on the integrated tree.

CI setup must install the dependencies imported by the collected suites. Lint follows the documented `E4,E7,E9,F` gate and excludes unmigrated mock UI/testbed/simulator trees; actual correctness errors in maintained code must be repaired, not hidden by general exclusions.
