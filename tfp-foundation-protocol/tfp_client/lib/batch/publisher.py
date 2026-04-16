# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
BatchPublisher - Aggregates multiple TFP requests into batches for efficient processing.

This module provides batching functionality for TFP operations (publish, retrieve)
to reduce HTTP overhead and improve throughput through request aggregation.

Usage:
    publisher = BatchPublisher(batch_size=10, timeout_ms=100)
    results = await publisher.publish_batch(requests)
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class BatchRequest(BaseModel):
    """A single request in a batch operation."""
    id: str = Field(..., description="Unique request identifier")
    method: str = Field(..., description="HTTP method (GET, POST, etc.)")
    path: str = Field(..., description="API endpoint path")
    body: Optional[Dict[str, Any]] = Field(default=None, description="Request body")


class BatchResponse(BaseModel):
    """Response for a single request in a batch."""
    id: str = Field(..., description="Request identifier (matches BatchRequest.id)")
    status_code: int = Field(..., description="HTTP status code")
    body: Optional[Dict[str, Any]] = Field(default=None, description="Response body")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class BatchPublisher:
    """
    Batches multiple TFP requests for efficient processing.

    Aggregates requests and processes them in batches to reduce HTTP overhead.
    Uses asyncio for concurrent request processing.

    Args:
        batch_size: Maximum number of requests per batch (default: 10)
        timeout_ms: Reserved for future timeout-based batching (not currently used)
        max_concurrent: Maximum concurrent HTTP requests (default: 8)
    """

    def __init__(
        self,
        batch_size: int = 10,
        timeout_ms: int = 100,
        max_concurrent: int = 8,
    ):
        self._batch_size = batch_size
        self._timeout_ms = timeout_ms  # Reserved for future timeout-based batching
        self._max_concurrent = max_concurrent

    async def publish_batch(
        self, requests: List[BatchRequest], base_url: str = "http://localhost:8000"
    ) -> List[BatchResponse]:
        """
        Process a batch of requests concurrently.

        Args:
            requests: List of BatchRequest objects to process
            base_url: Base URL for the TFP API

        Returns:
            List of BatchResponse objects in the same order as requests
        """
        if not requests:
            return []

        try:
            import httpx
        except ImportError:
            logger.error("httpx is not installed; cannot process batch requests")
            return [
                BatchResponse(
                    id=req.id,
                    status_code=500,
                    error="httpx not installed"
                )
                for req in requests
            ]

        # Use httpx with connection pooling and HTTP/2
        limits = httpx.Limits(
            max_connections=self._max_concurrent * 2,
            max_keepalive_connections=self._max_concurrent,
        )

        async with httpx.AsyncClient(
            limits=limits,
            timeout=httpx.Timeout(30.0),
            http2=True,
        ) as client:
            semaphore = asyncio.Semaphore(self._max_concurrent)

            async def process_one(req: BatchRequest) -> BatchResponse:
                async with semaphore:
                    try:
                        url = f"{base_url}{req.path}"
                        if req.method.upper() == "GET":
                            response = await client.get(url)
                        elif req.method.upper() == "POST":
                            response = await client.post(url, json=req.body)
                        else:
                            return BatchResponse(
                                id=req.id,
                                status_code=400,
                                error=f"Unsupported method: {req.method}"
                            )

                        try:
                            body = response.json()
                        except Exception:
                            body = None

                        return BatchResponse(
                            id=req.id,
                            status_code=response.status_code,
                            body=body,
                        )
                    except Exception as exc:
                        logger.warning("Batch request failed (id=%s): %s", req.id, exc)
                        return BatchResponse(
                            id=req.id,
                            status_code=500,
                            error=str(exc),
                        )

            # Process all requests concurrently
            tasks = [process_one(req) for req in requests]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Handle exceptions in results
            final_results = []
            for req, result in zip(requests, results):
                if isinstance(result, Exception):
                    final_results.append(
                        BatchResponse(
                            id=req.id,
                            status_code=500,
                            error=str(result),
                        )
                    )
                else:
                    final_results.append(result)

            return final_results

    async def auto_batch(
        self, request_generator, base_url: str = "http://localhost:8000"
    ) -> List[BatchResponse]:
        """
        Automatically batch requests from a generator.

        Collects requests until batch_size is reached or timeout expires,
        then processes the batch.

        Args:
            request_generator: Async generator yielding BatchRequest objects
            base_url: Base URL for the TFP API

        Returns:
            List of BatchResponse objects
        """
        all_results = []
        current_batch = []

        async for request in request_generator:
            current_batch.append(request)

            if len(current_batch) >= self._batch_size:
                results = await self.publish_batch(current_batch, base_url)
                all_results.extend(results)
                current_batch = []

        # Process remaining partial batch
        if current_batch:
            results = await self.publish_batch(current_batch, base_url)
            all_results.extend(results)

        return all_results
