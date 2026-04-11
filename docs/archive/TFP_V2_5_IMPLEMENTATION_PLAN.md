# TFP v2.5: Hierarchical Lexicon Tree + Chunking System Implementation Plan

## Executive Summary

This document outlines the complete implementation strategy for **Bridge 3 (Popularity→Persistence)** plus the critical **Hierarchical Lexicon Tree (HLT)** and **Chunking/Template** systems that transform TFP from a broadcast layer into a true semantic-synchronized, bandwidth-efficient global information commons.

---

## 🎯 The Four Pillars Complete Vision

| Pillar | Status | Purpose |
|--------|--------|---------|
| ✅ **Tag-Overlay Index** | Complete (v2.4) | Tag-based discovery without central indexers |
| ✅ **Self-Publish Pipeline** | Complete (v2.4) | Device→Mesh→Gateway ingestion |
| ⏳ **Popularity→Persistence Loop** | In Progress | Demand-weighted archival credits with decay |
| ⏳ **HLT + Chunking** | **NEW** | Semantic synchronization + bandwidth optimization |

---

## 🧠 Understanding HLT vs Chunking (Critical Distinction)

### They Are Siblings, Not Rivals

| Aspect | **Chunking/Templates** | **Hierarchical Lexicon Tree (HLT)** |
|--------|----------------------|-------------------------------------|
| **What it synchronizes** | Content pieces (textures, layouts, audio patterns, code blocks) | AI model weights (the "brain" that generates/assembles) |
| **Problem solved** | Bandwidth waste + generation compute | Semantic drift + version incompatibility |
| **When used** | During reconstruction (filling in the recipe) | During updates (keeping devices speaking the same language) |
| **Analogy** | LEGO bricks + instruction manual | Dictionary + grammar textbook |

### How They Work Together (The Full Flow)

```
1. Broadcaster creates recipe:
   [template: news_layout_v4, chunks: [sky_42, face_19, text_delta], ai_adapter: medical_v2.1]

2. Device checks HLT:
   "Do I have medical_v2.1? Yes." → AI brain is synchronized ✓

3. Device checks chunk cache:
   "Have sky_42? Yes. Have face_19? No."

4. Device requests only face_19 via NDN + RaptorQ

5. AI assembles:
   Places cached chunks → generates missing piece → applies template rules

6. Result:
   99% less data transmitted, 80% less compute used, zero semantic drift
```

---

## 📋 Implementation Modules

### Module 1: Chunk Registry & Index (`tfp-common/assets/chunk_index/`)

**Files to Create:**
- `tfp_common/assets/chunk_index/__init__.py`
- `tfp_common/assets/chunk_index/registry.py` - Maps chunk_id → content_hash → category
- `tfp_common/assets/chunk_index/categories.py` - Predefined categories (texture, layout, audio, code, etc.)

**Key Features:**
- SHA3-256 chunk hashing
- Category-based organization
- Version tracking for chunks
- Merkle root export for verification

**Estimated LOC:** ~200

---

### Module 2: Chunk Cache Manager (`tfp-client/lib/cache/chunk_store.py`)

**Files to Create:**
- `tfp_client/lib/cache/__init__.py` (update)
- `tfp_client/lib/cache/chunk_store.py` - LRU eviction + Credit reward for pinning rare chunks

**Key Features:**
- LRU eviction policy
- Rare-chunk pinning rewards (credits ∝ 1/frequency)
- Integration with credit ledger
- Bloom filter for fast existence checks

**Estimated LOC:** ~250

---

### Module 3: Template Assembler (`tfp-client/lib/reconstruction/template_assembler.py`)

**Files to Create:**
- `tfp_client/lib/reconstruction/__init__.py`
- `tfp_client/lib/reconstruction/template_assembler.py` - Recipe → HLT sync check → fetch missing chunks → AI fill-in → final asset
- `tfp_client/lib/reconstruction/templates.py` - Template definitions and validation

**Key Features:**
- Template schema validation
- HLT version checking before assembly
- Missing chunk detection and fetching
- Minimal AI generation (only for missing pieces)
- Assembly audit trail

**Estimated LOC:** ~350

---

### Module 4: Hierarchical Lexicon Tree Core (`tfp-client/lib/lexicon/hlt.py`)

**Files to Create:**
- `tfp_client/lib/lexicon/hlt.py` - Full HLT implementation with versioning, delta sync, precision anchors
- `tfp_client/lib/lexicon/delta_sync.py` - Adapter delta computation and application
- `tfp_client/lib/lexicon/precision_anchor.py` - Precision anchors for semantic stability

**Key Features:**
- Tree structure: Root → Domain → Subdomain → Adapter → Version
- Delta computation between versions
- Precision anchors (immutable semantic reference points)
- Tag-indexed discovery for lexicons
- Rollback on hash mismatch (atomic updates)

**Estimated LOC:** ~400

---

### Module 5: DWCC Calculator (`tfp-client/lib/credit/dwcc_calculator.py`)

**Files to Create:**
- `tfp_client/lib/credit/dwcc_calculator.py` - Demand-Weighted Caching Credits formula engine

**Formula:**
```
credits = base_rate × (requests × storage_duration × semantic_value × rarity_multiplier)

where:
- base_rate = network-configured base credit rate
- requests = number of unique requests for this hash
- storage_duration = hours pinned
- semantic_value = tag-based importance score (configurable per domain)
- rarity_multiplier = 1 / (global_copy_count + 0.001)
```

**Estimated LOC:** ~150

---

### Module 6: Hybrid Wallet (`tfp-client/lib/credit/hybrid_wallet.py`)

