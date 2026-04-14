# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Real NDN adapter backed by python-ndn (async).
Falls back to mock behaviour if NFD is unreachable.
Interface matches NDNAdapter exactly so DI is transparent.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Interest:
    name: str


@dataclasses.dataclass
class Data:
    name: str
    content: bytes


_TIMEOUT_MS = int(os.getenv("TFP_NDN_TIMEOUT_MS", "2000"))
_RETRIES = int(os.getenv("TFP_NDN_RETRIES", "2"))


class RealNDNAdapter:
    """
    Async NDN adapter — wraps python-ndn.
    Falls back to mock if NFD socket unavailable.
    """

    def __init__(self, fallback_content: Optional[bytes] = None):
        self._fallback_content = fallback_content

    def create_interest(self, root_hash: str) -> Interest:
        return Interest(name=f"/tfp/content/{root_hash}")

    def express_interest(self, interest: Interest) -> Data:
        """Sync wrapper — always runs in a dedicated event loop to avoid deprecation."""
        try:
            # Check if we're already inside a running event loop (e.g. async test)
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None

            if running_loop is not None:
                # Already inside async context — delegate to thread with its own loop
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self._sync_express, interest)
                    return future.result(
                        timeout=(_TIMEOUT_MS / 1000) * (_RETRIES + 1) + 1
                    )
            else:
                return self._sync_express(interest)
        except Exception as exc:
            log.warning("NDN express_interest failed (%s), using fallback", exc)
            return self._fallback(interest)

    def _sync_express(self, interest: Interest) -> Data:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._async_express(interest))
        finally:
            loop.close()

    async def _async_express(self, interest: Interest) -> Data:
        try:
            from ndn.app import NDNApp
            from ndn.encoding import Name
            from ndn.types import InterestNack, InterestTimeout
        except ImportError:
            return self._fallback(interest)

        app = NDNApp()
        for attempt in range(_RETRIES + 1):
            try:

                async def _run():
                    async with app:
                        name = Name.from_str(interest.name)
                        _name, _meta, content = await app.express_interest(
                            name,
                            must_be_fresh=True,
                            can_be_prefix=False,
                            lifetime=_TIMEOUT_MS,
                        )
                        return Data(name=interest.name, content=bytes(content or b""))

                return await asyncio.wait_for(
                    _run(), timeout=(_TIMEOUT_MS / 1000) + 0.5
                )
            except (
                InterestNack,
                InterestTimeout,
                asyncio.TimeoutError,
                Exception,
            ) as e:
                backoff = 0.1 * (2**attempt)
                log.warning(
                    "NDN attempt %d failed: %s — retry in %.2fs", attempt, e, backoff
                )
                if attempt < _RETRIES:
                    await asyncio.sleep(backoff)
        return self._fallback(interest)

    def _fallback(self, interest: Interest) -> Data:
        content = self._fallback_content or (
            b"fallback_shard_" + interest.name.encode()
        )
        return Data(name=interest.name, content=content)
