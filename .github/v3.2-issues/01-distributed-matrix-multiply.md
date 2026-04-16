# [v3.2.0-alpha] Implement Distributed Matrix Multiply Task

## Goal
Enable pooled compute by distributing matrix multiplication across multiple devices, with each device computing a subset of the result matrix.

## Background
Current `MATRIX_VERIFY` tasks verify pre-computed results. This issue implements actual distributed computation where:
- Large matrix C = A × B is split into shards
- Each device computes a shard
- Results are aggregated and verified via HABP consensus

## Technical Scope

### Phase 1: Task Sharding (Complexity: Medium)
**File:** `tfp-foundation-protocol/tfp_client/lib/compute/task_sharding.py` (new)

Implement matrix splitting:
```python
@dataclass
class MatrixShardTask:
    shard_id: str
    parent_task_id: str
    row_range: Tuple[int, int]  # e.g., (0, 100) for first 100 rows
    col_range: Tuple[int, int]
    matrix_a_rows: List[List[int]]  # Subset of matrix A
    matrix_b: List[List[int]]       # Full matrix B (read-only, cached)
```

### Phase 2: Shard Distribution (Complexity: High)
**Files:**
- `tfp_demo/server.py` — modify `/api/task` to generate shard sub-tasks
- `tfp_client/lib/core/tfp_engine.py` — handle shard aggregation

Changes needed:
1. Server generates N shard tasks from parent task
2. Each shard has `credit_reward = parent_reward / N`
3. Devices claim shards via new endpoint `POST /api/task/{id}/claim`
4. Aggregation endpoint `POST /api/task/{id}/aggregate` collects results
5. HABP consensus runs on final assembled matrix

### Phase 3: Worker Pool Coordination (Complexity: High)
**File:** `tfp-foundation-protocol/tfp_client/lib/compute/worker_pool.py` (new)

Implement:
```python
class WorkerPool:
    def __init__(self, device_id: str, api_endpoint: str):
        self.device_id = device_id
        self.api = api_endpoint

    def join_pool(self, capabilities: DeviceCapabilities):
        """Register device with its compute capacity."""

    def poll_shard_tasks(self) -> Optional[MatrixShardTask]:
        """Poll for available shards matching device capability."""

    def submit_shard_result(self, shard_id: str, result: Matrix) -> Receipt:
        """Submit computed shard, receive partial credit receipt."""
```

## Acceptance Criteria
- [ ] Can split 1000×1000 matrix into 10 shards of 100 rows each
- [ ] 3+ devices can claim and compute shards simultaneously
- [ ] Results aggregate correctly into final matrix C
- [ ] HABP consensus passes (3/5 devices agree on C)
- [ ] Credits distributed proportionally by rows computed
- [ ] If device fails, shard is reassigned to another device
- [ ] 10-node testbed demonstrates distributed matrix multiply

## API Changes

New endpoints:
```
POST /api/task/{id}/claim          # Device claims a shard
POST /api/task/{id}/shard-result   # Submit shard computation
GET  /api/task/{id}/shards          # List shard statuses
POST /api/task/{id}/aggregate       # Finalize and verify
```

## Database Schema Addition
```sql
CREATE TABLE task_shards (
    shard_id TEXT PRIMARY KEY,
    parent_task_id TEXT,
    row_start INTEGER,
    row_end INTEGER,
    assigned_device_id TEXT,
    status TEXT CHECK(status IN ('pending', 'claimed', 'completed', 'failed')),
    result_hash TEXT,
    claimed_at REAL,
    completed_at REAL,
    FOREIGN KEY (parent_task_id) REFERENCES tasks(task_id)
);
```

## Depends On
- #30 (Add `--version` flag to CLI) — not strictly required but good first contributor warmup

## Good First Sub-Issues
1. **Matrix splitting algorithm** — Write `split_matrix(A, B, num_shards)` function with tests
2. **Shard status tracker** — Implement SQLite schema and basic CRUD
3. **Worker pool CLI command** — `tfp worker --pool http://localhost:8000`

## Estimated Effort
- Senior contributor: 2-3 weeks
- Multiple contributors parallelizing sub-issues: 1 week

## Priority
**P0** — Blocks v3.2.0-alpha, core pooled compute functionality

---

## Discussion Points

**Q: How large should matrices be to justify distribution?**
A: Start with 500×500 minimum (250k multiply-adds). Below this, overhead exceeds benefit.

**Q: What if matrix B doesn't fit in device memory?**
A: Phase 2 can implement streaming — device fetches B in chunks. Document as follow-up issue.

**Q: Security implications of partial results?**
A: Each shard result is hashed; HABP consensus requires full re-assembly. No new trust assumptions.