**Files to Create:**
- `tfp_client/lib/credit/hybrid_wallet.py` - Dual-balance wallet (compute + pinning)

**Key Features:**
- Two balances: `compute_credits` and `pinning_credits`
- 50/50 split rule (configurable)
- Decay function for unused pinning credits
- Conversion rules (pinning → compute allowed, reverse restricted)

**Estimated LOC:** ~200

---

### Module 7: Pinning Manager (`tfp-client/lib/storage/pinning_manager.py`)

**Files to Create:**
- `tfp_client/lib/storage/__init__.py` (update)
- `tfp_client/lib/storage/pinning_manager.py` - Content pinning with decay, demand tracking

**Key Features:**
- Pin/unpin content by hash
- Demand tracking (request counter per hash)
- Automatic decay calculation
- Eviction policy based on credit optimization
- Integration with chunk store for chunk-level pinning

**Estimated LOC:** ~300

---

## 🧪 Test Strategy (TDD - Test First)

### Test Files to Create

1. **`tests/test_chunk_registry.py`** (~25 tests)
   - Chunk ID generation and validation
   - Hash computation and verification
   - Category assignment and filtering
   - Merkle root export
   - Serialization/deserialization

2. **`tests/test_chunk_store.py`** (~30 tests)
   - LRU eviction behavior
   - Rare-chunk credit rewards
   - Bloom filter existence checks
   - Concurrent access safety
   - Storage limits enforcement

3. **`tests/test_template_assembler.py`** (~35 tests)
   - Template validation
   - HLT sync checking
   - Missing chunk detection
   - Assembly with partial cache hits
   - Audit trail generation
   - Error handling and rollback

4. **`tests/test_hlt.py`** (~40 tests)
   - Tree construction and traversal
   - Delta computation
   - Delta application with rollback
   - Precision anchor stability
   - Tag-indexed discovery
   - Version compatibility checking

5. **`tests/test_dwcc_calculator.py`** (~20 tests)
   - Formula correctness
   - Edge cases (zero requests, infinite duration)
   - Rarity multiplier behavior
   - Semantic value weighting

6. **`tests/test_hybrid_wallet.py`** (~20 tests)
   - Dual balance management
   - Decay calculations
   - Conversion rules
   - Insufficient balance errors

7. **`tests/test_pinning_manager.py`** (~25 tests)
   - Pin/unpin operations
   - Demand tracking accuracy
   - Decay over time
   - Eviction optimization
   - Integration with chunk store

8. **`tests/test_integration_chunking.py`** (~20 tests)
   - End-to-end chunking workflow
   - HLT + Chunking integration
   - Bandwidth savings measurement
   - Compute reduction measurement

**Total New Tests:** ~215

---

## 📊 Implementation Phases

### Phase 1: Foundation (Chunks + HLT Core)
**Modules:** 1, 2, 4
**Tests:** test_chunk_registry.py, test_chunk_store.py, test_hlt.py
**LOC:** ~850
**Duration Estimate:** 2-3 hours

### Phase 2: Assembly + Templates
**Modules:** 3
**Tests:** test_template_assembler.py
**LOC:** ~350
**Duration Estimate:** 1-2 hours

### Phase 3: Economic Layer (DWCC + Hybrid Wallet + Pinning)
**Modules:** 5, 6, 7
**Tests:** test_dwcc_calculator.py, test_hybrid_wallet.py, test_pinning_manager.py
**LOC:** ~650
**Duration Estimate:** 2 hours

### Phase 4: Integration Testing
**Modules:** All integration tests
**Tests:** test_integration_chunking.py
**LOC:** ~200 (test code)
**Duration Estimate:** 1 hour

---

## 🎯 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Test Coverage** | 100% of new modules | pytest --cov |
| **Bandwidth Savings** | >90% for cached chunks | Compare raw vs chunked transfer size |
| **Compute Reduction** | >75% for templated content | Measure AI inference calls |
| **Semantic Drift** | 0% (all HLT-synced reconstructions match) | Hash comparison across devices |
| **Total Tests** | 132 → 347+ | pytest collection count |

---

## 🔧 Integration Points

### Existing Modules (No Changes Required)
- ✅ `tfp_client/lib/fountain/` - RaptorQ encoding/decoding
- ✅ `tfp_client/lib/ndn/` - Content retrieval by hash
- ✅ `tfp_client/lib/credit/ledger.py` - Base credit operations
- ✅ `tfp_client/lib/security/symbolic_preprocessor/` - Recipe validation

### Updated Adapters
- `tfp_client/lib/lexicon/adapter.py` - Add HLT-aware reconstruct()
- `tfp_client/lib/core/tfp_engine.py` - Add chunk-aware request flow

---

## 🚀 Post-Implementation Roadmap

### v2.5 (This Release)
- [x] Chunk Registry + Cache
- [x] Template Assembler
- [x] Hierarchical Lexicon Tree
- [x] DWCC Calculator
- [x] Hybrid Wallet
- [x] Pinning Manager
- [ ] Full integration tests

### v2.6 (Next)
- Multi-waveform fallback support
- Crypto agility registry
- Real ONNX/TFLite bindings for lexicon adapters

### v3.0 (Future)
- Mesh-native governance layer
- Cross-network bridge protocols
- Quantum-resistant signature upgrade path

---

## 📝 Notes

1. **TDD Strict adherence**: Every module must have tests written FIRST, then implementation to pass tests.
2. **No breaking changes**: All existing 132 tests must continue to pass.
3. **Documentation**: Each module gets docstrings + type hints.
4. **Performance**: Profile chunk lookup latency; target <1ms for cache hits.

---

**Ready to begin implementation. Starting with Phase 1: Foundation.**
