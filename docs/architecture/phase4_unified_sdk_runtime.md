# The Foundation Protocol (TFP): Phase 4 — Unified SDK & Sandboxed Runtime Specification

**Document Classification:** Publication-Grade Architectural Specification & Developer Runtime Standard  
**Document Version:** 4.4.0-SDK-SPEC  
**Target Platform:** The Foundation Protocol (TFP) Client SDK & Plugin Sandboxed Runtime Engine  
**Working Group:** Developer Experience, SDK Engineering & Security Sandbox Working Group  
**Date of Release:** August 2026  
**Status:** Approved for Implementation  

---

## 1. Executive Summary & Developer Runtime Scope

Phase 4 of The Foundation Protocol (TFP) establishes the unified developer experience and the secure edge-compute execution runtime:
1. **Isomorphic Typed `tfp-sdk`**: A high-performance, developer-friendly client library available across asynchronous (`AsyncTFPClient`) and synchronous (`TFPClient`) execution models, handling FastCDC chunking, PQC signature verification, connection pooling, and multi-node failover transparently.
2. **Capability-Gated Sandboxed Plugin Runtime (`tfp_plugin_engine`)**: A zero-trust execution engine running untrusted edge-compute plugins inside WebAssembly (`wasmtime`) and isolated gRPC subprocess sandboxes with strict memory quotas (64 MB), execution timeouts (250 ms), and syscall trap interceptors.

---

## 2. Isomorphic Typed `tfp-sdk` Client Architecture

```
                  +--------------------------------------------------+
                  |                     tfp-sdk                      |
                  +--------------------------------------------------+
                                   /                \
                                  /                  \
                                 ▼                    ▼
               +--------------------+      +-----------------------+
               |     TFPClient      |      |     AsyncTFPClient    |
               | (Synchronous API)  |      |   (AsyncIO / Native)  |
               +--------------------+      +-----------------------+
                         │                             │
                         ▼                             ▼
               +---------------------------------------------------+
               |             Unified SDK Core Engine               |
               | - Client-side FastCDC 64-bit Chunking             |
               | - Transparent Tier 1 PQC Signature Validation     |
               | - Connection Pool & HTTP/2 Multiplexing           |
               | - Circuit Breaker & Exponential Jitter Retries    |
               | - Streaming Rateless Fountain Codec Assembler     |
               +---------------------------------------------------+
```

### 2.1 Core Client API Signatures (Python Typed Specification)

```python
from typing import Optional, List, Dict, Any, AsyncIterator, Iterator
from dataclasses import dataclass

@dataclass(frozen=True)
class SDKConfig:
    node_endpoints: List[str]               # e.g., ["http://node1.tfp.net", "http://node2.tfp.net"]
    identity_path: Optional[str] = None     # Path to encrypted ~/.tfp/identity.enc
    passphrase: Optional[str] = None        # Identity decrypt passphrase
    pqc_algorithm: str = "dilithium5"       # Default PQC manifest algorithm
    connection_pool_size: int = 20
    request_timeout_seconds: float = 10.0
    max_retries: int = 3
    circuit_breaker_threshold: int = 5

class AsyncTFPClient:
    def __init__(self, config: SDKConfig) -> None: ...
    
    async def publish(
        self,
        data: bytes,
        content_type: str = "application/octet-stream",
        tags: Optional[List[str]] = None,
        dual_sign: bool = True
    ) -> Dict[str, Any]:
        """
        Executes client-side FastCDC 64-bit chunking, derives SHA3-256 Merkle root,
        signs manifest via ML-DSA-87/Ed25519, and broadcasts to optimal node pool.
        """
        ...

    async def get(self, root_hash: str) -> bytes:
        """
        Retrieves ChunkRecipe manifest, verifies PQC signature, fetches chunks
        concurrently with Merkle proof validation, and returns bit-exact payload.
        """
        ...

    async def stream(self, root_hash: str) -> AsyncIterator[bytes]:
        """
        Connects to rateless fountain droplet stream, verifies PRF seed schedule,
        executes incremental Gaussian decoding, and yields chunks as reconstructed.
        """
        ...

    async def earn_task(self, task_id: str, compute_func: Any) -> Dict[str, Any]:
        """
        Executes edge-compute task in sandboxed environment, derives HABP proof,
        and submits for 3/5 consensus credit minting.
        """
        ...

class TFPClient:
    """Synchronous blocking wrapper around AsyncTFPClient for scripting and CLI."""
    def __init__(self, config: SDKConfig) -> None: ...
    def publish(self, data: bytes, **kwargs: Any) -> Dict[str, Any]: ...
    def get(self, root_hash: str) -> bytes: ...
    def stream(self, root_hash: str) -> Iterator[bytes]: ...
```

### 2.2 Fault Tolerance: Circuit Breaking & Exponential Jitter Retries
The SDK manages multi-endpoint failover through an active circuit breaker state machine:
- **Closed**: Requests routed normally to healthy node endpoints.
- **Open**: Endpoint marked unhealthy after 5 consecutive failures ($5xx$ or timeout); traffic diverted to secondary endpoints.
- **Half-Open**: Periodic canary request sent after 30 seconds to test endpoint recovery.
- **Backoff Formula**: $T_{wait} = \min(T_{max}, T_{base} \cdot 2^{attempt}) + \text{Uniform}(0, \text{Jitter})$.

---

## 3. Capability-Gated Sandboxed Plugin Runtime (`tfp_plugin_engine`)

