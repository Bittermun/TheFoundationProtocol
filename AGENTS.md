# TheFoundationProtocol — AI Agent Architecture & Operational Rules

## 1. Python Runtime & AST Code Graph First (Mandatory Before Reading Random Files)
- **Windows Python Runtime**: System `python` on Windows may point to a Microsoft Store alias. Always prefer `.dist_verify\runtime\Scripts\python.exe` (if missing, bootstrap once via `powershell -ExecutionPolicy Bypass -File scripts/agent/bootstrap_env.ps1`).
- **Surgical AST Symbol & Test Lookup (`scripts/code_graph.py`)**:
  Before grepping blindly across 247 production files and 4,272 symbols, query the deterministic AST graph:
  ```powershell
  .\.dist_verify\runtime\Scripts\python.exe scripts/code_graph.py --query <SymbolName>
  ```
  *Returns exact file/line definitions, docstrings, `callers`, `callees`, and `covered_by_tests` (every unit test exercising that symbol).*
- **Snapshot Maintenance**: Whenever you add, rename, or remove Python classes/functions, refresh `CODE_GRAPH_SNAPSHOT.json` before committing:
  ```powershell
  .\.dist_verify\runtime\Scripts\python.exe scripts/code_graph.py --json
  ```

## 2. Non-Negotiable Protocol, Crypto & Async Invariants (`.ast-grep/rules/` & `bandit.ini`)
1. **Cryptographic Hygiene**:
   - Always use `hmac.compare_digest()` for secret/digest comparisons (`constant-time-crypto-compare.yml`).
   - Never use Python's `random` module for keys, nonces, salts, or protocol IDs; use `secrets` or `os.urandom()` (`no-unshielded-random.yml`).
2. **Async & Concurrency Discipline**:
   - Never call blocking `time.sleep()` inside `async def` functions (`no-blocking-sleep-in-async.yml`); use `await asyncio.sleep()`.
   - Never spawn fire-and-forget `asyncio.create_task()` without storing the task reference and handling exceptions (`no-unhandled-async-task.yml`).
   - Always specify explicit `timeout=` on network/HTTP/socket operations (`no-unshielded-network-timeout.yml`).
3. **Production Cleanliness**:
   - Never import `unittest.mock` inside production packages (`no-mock-in-production.yml`).

## 3. Quality & Safety Gate (`scripts/agent/run_agent_gate.ps1`)
Before claiming any task is complete or committing changes, run:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/agent/run_agent_gate.ps1
```
This enforces:
1. **Ruff** (`E4,E7,E9,F`) across the repository
2. **Mypy** static type checking on `tfp-foundation-protocol`
3. **Bandit** security audit (`-c bandit.ini -r tfp-foundation-protocol -ll`)
4. **Pytest** reliability & tooling isolation suite (plus any `covered_by_tests` returned by `code_graph.py --query`)
