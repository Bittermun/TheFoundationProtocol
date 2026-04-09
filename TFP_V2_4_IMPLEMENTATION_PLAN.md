# TFP v2.4 Implementation Plan: Three Architectural Bridges

## 🎯 Executive Summary

**Goal**: Transform TFP from "broadcast download layer" → "uncensorable, discoverable, user-publishable, self-archiving digital commons"

**Current State**: v2.3 with 100 passing tests, strong security gates, working credit economy (compute-only)

**Target**: v2.4 with 3 architectural bridges (~1,500 LOC total)

---

## 📋 Bridge 1: Tag-Overlay Index (Discoverability)

### Problem
NDN routes by hash only (`/tfp/content/{hash}`). No way to discover content by topic/tag without central indexer.

### Solution
Lightweight decentralized metadata layer with weekly Merkle DAG broadcasts.

### Architecture

```
Naming Convention:
/tfp/archive/{domain}/{tag1}/{tag2}/.../{hash}
/tfp/meta/tag_index/{epoch_week}/{domain}

Data Structure:
tag_index_merkle_dag = {
    "epoch": 202501,  # ISO week
    "domain": "science",
    "entries": [
        {"tag": "physics", "hash": "abc123...", "popularity_score": 0.95},
        {"tag": "biology", "hash": "def456...", "popularity_score": 0.87}
    ],
    "merkle_root": "xyz789..."
}

Discovery Flow:
1. Device requests /tfp/meta/tag_index/{current_week}
2. Receives Bloom-filter compressed index
3. Queries locally for tags of interest
4. Extracts content hashes → requests via NDN Interest
```

### Implementation Plan

**Files to Create:**
1. `tfp_client/lib/metadata/tag_index.py` - Tag overlay indexer
2. `tfp_client/lib/metadata/bloom_filter.py` - Bloom filter compression
3. `tfp_broadcaster/src/tag_broadcast/broadcaster.py` - Weekly broadcast job
4. `tests/test_tag_index.py` - Unit tests

**Key Functions:**
```python
class TagOverlayIndex:
    def add_entry(self, domain: str, tags: List[str], content_hash: bytes, popularity: float)
    def build_merkle_dag(self, epoch: int, domain: str) -> dict
    def export_bloom_filter(self, dag: dict) -> bytes
    def query(self, bloom: bytes, tag: str) -> bool  # Local query
    
class TagBroadcaster:
    def broadcast_weekly_index(self, domain: str) -> bytes
    def schedule_next_broadcast(self, epoch: int)
```

**Estimated LOC**: ~400
**Priority**: HIGH (enables discoverability)
**Dependencies**: None (pure Python)

---

## 📋 Bridge 2: Self-Publish Ingestion Pipeline (User Publishing)

### Problem
Current blueprint assumes tower-down broadcast only. No user→network ingestion path.

### Solution
Device → RaptorQ shard → NDN Announce → Mesh Cache → Gateway Schedule flow.

### Architecture

```
Publish Flow:
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│ User Device │───▶│ Local Mesh   │───▶│ Gateway     │───▶│ Broadcast    │
│             │    │ Nodes        │    │ Aggregator  │    │ Scheduler    │
└─────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
     │                    │                    │                    │
     │ 1. Hash content    │                    │                    │
     │ 2. RaptorQ encode  │                    │                    │
     │ 3. NDN Announce    │                    │                    │
     │───────────────────▶│                    │                    │
     │                    │ 4. Cache shards    │                    │
     │                    │ 5. Demand signal   │                    │
     │                    │───────────────────▶│                    │
     │                    │                    │ 6. Bid for slot    │
     │                    │                    │ 7. Schedule        │
     │                    │                    │───────────────────▶│
```

**Naming Convention:**
- `/tfp/publish/{device_id}/{content_hash}/announce` - Device announcement
- `/tfp/mesh/aggregate/{region}` - Mesh aggregation point
- `/tfp/gateway/bid/{content_hash}` - Gateway bid channel
- `/tfp/schedule/{epoch}/{slot}` - Broadcast schedule

### Implementation Plan

**Files to Create:**
1. `tfp_client/lib/publish/ingestion.py` - Device-side publishing
2. `tfp_client/lib/publish/mesh_aggregator.py` - Mesh node aggregation
3. `tfp_broadcaster/src/gateway/scheduler.py` - Gateway scheduling + bidding
4. `tfp_common/schemas/publish_schemas.py` - Publish message schemas
5. `tests/test_publish_pipeline.py` - Integration tests

