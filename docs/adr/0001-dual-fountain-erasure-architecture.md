# ADR 0001: Dual Fountain Erasure Architecture (`BinaryLinearErasureCodec` vs. `FountainStreamer`)

## Status
Accepted

## Context
`TheFoundationProtocol` disseminates content-defined chunks across both small-block storage/mesh swarms (`tfp_core_v4`) and continuous unidirectional acoustic/radio broadcast streams (`tfp_client/lib/media/`). Small deterministic storage blocks require guaranteed zero-overhead recovery after exactly $k$ symbols, whereas one-way acoustic/UDP broadcasts require rateless Luby Transform (LT) soliton repair droplets with session-scoped `(session_id, chunk_index)` multiplexing and checkpointing.

## Decision
Maintain two complementary erasure engines with explicit domain boundaries:
1. **`BinaryLinearErasureCodec` / `FountainCodec` (`tfp_core_v4/fountain.py`)**: Systematic $\text{GF}(2)$ Cauchy/Soliton XOR erasure coding with Gaussian elimination for node-to-node chunk recovery and Merkle-verified swarm exchange.
2. **`FountainStreamer` & `FountainStreamReceiver` (`tfp-foundation-protocol/tfp_client/lib/media/`)**: Session-multiplexed rateless media streaming where internal receiver buffers (`_droplet_buffers`, `_chunk_meta`) are strictly keyed by `(session_id, chunk_index): Tuple[int, int]` and bounded by `max_sessions`, `max_chunks_per_session`, and `max_droplets_per_chunk`.

## Consequences
- **Easier**: Unidirectional audio/radio broadcasts can interleave multiple sessions and resume from disk checkpoints without cross-session chunk index collisions, while core node storage stays minimal and zero-dependency.
- **Harder / Invariants Required**: Any caller inspecting `FountainStreamReceiver` state (such as `LiveTransmissionEngine` in `live_streamer.py`) must index `_droplet_buffers` and `_chunk_meta` by the tuple `(pkt.session_id, pkt.chunk_index)` rather than bare `pkt.chunk_index`. Static type checking (`mypy` on Python 3.12+) is required in `run_agent_gate.ps1` to enforce this tuple key invariant.
