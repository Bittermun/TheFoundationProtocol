# [v3.2.0] Large File & Media Archive Support

## Goal
Enable distribution of large files (100MB - 10GB): movies, music albums, software archives, scientific datasets. Optimize RaptorQ and chunking for this scale.

## Background
Current system optimized for small content (< 10MB). Large files hit limits:
- Memory: Loading 1GB video into RAM crashes low-end devices
- Bandwidth: Single failed byte requires full re-download
- Storage: SQLite BLOBs inefficient for multi-GB files

## Technical Scope

### Phase 1: Streaming Chunk Store (Complexity: High)
**File:** `tfp_client/lib/cache/streaming_chunk_store.py` (new)

Replace in-memory blob handling with disk-backed streaming:

```python
class StreamingChunkStore:
    """Stores large files as 64KB chunks on disk, not in memory or SQLite."""
    
    def __init__(self, base_path: Path):
        self.base = base_path / "chunks"
        
    def write_chunk(self, content_hash: str, chunk_idx: int, data: bytes):
        """Write single chunk to disk."""
        path = self.base / content_hash[:2] / content_hash / f"{chunk_idx:08d}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        
    def read_stream(self, content_hash: str, start_chunk: int = 0) -> Iterator[bytes]:
        """Yield chunks for streaming without loading full file."""
        chunk_idx = start_chunk
        while True:
            path = self.base / content_hash[:2] / content_hash / f"{chunk_idx:08d}"
            if not path.exists():
                break
            yield path.read_bytes()
            chunk_idx += 1
            
    def verify_chunk(self, content_hash: str, chunk_idx: int, expected_hash: str) -> bool:
        """Verify single chunk integrity without loading whole file."""
```

### Phase 2: RaptorQ Tuning for Large Files (Complexity: Medium)
**File:** `tfp_client/lib/fountain/fountain_real.py`

Current settings (optimized for small content):
- Symbol size: 1KB
- Symbols per block: 64

New settings for large files:
- Symbol size: 64KB (matching HTTP chunk size)
- Symbols per block: 1024 (64MB blocks)
- Parallel encoding: Use thread pool for multi-core speedup

```python
@dataclass
class RaptorQProfile:
    """Tuned parameters for different content sizes."""
    symbol_size: int          # 1024 for small, 65536 for large
    symbols_per_block: int    # 64 for small, 1024 for large
    max_parallel: int         # 1 for small, 8 for large
    
    @classmethod
    def for_size(cls, bytes: int) -> "RaptorQProfile":
        if bytes < 10_000_000:      # < 10MB
            return cls(1024, 64, 1)
        elif bytes < 1_000_000_000: # < 1GB
            return cls(65536, 1024, 4)
        else:                        # > 1GB
            return cls(65536, 2048, 8)
```

### Phase 3: Resume & Partial Downloads (Complexity: High)
**Files:**
- `tfp_demo/server.py` — extend `/api/get/{hash}` with range requests
- `tfp_client/lib/core/tfp_engine.py` — resume support

Implement HTTP Range requests properly:
```
GET /api/get/{hash}?stream=true&start_chunk=1024
Range: bytes=67108864-134217727  # 64MB-128MB
```

Client resume flow:
1. Check local chunk store — what chunks already downloaded?
2. Request only missing chunks from peers
3. Verify each chunk via Merkle proof
4. Assemble on disk, not in memory

### Phase 4: Memory-Efficient Upload (Complexity: Medium)
**File:** `tfp_demo/server.py` — modify `/api/publish`

Current: Loads full multipart body into RAM
New: Streaming parser that yields chunks:

```python
async def publish_large_content(request: Request):
    """Handle multi-GB uploads without OOM."""
    content_hash = None
    chunk_store = StreamingChunkStore()
    
    async for chunk in request.stream():
        # Parse multipart boundaries
        if is_file_chunk(chunk):
            chunk_idx = calculate_chunk_index(chunk.offset)
            chunk_store.write_chunk(content_hash, chunk_idx, chunk.data)
            
        # Update progress for UI
        if chunk_idx % 100 == 0:
            broadcast_progress(content_hash, chunk_idx, total_chunks)
```

## Acceptance Criteria
- [ ] Can upload 500MB video without server OOM
- [ ] Can download 1GB file on device with 2GB RAM
- [ ] Resume interrupted download from middle (kill connection at 50%, resume)
- [ ] RaptorQ reconstruction works with 10% packet loss on 100MB file
- [ ] 10-node testbed distributes 1GB file in < 30 minutes
- [ ] Merkle tree verification for any chunk without full file

## Performance Targets

| Metric | Small (< 10MB) | Large (100MB - 1GB) | Huge (> 1GB) |
|--------|---------------|---------------------|--------------|
| Upload memory | < 50MB | < 100MB | < 200MB |
| Download memory | < 50MB | < 100MB | < 200MB |
| Chunk size | 64KB | 64KB | 64KB |
| Parallel connections | 1 | 4 | 8 |
| Resume granularity | N/A | 64KB | 64KB |

## API Changes

Extended query parameters:
```
GET /api/get/{hash}?stream=true&start_chunk=N&end_chunk=M
Range: bytes=START-END  # Standard HTTP Range header

Response:
206 Partial Content
Content-Range: bytes START-END/TOTAL
X-Chunk-Index: N
```

## Database Changes

```sql
-- Track download progress per device
CREATE TABLE download_progress (
    device_id TEXT,
    content_hash TEXT,
    chunks_received INTEGER,  -- Bitmap or count
    last_updated REAL,
    PRIMARY KEY (device_id, content_hash)
);

-- Large content metadata
ALTER TABLE content ADD COLUMN size_bytes INTEGER;
ALTER TABLE content ADD COLUMN chunk_count INTEGER;
ALTER TABLE content ADD COLUMN merkle_root TEXT;  -- For per-chunk verification
```

## Good First Sub-Issues
1. **Streaming file copy utility** — Generic `copy_stream(src, dst, chunk_size)`
2. **RaptorQ profile selector** — `select_profile(file_size)` function with tests
3. **Chunk index calculator** — Given byte offset, which chunk?
4. **HTTP Range parser** — Parse `bytes=START-END`, return (start, end)

## Estimated Effort
- Storage specialist: 2-3 weeks
- Protocol engineer + P2P specialist: 3-4 weeks

## Priority
**P1** — Enables media archives, movies, music albums

## Security Considerations

**Resource exhaustion:** Large uploads can fill disk. Add limits:
```python
MAX_CONTENT_SIZE = 10 * 1024 * 1024 * 1024  # 10GB per file
MAX_STORAGE_PER_DEVICE = 100 * 1024 * 1024 * 1024  # 100GB per node
```

**Verify-on-read:** Each chunk must be verified before use, not just at end.

---

## Open Questions

**Q: Should we support torrent-style swarming?**
A: Not in v3.2. Keep simpler: request from N closest nodes (by latency). Swarming in v3.3 if needed.

**Q: How to garbage collect partial downloads?**
A: `download_progress` table with `last_updated`. Reap entries > 7 days old.

**Q: Mobile battery impact?**
A: Add `low_power_mode` flag. Reduce parallel connections, batch disk writes.

**Q: What about seeding (keeping files available)?**
A: Incentivize via credits — nodes earn for serving chunks, not just storing. See economics in issue #31.
