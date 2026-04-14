# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

import dataclasses
import hashlib


@dataclasses.dataclass
class Content:
    root_hash: str
    data: bytes
    metadata: dict


class LexiconAdapter:
    """Mock Lexicon + on-device AI adapter — swap for ONNX/TFLite bindings."""

    def reconstruct(self, file_bytes: bytes, model=None) -> Content:
        return Content(
            root_hash=hashlib.sha3_256(file_bytes).hexdigest(),
            data=file_bytes,
            metadata={},
        )
