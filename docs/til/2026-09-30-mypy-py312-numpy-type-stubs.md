# TIL: `mypy` `python_version = "3.11"` Fails on Python 3.12 NumPy `.pyi` `type` Statements and Masks Downstream Type Bugs

## Problem / Symptom
Running `mypy tfp-foundation-protocol --ignore-missing-imports` inside the `.dist_verify/runtime` virtual environment (Python `3.12.14`) immediately aborted with exit code `2`:
```text
.dist_verify\runtime\Lib\site-packages\numpy\__init__.pyi:737: error: Type statement is only supported in Python 3.12 and greater  [syntax]
Found 1 error in 1 file (errors prevented further checking)
```
Because `mypy` halted at syntax parsing inside `numpy/__init__.pyi`, it never type-checked the 197 project source files.

## Root Cause & Minimal Reproduction / Fix
`pyproject.toml` specified `python_version = "3.11"` under `[tool.mypy]`, while the virtual environment installed `numpy` wheels targeting Python `3.12` whose `.pyi` stub files use PEP 695 `type X = ...` syntax introduced in Python 3.12.

Updating `[tool.mypy]` in `pyproject.toml`:
```toml
[tool.mypy]
python_version = "3.12"
```
unblocked full type checking across all 197 files and immediately caught:
1. A silent runtime bug in `tfp-foundation-protocol/tfp_client/lib/media/live_streamer.py:231-232`, where `receiver._droplet_buffers.get(pkt.chunk_index, {})` passed an `int` instead of `(pkt.session_id, pkt.chunk_index)`, causing `droplet_recv` telemetry to report `rank = 0` on every intermediate droplet.
2. When running `ruff check --select F401 --fix`, adapter facade modules (`tfp_client/lib/ndn/adapter.py` and `tfp_client/lib/lexicon/adapter.py`) that re-export types (`Data`, `Interest`, `Content`) must declare `__all__` explicitly; otherwise Ruff strips the re-exports and `mypy` catches downstream `[attr-defined]` errors.

## Verification Command
```powershell
.\.dist_verify\runtime\Scripts\python.exe -m mypy tfp-foundation-protocol --ignore-missing-imports
.\.dist_verify\runtime\Scripts\python.exe -m pytest tests/test_live_file_streaming.py -v
```
