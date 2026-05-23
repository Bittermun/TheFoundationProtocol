# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Tests for TFP CDCTemplateBuilder - Audio, Video, and Webpage Profiles
"""

import hashlib
import pytest
from tfp_client.lib.fountain.templates import CDCTemplateBuilder
from tfp_client.lib.cache.chunk_store import ChunkStore
from tfp_client.lib.lexicon.hlt.tree import HierarchicalLexiconTree
from tfp_client.lib.reconstruction.template_assembler import TemplateAssembler, AssemblyStatus


def test_audio_template_chunking_and_reassembly():
    """Verify AUDIO profile chunking, recipe generation, and TemplateAssembler reassembly."""
    # Generate mock MP3-like repeating/silent pattern
    audio_data = b"MP3HEADER" + b"\x00" * 4000 + b"MUSICDATA" * 5000 + b"TAGS" * 100
    
    builder = CDCTemplateBuilder(profile_type="audio")
    recipe, chunks_meta = builder.generate_recipe(
        data=audio_data,
        template_id="audio_template_001",
        ai_adapter="general",
        title="Sample Community Podcast"
    )
    
    assert recipe.metadata["profile"] == "audio"
    assert recipe.metadata["total_bytes"] == len(audio_data)
    assert len(chunks_meta) > 0
    
    # Initialize Core storage and assembly components
    chunk_store = ChunkStore(max_bytes=10 * 1024 * 1024, max_chunks=1000)
    hlt = HierarchicalLexiconTree()
    hlt.add_domain("general", "v1.0.0", hashlib.sha3_256(b"general").hexdigest())
    
    # Store all chunks in the chunk store
    for ch in chunks_meta:
        chunk_store.put(
            ch["data"],
            category="audio",
            chunk_id_hint=ch["chunk_id"]
        )
        
    assembler = TemplateAssembler(chunk_store, hlt)
    result = assembler.assemble(recipe)
    
    assert result.status == AssemblyStatus.SUCCESS
    assert result.assembled_data == audio_data
    assert result.bandwidth_saved_bytes == len(audio_data)
    assert result.compute_saved_percent == 100.0


def test_video_template_chunking_and_reassembly():
    """Verify VIDEO profile chunking with large boundaries and TemplateAssembler reassembly."""
    # Generate mock MP4-like larger pattern
    video_data = b"MP4BOX" + b"KEYFRAME_DATA" * 80000 + b"TRANSITION" * 1000
    
    builder = CDCTemplateBuilder(profile_type="video")
    recipe, chunks_meta = builder.generate_recipe(
        data=video_data,
        template_id="video_template_001",
        ai_adapter="general",
        title="Sample Emergency Video"
    )
    
    assert recipe.metadata["profile"] == "video"
    assert len(chunks_meta) > 0
    
    # Large chunks should be generated
    for ch in chunks_meta:
        # Check that individual chunks conform to the video size bounds, except possibly the last one
        if ch != chunks_meta[-1]:
            assert ch["size"] >= 131072
            assert ch["size"] <= 1048576

    # Verify assembler reassembly
    chunk_store = ChunkStore(max_bytes=150 * 1024 * 1024, max_chunks=1000)
    hlt = HierarchicalLexiconTree()
    hlt.add_domain("general", "v1.0.0", hashlib.sha3_256(b"general").hexdigest())
    
    for ch in chunks_meta:
        chunk_store.put(
            ch["data"],
            category="video",
            chunk_id_hint=ch["chunk_id"]
        )
        
    assembler = TemplateAssembler(chunk_store, hlt)
    result = assembler.assemble(recipe)
    
    assert result.status == AssemblyStatus.SUCCESS
    assert result.assembled_data == video_data


def test_webpage_template_chunking_and_reassembly():
    """Verify WEBPAGE profile chunking with ultra-fine boundaries and TemplateAssembler reassembly."""
    # Generate mock HTML/JS text content
    web_data = b"<!DOCTYPE html><html><head><title>Test Page</title></head><body>" + b"<h1>Header</h1><p>Paragraph.</p>" * 200 + b"</body></html>"
    
    builder = CDCTemplateBuilder(profile_type="webpage")
    recipe, chunks_meta = builder.generate_recipe(
        data=web_data,
        template_id="webpage_template_001",
        ai_adapter="general",
        title="Emergency Info Portal"
    )
    
    assert recipe.metadata["profile"] == "webpage"
    assert len(chunks_meta) > 0
    
    # Check that individual chunks conform to the webpage size bounds, except possibly the last one
    for ch in chunks_meta:
        if ch != chunks_meta[-1]:
            assert ch["size"] >= 2048
            assert ch["size"] <= 16384

    # Verify assembler reassembly
    chunk_store = ChunkStore(max_bytes=10 * 1024 * 1024, max_chunks=1000)
    hlt = HierarchicalLexiconTree()
    hlt.add_domain("general", "v1.0.0", hashlib.sha3_256(b"general").hexdigest())
    
    for ch in chunks_meta:
        chunk_store.put(
            ch["data"],
            category="webpage",
            chunk_id_hint=ch["chunk_id"]
        )
        
    assembler = TemplateAssembler(chunk_store, hlt)
    result = assembler.assemble(recipe)
    
    assert result.status == AssemblyStatus.SUCCESS
    assert result.assembled_data == web_data
