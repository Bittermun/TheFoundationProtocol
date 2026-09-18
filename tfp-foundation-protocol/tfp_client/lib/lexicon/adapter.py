# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

from .adapter_real import Content, RealLexiconAdapter


class LexiconAdapter(RealLexiconAdapter):
    """Production Lexicon adapter backed by real Zstandard dictionary compression."""
    pass
