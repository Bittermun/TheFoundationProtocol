# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
TFP Transport Layer

Provides content-defined chunking, erasure coding, and transport protocols
for efficient data transfer and deduplication.
"""

from tfp_transport.cdc import CDCChunker, FastCDC, create_fastcdc_chunker
from tfp_transport.template_descriptor import TemplateDescriptor, create_cdc_template

__all__ = [
    "CDCChunker",
    "FastCDC",
    "create_fastcdc_chunker",
    "TemplateDescriptor",
    "create_cdc_template",
]
