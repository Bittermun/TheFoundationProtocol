"""
TFP Web Bridge v2.12

Exposes TFP protocol to browser extensions via simple intercept API.
Handles tfp:// URL scheme, content-type registration, and HTTP fallback.

Zero UI, zero dependencies—pure protocol adapter for community-built plugins.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse


class TFPContentType(Enum):
    """Content types supported by TFP."""

    VIDEO = "video/tfp"
    AUDIO = "audio/tfp"
    IMAGE = "image/tfp"
    TEXT = "text/tfp"
    APPLICATION = "application/tfp"
    UNKNOWN = "unknown"


@dataclass
class TFPRequest:
    """Represents a TFP protocol request from browser."""

    url: str  # tfp://hash or tfp://tag/category
    content_type: TFPContentType
    timestamp: float = field(default_factory=time.time)
    source_tab_id: Optional[int] = None
    priority: int = 0  # 0 = normal, >0 = high priority

    # Parsed components
    content_hash: Optional[str] = None
    tag_query: Optional[str] = None
    fallback_url: Optional[str] = None  # HTTP fallback if TFP fails


@dataclass
class TFPResponse:
    """Response from TFP protocol to browser."""

    success: bool
    content_hash: Optional[str]
    content_type: str
    data: Optional[bytes]
    metadata: Dict = field(default_factory=dict)

    # Performance metrics
    fetch_time_ms: float = 0.0
    cache_hit: bool = False
    source: str = "unknown"  # 'cache', 'mesh', 'broadcast', 'http_fallback'

    # Error handling
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def to_http_headers(self) -> Dict[str, str]:
        """Convert to HTTP response headers for browser."""
        headers = {
            "X-TFP-Hash": self.content_hash or "",
            "X-TFP-Source": self.source,
            "X-TFP-Cache-Hit": str(self.cache_hit).lower(),
            "X-TFP-Fetch-Time-Ms": str(self.fetch_time_ms),
            "Content-Type": self.content_type,
        }

        if self.metadata:
            for key, value in self.metadata.items():
                headers[f"X-TFP-{key}"] = str(value)

        return headers


@dataclass
class InterceptionResult:
    """Result of URL interception attempt."""

    intercepted: bool
    request: Optional[TFPRequest]
    reason: str = ""


class WebBridge:
    """
    Bridges TFP protocol with web browsers.

    Core features:
    - Intercept tfp:// URLs from browser extensions
    - Map content hashes to appropriate handlers
    - Provide HTTP fallback for non-TFP content
    - Zero UI (headless protocol adapter)
    """

    def __init__(self):
        self.request_handlers: Dict[TFPContentType, Callable] = {}
        self.intercept_log: List[dict] = []
        self.content_type_registry: Dict[str, TFPContentType] = {
            "mp4": TFPContentType.VIDEO,
            "webm": TFPContentType.VIDEO,
            "mp3": TFPContentType.AUDIO,
            "ogg": TFPContentType.AUDIO,
            "jpg": TFPContentType.IMAGE,
            "jpeg": TFPContentType.IMAGE,
            "png": TFPContentType.IMAGE,
            "gif": TFPContentType.IMAGE,
            "txt": TFPContentType.TEXT,
            "html": TFPContentType.TEXT,
            "json": TFPContentType.APPLICATION,
        }

    def register_handler(self, content_type: TFPContentType, handler: Callable) -> None:
        """
        Register a handler function for a content type.

        Args:
            content_type: Type of content to handle
            handler: Function that takes TFPRequest and returns TFPResponse
        """
        self.request_handlers[content_type] = handler

    def parse_tfp_url(self, url: str) -> Optional[TFPRequest]:
        """
        Parse a tfp:// URL into a TFPRequest.

        Supported formats:
        - tfp://<content_hash>
        - tfp://tag/<category>/<search_query>
        - tfp://<content_hash>?fallback=<http_url>

        Args:
            url: The tfp:// URL to parse

        Returns:
            TFPRequest or None if invalid
        """
        if not url.startswith("tfp://"):
            return None

        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        request = TFPRequest(
            url=url,
            content_type=TFPContentType.UNKNOWN,
            content_hash=None,
            tag_query=None,
            fallback_url=query_params.get("fallback", [None])[0],
        )

        # Parse hash-based URL: tfp://<hash>
        if parsed.netloc or (parsed.path and not parsed.path.startswith("/tag/")):
            potential_hash = parsed.netloc or parsed.path.lstrip("/")

            # Validate hash format (64 hex chars for SHA3-256)
            if len(potential_hash) == 64 and all(
                c in "0123456789abcdef" for c in potential_hash.lower()
            ):
                request.content_hash = potential_hash.lower()

                # Infer content type from extension if present
                if "." in potential_hash:
                    ext = potential_hash.split(".")[-1].lower()
                    request.content_type = self.content_type_registry.get(
                        ext, TFPContentType.UNKNOWN
                    )
                else:
                    request.content_type = TFPContentType.UNKNOWN

        # Parse tag-based URL: tfp://tag/<category>/<query>
        elif parsed.path.startswith("/tag/"):
            path_parts = parsed.path.split("/")
            if len(path_parts) >= 3:
                category = path_parts[2]
                query = "/".join(path_parts[3:]) if len(path_parts) > 3 else ""
                request.tag_query = f"{category}:{query}" if query else category
                request.content_type = TFPContentType.UNKNOWN

        return request

    def intercept_request(self, url: str, tab_id: int = None) -> InterceptionResult:
        """
        Intercept a browser request and determine if it's a TFP URL.

        Args:
            url: The requested URL
            tab_id: Browser tab ID (for extension integration)

        Returns:
            InterceptionResult with decision and parsed request
        """
        if not url.startswith("tfp://"):
            return InterceptionResult(
                intercepted=False, request=None, reason="Not a TFP URL"
            )

        request = self.parse_tfp_url(url)

        if not request:
            return InterceptionResult(
                intercepted=False, request=None, reason="Invalid TFP URL format"
            )

        request.source_tab_id = tab_id

        # Log interception
        self._log_interception("intercepted", request)

        return InterceptionResult(
            intercepted=True, request=request, reason="TFP URL detected"
        )

    async def handle_request(self, request: TFPRequest) -> TFPResponse:
        """
        Handle a TFP request by routing to appropriate handler.

        Args:
            request: Parsed TFPRequest

        Returns:
            TFPResponse with content or error
        """
        start_time = time.time()

        # Check if we have a handler for this content type
        handler = self.request_handlers.get(request.content_type)

        if not handler and request.content_type != TFPContentType.UNKNOWN:
            # Try unknown handler as fallback
            handler = self.request_handlers.get(TFPContentType.UNKNOWN)

        if not handler:
            return TFPResponse(
                success=False,
                content_hash=request.content_hash,
                content_type="text/plain",
                data=None,
                error_code="NO_HANDLER",
                error_message=f"No handler registered for content type {request.content_type.value}",
            )

        try:
            # Call handler (may be async)
            if hasattr(handler, "__await__"):
                response = await handler(request)
            else:
                response = handler(request)

            # Add performance metrics
            response.fetch_time_ms = (time.time() - start_time) * 1000

            return response

        except Exception as e:
            # Handler failed, try HTTP fallback
            if request.fallback_url:
                return TFPResponse(
                    success=False,
                    content_hash=request.content_hash,
                    content_type="text/plain",
                    data=None,
                    error_code="HANDLER_FAILED",
                    error_message=str(e),
                    metadata={"fallback_url": request.fallback_url},
                )

            return TFPResponse(
                success=False,
                content_hash=request.content_hash,
                content_type="text/plain",
                data=None,
                error_code="HANDLER_ERROR",
                error_message=f"Handler error: {str(e)}",
            )

    def register_content_type(
        self, extension: str, content_type: TFPContentType
    ) -> None:
        """
        Register a file extension to content type mapping.

        Args:
            extension: File extension (e.g., 'mp4')
            content_type: TFP content type
        """
        self.content_type_registry[extension.lower()] = content_type

    def _log_interception(self, event_type: str, request: TFPRequest) -> None:
        """Log interception event (no PII)."""
        entry = {
            "timestamp": time.time(),
            "event_type": event_type,
            "url_pattern": "tfp://..." if request.content_hash else "tfp://tag/...",
            "content_type": request.content_type.value,
            "has_fallback": request.fallback_url is not None,
        }
        self.intercept_log.append(entry)

        # Keep log bounded
        if len(self.intercept_log) > 1000:
            self.intercept_log = self.intercept_log[-1000:]

    def get_statistics(self) -> dict:
        """Get bridge usage statistics."""
        total_interceptions = len(self.intercept_log)

        # Count by content type
        type_counts = {}
        for entry in self.intercept_log:
            ct = entry["content_type"]
            type_counts[ct] = type_counts.get(ct, 0) + 1

        return {
            "total_interceptions": total_interceptions,
            "by_content_type": type_counts,
            "registered_handlers": list(self.request_handlers.keys()),
            "registered_extensions": len(self.content_type_registry),
        }

    def generate_manifest(self) -> dict:
        """
        Generate browser extension manifest snippet.

        This can be embedded in a browser extension's manifest.json
        to enable tfp:// URL handling.
        """
        return {
            "name": "TFP Protocol Handler",
            "version": "2.12",
            "description": "Enables tfp:// URL scheme for decentralized content access",
            "protocol_handlers": [
                {
                    "protocol": "tfp",
                    "name": "TFP Decentralized Content",
                    "uriTemplate": "tfp://%s",
                }
            ],
            "permissions": ["webRequest", "webRequestBlocking"],
            "content_scripts": [
                {
                    "matches": ["<all_urls>"],
                    "js": ["tfp_bridge.js"],
                    "run_at": "document_start",
                }
            ],
            "note": "This manifest enables browser integration with TFP protocol. No PII collected.",
        }


# Example handler functions (stubs for plugin developers)
def example_video_handler(request: TFPRequest) -> TFPResponse:
    """Example video content handler."""
    # In production, this would:
    # 1. Query NDN for content_hash
    # 2. Decode RaptorQ shards
    # 3. Reassemble from chunk cache
    # 4. Return video bytes

    return TFPResponse(
        success=True,
        content_hash=request.content_hash,
        content_type="video/mp4",
        data=b"\\x00" * 1000,  # Placeholder
        metadata={"duration_ms": 5000},
        cache_hit=True,
        source="cache",
    )


def example_unknown_handler(request: TFPRequest) -> TFPResponse:
    """Generic handler for unknown content types."""
    return TFPResponse(
        success=True,
        content_hash=request.content_hash,
        content_type="application/octet-stream",
        data=b"\\x00" * 500,
        source="mesh",
    )


# Example usage
if __name__ == "__main__":
    bridge = WebBridge()

    # Register handlers
    bridge.register_handler(TFPContentType.VIDEO, example_video_handler)
    bridge.register_handler(TFPContentType.UNKNOWN, example_unknown_handler)

    # Test URL parsing
    test_urls = [
        "tfp://abc123def456...64chars...xyz",
        "tfp://tag/music/synthwave",
        "tfp://hash123?fallback=https://example.com/file.mp4",
        "https://example.com",  # Should not intercept
    ]

    print("=== URL Interception Test ===")
    for url in test_urls:
        result = bridge.intercept_request(url, tab_id=42)
        print(f"\\nURL: {url[:50]}...")
        print(f"Intercepted: {result.intercepted}")
        print(f"Reason: {result.reason}")
        if result.request:
            print(f"Content Hash: {result.request.content_hash}")
            print(f"Tag Query: {result.request.tag_query}")

    # Generate browser manifest
    print("\\n\\n=== Browser Extension Manifest ===")
    import json

    manifest = bridge.generate_manifest()
    print(json.dumps(manifest, indent=2))

    # Get statistics
    print("\\n\\n=== Bridge Statistics ===")
    stats = bridge.get_statistics()
    print(f"Total Interceptions: {stats['total_interceptions']}")
    print(f"Registered Handlers: {stats['registered_handlers']}")