**Key Functions:**
```python
class PublishIngestion:
    def announce_content(self, content: bytes, metadata: dict) -> str  # Returns hash
    def encode_and_announce(self, content: bytes) -> List[bytes]  # RaptorQ + NDN
    def wait_for_mesh_cache_confirmation(self, hash: str, timeout: int) -> bool

class MeshAggregator:
    def listen_for_announcements(self, region: str)
    def aggregate_demand_signals(self) -> dict  # {hash: demand_score}
    def forward_to_gateway(self, aggregated: dict)

class GatewayScheduler:
    def receive_aggregated_demand(self, demand: dict)
    def calculate_bid(self, content_hash: str, demand: float) -> int  # Credit bid
    def schedule_broadcast_slot(self, hash: str, bid: int, epoch: int)
```

**Estimated LOC**: ~600
**Priority**: HIGH (enables user publishing)
**Dependencies**: RaptorQ (already implemented), NDN (already implemented)

---

## 📋 Bridge 3: Popularity → Persistence Economic Loop (Self-Archiving)

### Problem
NDN caches popular content naturally, but lacks explicit economic incentive for long-term archival. Pure compute credits don't reward storage.

### Solution
Demand-Weighted Caching Credits (DWCC): Hybrid model with 50% compute + 50% archival pinning.

### Architecture

```
DWCC Formula:
credits_earned = base_rate × (requests × storage_duration × semantic_value) × decay_factor

Where:
- base_rate: 0.1 credits per request-hour
- requests: number of Interest packets for this hash
- storage_duration: hours pinned
- semantic_value: multiplier from LDM mapper (core=1.5x, enhanced=1.0x)
- decay_factor: 0.9^epochs_without_request (penalizes unused content)

Credit Types:
1. Compute Credits (PoSI): Earned by executing tasks
2. Pinning Credits (DWCC): Earned by storing high-demand content

Hybrid Wallet:
wallet = {
    "compute_balance": 100,  # 50% of total value
    "pinning_balance": 100,  # 50% of total value
    "pinned_content": [
        {"hash": "abc...", "since": epoch, "requests": 47, "credits_earned": 23.5}
    ]
}
```

### Implementation Plan

**Files to Create:**
1. `tfp_client/lib/credit/dwcc_calculator.py` - DWCC formula engine
2. `tfp_client/lib/credit/hybrid_wallet.py` - Dual-balance wallet
3. `tfp_client/lib/storage/pinning_manager.py` - Content pinning + decay
4. `tests/test_dwcc_economy.py` - Economic model tests

**Key Functions:**
```python
class DWCCCalculator:
    def calculate_pinning_credits(self, requests: int, duration_hours: float, 
                                   semantic_value: float, epochs_idle: int) -> float
    def apply_decay(self, credits: float, epochs_idle: int) -> float

class HybridWallet:
    def __init__(self, compute_ledger: CreditLedger, pinning_ledger: CreditLedger)
    def mint_compute(self, credits: int, proof_hash: bytes) -> Receipt
    def mint_pinning(self, content_hash: str, requests: int, duration: float) -> Receipt
    def spend(self, credits: int, receipt: Receipt)  # From either balance
    def get_total_value(self) -> float  # compute + pinning

class PinningManager:
    def pin_content(self, content_hash: str, semantic_value: float)
    def track_request(self, content_hash: str)  # Increment request counter
    def apply_epoch_decay(self)  # Decay all pinned content
    def evict_low_demand(self, threshold: float)  # Free space
```

**Integration Points:**
- Extend `CreditLedger` with pinning-specific methods
- Wire into `TFPClient.request_content()` to track requests
- Wire into broadcaster's LDM mapper for semantic_value
- Add periodic decay job (hourly epoch)

**Estimated LOC**: ~500
**Priority**: MEDIUM (enhances sustainability, not blocking)
**Dependencies**: CreditLedger (already implemented), LDM mapper (already implemented)

---

## 🗓️ Implementation Timeline

### Sprint 1: Tag-Overlay Index (Days 1-3)
- [ ] Day 1: Bloom filter implementation + tests
- [ ] Day 2: Tag index Merkle DAG builder + tests
- [ ] Day 3: Weekly broadcast scheduler + integration tests

### Sprint 2: Self-Publish Pipeline (Days 4-7)
- [ ] Day 4: Device-side ingestion (announce + encode)
- [ ] Day 5: Mesh aggregator listener
- [ ] Day 6: Gateway scheduler + bidding logic
- [ ] Day 7: End-to-end publish flow tests

### Sprint 3: DWCC Economy (Days 8-10)
- [ ] Day 8: DWCC calculator + unit tests
- [ ] Day 9: Hybrid wallet + pinning manager
- [ ] Day 10: Integration with existing credit system + full test suite

### Sprint 4: Hardening + Documentation (Days 11-14)
- [ ] Day 11: Attack scenario updates (test new vectors)
- [ ] Day 12: Performance optimization (Bloom filter size, cache eviction)
- [ ] Day 13: Documentation updates (README, architecture diagrams)
- [ ] Day 14: Release candidate testing, bug fixes

