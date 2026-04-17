# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
RetryHandler - Exponential backoff retry logic for HTTP requests.

Provides robust retry logic with exponential backoff for failed HTTP requests,
handling transient network errors and server issues gracefully.

Usage:
    retry_handler = RetryHandler(max_retries=3, base_delay=1.0)
    response = await retry_handler.upload_with_retry(client, url, chunk)
"""

import asyncio
import logging
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryHandler:
    """
    Handles retry logic with exponential backoff for HTTP requests.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds before first retry (default: 1.0)
        max_delay: Maximum delay between retries (default: 30.0)
        backoff_factor: Multiplier for exponential backoff (default: 2.0)
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
    ):
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor

    async def execute_with_retry(
        self,
        func: Callable[..., T],
        *args,
        **kwargs,
    ) -> T:
        """
        Execute an async function with retry logic and exponential backoff.

        Args:
            func: Async function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the function call

        Raises:
            Last exception if all retries are exhausted
        """
        last_exception = None

        for attempt in range(self._max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                last_exception = exc

                if attempt == self._max_retries:
                    # Last attempt failed, raise the exception
                    logger.error(
                        "All %d retry attempts failed: %s",
                        self._max_retries + 1,
                        exc,
                    )
                    raise

                # Check if error is retryable (transient errors only)
                if not self.should_retry(exc):
                    logger.error(
                        "Non-retryable error encountered (attempt %d/%d): %s",
                        attempt + 1,
                        self._max_retries + 1,
                        exc,
                    )
                    raise

                # Calculate delay with exponential backoff
                delay = min(
                    self._base_delay * (self._backoff_factor**attempt),
                    self._max_delay,
                )

                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                    delay,
                )

                await asyncio.sleep(delay)

        # This should never be reached, but for type safety
        if last_exception:
            raise last_exception
        raise RuntimeError("Retry logic failed unexpectedly")

    async def upload_with_retry(
        self,
        client,
        url: str,
        chunk: bytes,
        chunk_index: int,
        max_retries: Optional[int] = None,
    ):
        """
        Upload a chunk with retry logic and exponential backoff.

        Args:
            client: httpx.AsyncClient instance
            url: Upload URL
            chunk: Chunk bytes to upload
            chunk_index: Index of the chunk (for logging)
            max_retries: Override default max retries

        Returns:
            httpx Response object

        Raises:
            Exception if all retries are exhausted
        """
        if max_retries is None:
            max_retries = self._max_retries

        async def _upload():
            response = await client.post(
                url,
                content=chunk,
                headers={"Content-Type": "application/octet-stream"},
                timeout=30.0,
            )
            response.raise_for_status()
            return response

        return await self.execute_with_retry(
            _upload,
        )

    def should_retry(self, exception: Exception) -> bool:
        """
        Determine if an exception should trigger a retry.

        Args:
            exception: Exception to evaluate

        Returns:
            True if retry should be attempted, False otherwise
        """
        # Retry on transient errors
        error_str = str(exception).lower()

        # Network-related errors
        transient_errors = [
            "timeout",
            "connection",
            "network",
            "temporary",
            "503",  # Service Unavailable
            "502",  # Bad Gateway
            "504",  # Gateway Timeout
            "429",  # Too Many Requests
        ]

        return any(err in error_str for err in transient_errors)
