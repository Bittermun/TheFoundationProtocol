# TFP Template System Architecture

This document provides a technical deep-dive into TFP's template assembly framework for developers interested in extending or building on top of this system.

## Overview

TFP includes a template assembly framework designed to enable efficient content building from reusable chunks. The framework provides the architectural foundation for template-based content creation, though it is currently an internal component requiring manual configuration.

## Components

### 1. ChunkStore (`tfp_client/lib/cache/chunk_store.py`)

Stores reusable content pieces with metadata:

```python
from tfp_client.lib.cache.chunk_store import ChunkStore

chunk_store = ChunkStore(max_chunks=10_000, max_bytes=256 * 1024 * 1024)
chunk_store.put_chunk(chunk_id="texture-001", data=b"...texture bytes...")
entry = chunk_store.get_chunk(chunk_id)
```

**Purpose**: Cache reusable content pieces (textures, layouts, audio patterns, code blocks) to avoid re-uploading identical data.

### 2. TemplateAssembler (`tfp_client/lib/reconstruction/template_assembler.py`)

Assembles content from recipes using cached chunks:

```python
from tfp_client.lib.reconstruction.template_assembler import TemplateAssembler, Recipe

recipe = Recipe(
    content_hash="abc123...",
    template_id="audio-book-template",
    chunk_ids=["chunk-001", "chunk-002", "chunk-003"],
    ai_adapter="text",
    metadata={"title": "Educational Audio"}
)

assembler = TemplateAssembler(chunk_store=chunk_store, hlt=hlt_tree)
result = assembler.assemble(recipe)
```

**Purpose**: Combine cached chunks with AI fill-in for missing pieces, enabling efficient content assembly.

### 3. HierarchicalLexiconTree (HLT)

Provides semantic validation before assembly:

```python
from tfp_client.lib.lexicon.hlt.tree import HierarchicalLexiconTree

hlt = HierarchicalLexiconTree()
hlt.sync_domain("text", adapter=text_adapter)
```

**Purpose**: Ensure semantic synchronization between content creator and assembler to prevent drift.

### 4. Chunk Categories (`tfp_common/assets/chunk_index/categories.py`)

Predefined categories for chunk classification:

- `texture`: Visual texture elements
- `layout`: Structural layout templates
- `audio_pattern`: Audio segments and patterns
- `code_block`: Executable code snippets
- `text_delta`: Text content differences
- `video_segment`: Video clips
- `metadata`: Metadata chunks
- `font_glyph`: Font typography elements
- `icon`: Icon graphics
- `3d_model`: 3D model components

**Purpose**: Organize chunks by type for efficient lookup and reuse.

## Workflow

```
Recipe → HLT Sync Check → Chunk Cache Lookup → AI Fill-in → Final Content
```

1. **HLT Sync Check**: Verify HLT has required AI adapter and version
2. **Chunk Cache Lookup**: Check which chunks are cached vs missing
3. **AI Fill-in**: Generate missing pieces using AI adapter
4. **Assembly**: Combine cached chunks with generated pieces

## Recipe Format

```python
@dataclass
class Recipe:
    content_hash: str        # SHA3-256 of final content
    template_id: str         # Template identifier
    chunk_ids: List[str]     # Required chunk IDs
    ai_adapter: str          # AI adapter domain for fill-in
    metadata: Dict[str, Any] # Additional metadata
```

## Assembly Result

```python
@dataclass
class AssemblyResult:
    status: AssemblyStatus
    content_hash: str
    assembled_data: Optional[bytes]
    cached_chunks: List[str]
    missing_chunks: List[str]
    ai_generation_needed: bool
    hlt_synced: bool
    bandwidth_saved_bytes: int
    compute_saved_percent: float
```

## Current Limitations

- **Manual Configuration**: Requires manual recipe creation, chunk store setup, HLT configuration
- **No Template Marketplace**: No centralized template repository
- **No UX Layer**: No user-facing interface for template creation or assembly
- **Framework State**: This is an architectural foundation, not a turnkey solution

## Future Development

Potential enhancements to make this a user-facing feature:

1. **Template Marketplace**: Centralized repository for sharing templates
2. **UX Layer**: Web interface for template creation and assembly
3. **Perceptual Hash Integration**: Use PDQ/wavelet hashes for template matching
4. ~~**Content-Defined Chunking**: Use fastchunking's CDC for automatic chunk boundary detection~~ ✅ **COMPLETED**: FastCDC implemented in `tfp_transport/cdc.py`
5. **Auto-Recipe Generation**: AI-powered recipe creation from content analysis
6. **TemplateDescriptor Integration**: Use `tfp_transport/template_descriptor.py` for publish-time metadata

## Extension Points

Developers can extend the template system by:

1. **Custom Chunk Categories**: Register new categories via `register_custom_category()`
2. **Custom AI Adapters**: Implement new adapters for HLT domains
3. **Custom Assembly Logic**: Extend `TemplateAssembler` for specialized use cases
4. **Recipe Serialization**: Add custom metadata to recipes for domain-specific needs

## Integration with Existing Systems

The template system integrates with:

- **ContentCache**: LRU cache for hot content (complements chunk cache)
- **HLT Gossip**: Nostr-based HLT synchronization across nodes
- **NDN Routing**: Hash-based content naming for template distribution
- **IPFS**: Persistent pinning of template chunks

## Testing

See `tests/test_template_assembler.py` for template system tests including:
- Recipe serialization/deserialization
- Assembly plan generation
- HLT sync validation
- Chunk cache integration