---

## 🧪 Test Strategy

### New Test Files
1. `tests/test_tag_index.py` (20 tests)
   - Bloom filter false positive rate
   - Merkle DAG integrity
   - Query performance

2. `tests/test_publish_pipeline.py` (25 tests)
   - Device announcement flow
   - Mesh aggregation correctness
   - Gateway bidding logic
   - End-to-end publish → broadcast

3. `tests/test_dwcc_economy.py` (20 tests)
   - DWCC formula accuracy
   - Decay function behavior
   - Hybrid wallet balance tracking
   - Pinning reward distribution

### Updated Existing Tests
- `tests/test_credit_ledger.py`: Add pinning receipt tests
- `tests/test_simulation_scenarios.py`: Add 2 new scenarios:
  - Tag discovery under censorship
  - Self-publish flood attack mitigation

### Attack Scenarios to Add
1. **Tag Poisoning**: Adversary broadcasts fake tag entries
   - Mitigation: Merkle proof verification, reputation scoring
   
2. **Publish Flood**: Sybil devices spam mesh with low-value content
   - Mitigation: PUF identity check on announcements, demand threshold

3. **Pinning Gaming**: Node pins random content to earn credits
   - Mitigation: Request verification, semantic value validation

---

## 📊 Success Metrics

### Functional Requirements
- ✅ Tag-based discovery works (query returns correct hashes)
- ✅ User can publish from device → broadcast in <5 minutes
- ✅ High-demand content earns 2-3x more credits than low-demand
- ✅ Unused pinned content decays by 50% after 7 days

### Performance Requirements
- Bloom filter: <1% false positive rate at 10K entries
- Mesh aggregation latency: <2 seconds for 100 announcements
- Gateway scheduling: <100ms bid calculation
- DWCC calculation: <1ms per content hash

### Security Requirements
- All new modules pass symbolic preprocessor validation
- PUF identity required for publishing (blocks Sybil)
- Merkle proofs verifiable by any node
- No single point of failure in publish pipeline

---

## 🔧 Technical Decisions

### Bloom Filter Parameters
- Size: 10,000 bits (1.25 KB)
- Hash functions: 7 (optimal for 10K entries)
- False positive rate: ~0.7% at capacity
- Serialization: Compact bit array + salt

### Merkle DAG Structure
- Binary tree over sorted entries
- Root hash broadcast weekly
- Proofs: log₂(N) hashes for verification
- Epoch: ISO week number (e.g., 202501)

### DWCC Tuning Parameters
```python
BASE_RATE = 0.1  # credits per request-hour
SEMANTIC_MULTIPLIERS = {"core_plp": 1.5, "enhanced_plp": 1.0}
DECAY_FACTOR = 0.9  # per epoch (1 hour)
HALF_LIFE_EPOCHS = 7  # ~7 hours to 50% value
MIN_REQUESTS_FOR_PINNING = 3  # Prevent gaming
```

### Gateway Bidding Algorithm
```python
def calculate_bid(demand_score: float, content_size: int, 
                  current_load: float) -> int:
    base_bid = demand_score * 100  # Scale to credits
    size_penalty = content_size / 1_000_000  # 1 credit per MB
    load_multiplier = 1.0 / (1.0 + current_load)  # Reduce when busy
    return int(base_bid * size_penalty * load_multiplier)
```

---

## 📚 Documentation Deliverables

1. **Updated README.md**
   - New architecture diagram with 3 bridges
   - Quickstart for publishing content
   - Tag discovery examples

2. **Architecture Doc** (`docs/v2.4-architecture.md`)
   - Detailed flow diagrams
   - Module interaction specs
   - Performance benchmarks

3. **API Reference** (docstrings + Sphinx)
   - All new public classes/functions
   - Usage examples
   - Migration guide from v2.3

4. **Threat Model Update** (`docs/v2.4-threat-model.md`)
   - New attack vectors
   - Mitigation strategies
   - Residual risks

---

## 🎯 Final Verification Checklist

Before v2.4 release:
- [ ] 100+ tests passing (original 100 + 65 new)
- [ ] All 3 attack scenarios PASS thresholds
- [ ] Code coverage ≥95% for new modules
- [ ] Performance benchmarks meet targets
- [ ] Documentation complete
- [ ] Backward compatible with v2.3 clients
- [ ] Demo: Publish → Discover → Download end-to-end

---

*Total Estimated Effort: 1,500 LOC, 14 days, 3 sprints*
*Risk Level: LOW (builds on stable v2.3 foundation)*
*Impact: HIGH (achieves full vision of uncensorable digital commons)*
