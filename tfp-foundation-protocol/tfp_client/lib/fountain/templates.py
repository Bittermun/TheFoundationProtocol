# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Content-Defined Chunking (CDC) Template Builder

Defines optimized chunking profiles for Audio, Video, and Webpages,
generating standard TFP assembler Recipes using rolling Gear-hashes.
"""

import hashlib
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple
from tfp_client.lib.fountain.cdc import ContentDefinedChunker
from tfp_client.lib.reconstruction.template_assembler import Recipe


@dataclass
class CDCProfile:
    """Configuration profile for content-defined chunk sizes."""
    min_size: int
    max_size: int
    target_size: int


# Industry-optimized CDC size parameters
AUDIO_PROFILE = CDCProfile(min_size=8192, max_size=65536, target_size=32768)     # Small window for silent/repeating gaps
VIDEO_PROFILE = CDCProfile(min_size=131072, max_size=1048576, target_size=524288) # Large window for frame keyblocks
WEBPAGE_PROFILE = CDCProfile(min_size=2048, max_size=16384, target_size=8192)     # Ultra-fine window for text/HTML revisions


class CDCTemplateBuilder:
    """
    Builds optimized recipes for Audio, Video, and Webpages by applying
    specialized Content-Defined Chunking profiles.
    """

    def __init__(self, profile_type: str = "audio"):
        self.profile_type = profile_type.lower()
        if self.profile_type == "audio":
            self.profile = AUDIO_PROFILE
        elif self.profile_type == "video":
            self.profile = VIDEO_PROFILE
        elif self.profile_type == "webpage":
            self.profile = WEBPAGE_PROFILE
        else:
            # Fallback default
            self.profile = AUDIO_PROFILE

        self.chunker = ContentDefinedChunker(
            min_size=self.profile.min_size,
            max_size=self.profile.max_size,
            target_size=self.profile.target_size
        )

    def generate_recipe(
        self,
        data: bytes,
        template_id: str,
        ai_adapter: str = "general",
        title: str = "Untitled Content"
    ) -> Tuple[Recipe, List[Dict[str, Any]]]:
        """
        Partition the binary data using the selected CDC profile, generate TFP chunks,
        and construct the final assembly Recipe.

        Returns:
            Tuple of:
              - Recipe: Standard TFP template assembler recipe
              - List[Dict]: List of generated chunk objects containing:
                "chunk_id", "data", "size", "hash"
        """
        # Partiton data using Gear rolling hash
        raw_chunks = self.chunker.chunk_data(data)
        
        chunk_ids = []
        chunks_metadata = []
        
        for item in raw_chunks:
            chunk_hash = item["hash"]
            # Construct standard chunk ID matching the schema format
            chunk_id = f"chunk-{self.profile_type}-{chunk_hash[:16]}"
            
            chunk_ids.append(chunk_id)
            chunks_metadata.append({
                "chunk_id": chunk_id,
                "data": item["data"],
                "size": item["size"],
                "hash": chunk_hash
            })

        final_content_hash = hashlib.sha3_256(data).hexdigest()
        
        recipe = Recipe(
            content_hash=final_content_hash,
            template_id=template_id,
            chunk_ids=chunk_ids,
            ai_adapter=ai_adapter,
            metadata={
                "title": title,
                "profile": self.profile_type,
                "min_chunk_bytes": self.profile.min_size,
                "max_chunk_bytes": self.profile.max_size,
                "target_chunk_bytes": self.profile.target_size,
                "total_chunks": len(chunk_ids),
                "total_bytes": len(data)
            }
        )

        return recipe, chunks_metadata