To allow decentralized developers to deploy custom content filters, routing transformations, and HABP edge-compute tasks without risking node compromise, TFP specifies a capability-gated execution sandbox.

```
+----------------------------------------------------------------------------------------------------+
|                                    WASM PLUGIN SANDBOX RUNTIME                                     |
+----------------------------------------------------------------------------------------------------+
|                                                                                                    |
|   [ Plugin Manifest (plugin.yaml) ]                                                                |
|     ├── Declares required permissions: network, storage quota, compute timeout                     |
|     └── Node Security Policy verifies signature and capability bounds                              |
|                                                                                                    |
|   [ Wasmtime Linear Memory Sandbox ]                                                               |
|     ├── Hardware memory limit: strictly capped at 64 MB                                            |
|     ├── Execution timeout guard: interrupt trigger fires at 250 ms                                 |
|     └── Custom WASI Import Table: intercepts illegal syscalls & file system access                 |
|                                                                                                    |
|   [ Event Interception Pipeline ]                                                                  |
|     ├── ON_CONTENT_INGEST     : Transform / filter content blobs before indexing                   |
|     ├── ON_SHARD_RECEIVED     : Inspect / forward raw transport shards                             |
|     ├── ON_TASK_BID           : Autonomous bidding on HABP edge-compute tasks                      |
|     └── ON_ACCESS_REQUEST     : Evaluate dynamic zero-trust access control policies                |
|                                                                                                    |
+----------------------------------------------------------------------------------------------------+
```

### 3.1 Declarative Plugin Capability Manifest (`plugin.yaml`)

```yaml
plugin:
  name: "tfp-video-transcoder"
  version: "1.2.0"
  runtime: "wasm"                    # "wasm" (in-process) or "grpc" (isolated subprocess)
  entrypoint: "transcoder.wasm"
  author_did: "did:tfp:8f9a...3c12"
  signature: "4a2b...99e1"           # Signed by author BIP-39 / Dilithium5 key

capabilities:
  network:
    allow_outbound: false            # Outbound raw sockets strictly prohibited
    whitelisted_hosts: []
  storage:
    max_kv_quota_bytes: 10485760     # 10 MB maximum key-value quota
    allow_persistent_state: true
  system:
    max_memory_bytes: 67108864       # 64 MB hardware RAM cap
    max_execution_ms: 250            # 250 ms execution deadline
    allow_random: true               # Access to CSPRNG getrandom
    allow_system_time: true          # Read-only UTC clock access
    allow_filesystem: false          # Host filesystem access completely denied
    allow_subprocesses: false        # Subprocess spawning blocked

event_hooks:
  - ON_CONTENT_INGEST
  - ON_TASK_BID
```

### 3.2 In-Process WebAssembly Isolation (`wasmtime`)

The WASM runner leverages `wasmtime` with memory bounds and execution epoch interruptions:
1. **Linear Memory Clamping**: Linear memory is initialized with `MemoryType::new(1, Some(1024))` (max 64 MB). Any attempt by the plugin to grow memory beyond 64 MB triggers an immediate `MemoryQuotaExceeded` trap.
2. **Epoch-Based Execution Interruption**: A background timer advances the engine epoch every 10 ms. The execution context is configured with `epoch_deadline = 25` (250 ms). If execution exceeds 250 ms, the WASM virtual machine halts with `ExecutionTimeoutTrap`.
3. **WASI Syscall Interception**: The WASI import table provides stubs only for `clock_time_get` and `random_get`. Syscalls such as `path_open`, `sock_send`, or `proc_exec` return `WASI_EACCES` (Permission Denied).

### 3.3 Out-of-Process gRPC Sandbox (Linux `seccomp-bpf` & `cgroups v2`)

For complex non-WASM plugins (e.g. C/C++ or Python native runtimes):
- **Isolation Boundary**: Runs as an unprivileged child process communicating over a dedicated Unix Domain Socket.
- **cgroups v2 Enforcement**: `cpu.max = 50000 100000` (max 0.5 CPU core) and `memory.max = 67108864` (64 MB RAM limit).
- **seccomp-bpf Filter**: Prohibits all syscalls except `read`, `write`, `epoll_wait`, `nanosleep`, `futex`, and `exit_group`. Attempts to invoke `clone`, `fork`, `execve`, or `connect` trigger immediate `SIGSYS` process termination.

---

## 4. Plugin Event Lifecycle & Hook Pipeline

```
+----------------------------------------------------------------------------------------------------+
|                                  PLUGIN EVENT HOOK PIPELINE                                        |
+----------------------------------------------------------------------------------------------------+
| Hook Name            | Execution Context          | Input Parameters        | Output / Action      |
+----------------------+----------------------------+-------------------------+----------------------+
| ON_CONTENT_INGEST    | Prior to FastCDC chunking  | Raw Payload, ContentType| Transformed Payload  |
| ON_SHARD_RECEIVED    | Ingress Transport Stream   | Shard Header, Raw Data  | Forward / Drop Flag  |
| ON_TASK_BID          | HABP Task Announcement     | TaskID, RewardDWCC      | Bid Struct / Pass    |
| ON_ACCESS_REQUEST    | HTTP / NDN Route Ingress   | Caller DID, Route Path  | Allow / Deny Policy  |
+----------------------+----------------------------+-------------------------+----------------------+
```

---
*Authored by the Protocol Architecture & Audit Working Group.*
