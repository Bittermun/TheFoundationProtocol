---
name: tfp-review-and-gate
description: Runs TheFoundationProtocol's AST code graph impact analysis, 4-stage quality/security gate (Ruff, Mypy, Bandit, Pytest), and dispatches parallel Gemini Pro reviewer subagents for cryptography, async transport/DSP, and governance verification.
---

# TheFoundationProtocol — AST Impact Analysis, Quality Gate & Subagent Review Fleet

Use this skill before completing any non-trivial change in `TheFoundationProtocol`, or whenever the user asks for an independent operational/technical review.

## Step 1 — AST Code Graph Blast Radius & Snapshot Sync

1. For every modified class or function `<Symbol>`, query the deterministic AST code graph:
   ```powershell
   .\.dist_verify\runtime\Scripts\python.exe scripts/code_graph.py --query <Symbol>
   ```
2. Run all unit test files listed under `covered_by_tests` in the query output:
   ```powershell
   .\.dist_verify\runtime\Scripts\python.exe -m pytest <test_files...> -q
   ```
3. If any Python symbols, arguments, return types, or files were added/renamed/removed, regenerate `CODE_GRAPH_SNAPSHOT.json`:
   ```powershell
   .\.dist_verify\runtime\Scripts\python.exe scripts/code_graph.py --json
   ```

## Step 2 — Run the 4-Stage Automated Agent Gate

Execute the repository's official quality & security gate:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/agent/run_agent_gate.ps1
```
Verify all 4 stages pass with exit code `0`:
- `[1/4]` Ruff (`E4,E7,E9,F`)
- `[2/4]` Mypy (`tfp-foundation-protocol`)
- `[3/4]` Bandit security audit (`bandit.ini`)
- `[4/4]` Pytest reliability & tooling isolation suite

## Step 3 — Parallel Pro Subagent Review Fleet (For Non-Technical Operator Confidence)

When completing a feature or when requested by the user, dispatch up to 3 read-only `research` subagents (`Model: "pro"`) in parallel via `invoke_subagent`:

1. **Cryptography, Trust & Byzantine Safety Auditor**:
   - Checks Ed25519 signature verification, constant-time comparisons (`hmac.compare_digest`), CSPRNG usage (`secrets`), quarantine of unverified acoustic/network frames, and `.ast-grep/rules/` invariants.
2. **Async Concurrency, Transport & Acoustic DSP Reviewer**:
   - Checks for blocking calls in `async def`, untracked `asyncio.create_task`, network timeouts, and (if `tfp_demo/static/` changed) AudioWorklet buffer reuse, bounded queues, and Service Worker offline cache lists.
3. **Test Coverage & Governance Gate Auditor**:
   - Verifies that new branches and failure modes have deterministic unit/property tests and that `CODE_GRAPH_SNAPSHOT.json` is up to date.

Fix any **Critical** or **Important** findings via TDD and re-run Step 2 before reporting completion.
