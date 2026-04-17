# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


_FALSE_VALUES = {"0", "false", "no", "off"}
_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RuntimeConfig:
    mode: str
    db_path: str
    enable_nostr: bool
    nostr_publish_enabled: bool
    nostr_trusted_pubkeys: frozenset[str]
    peer_secret: str
    admin_device_ids: frozenset[str]
    real_adapters: bool
    enable_rag: bool
    peer_nodes: frozenset[str]
    redis_url: str | None
    shard_size_kb: int
    supply_gossip_buffer: int


def _parse_bool(value: str | None, *, default: bool, var_name: str) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{var_name} must be one of 1/0/true/false/yes/no/on/off (got {value!r})"
    )


def _parse_csv_set(value: str | None, *, lowercase: bool) -> frozenset[str]:
    if value is None:
        return frozenset()
    items = {item.strip() for item in value.split(",") if item.strip()}
    if lowercase:
        items = {item.lower() for item in items}
    return frozenset(items)


def _parse_nonnegative_int(value: str | None, *, default: int, var_name: str) -> int:
    """Parse a non-negative integer (>= 0) from environment variable."""
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
        if parsed < 0:
            raise ValueError(f"{var_name} must be non-negative (got {parsed})")
        return parsed
    except ValueError as exc:
        raise ValueError(
            f"{var_name} must be a non-negative integer (got {value!r})"
        ) from exc


def _parse_positive_int(value: str | None, *, default: int, var_name: str) -> int:
    """Parse a positive integer from environment variable."""
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value.strip())
        if parsed <= 0:
            raise ValueError(f"{var_name} must be positive (got {parsed})")
        return parsed
    except ValueError as exc:
        raise ValueError(
            f"{var_name} must be a positive integer (got {value!r})"
        ) from exc


def _validate_url(value: str, *, var_name: str) -> None:
    """Validate that a string is a valid URL."""
    try:
        parsed = urlparse(value)
        if not all([parsed.scheme, parsed.netloc]):
            raise ValueError(f"{var_name} must be a valid URL (got {value!r})")
        if parsed.scheme not in {"http", "https", "redis", "rediss"}:
            raise ValueError(
                f"{var_name} must use http/https/redis/rediss scheme (got {parsed.scheme})"
            )
    except Exception as exc:
        raise ValueError(f"{var_name} must be a valid URL (got {value!r})") from exc


def _validate_nostr_private_key(raw_key: str) -> None:
    try:
        key = bytes.fromhex(raw_key)
    except ValueError as exc:
        raise ValueError("NOSTR_PRIVATE_KEY must be valid hex") from exc
    if len(key) != 32:
        raise ValueError(f"NOSTR_PRIVATE_KEY must be 64 hex chars (got {len(key) * 2})")


def _validate_csv_urls(value: str | None, *, var_name: str) -> None:
    """Validate comma-separated list of URLs."""
    if value is None or not value.strip():
        return

    urls = [u.strip() for u in value.split(",") if u.strip()]
    for url in urls:
        _validate_url(url, var_name=var_name)


def validate_runtime_config(
    environ: Mapping[str, str],
    *,
    default_db_path: str,
) -> RuntimeConfig:
    mode = environ.get("TFP_MODE", "demo").strip().lower()
    if mode not in {"demo", "production"}:
        raise ValueError("TFP_MODE must be 'demo' or 'production'")

    db_path = environ.get("TFP_DB_PATH", default_db_path).strip() or default_db_path
    enable_nostr = _parse_bool(
        environ.get("TFP_ENABLE_NOSTR"),
        default=True,
        var_name="TFP_ENABLE_NOSTR",
    )
    publish_default = mode != "production"
    nostr_publish_enabled = _parse_bool(
        environ.get("TFP_NOSTR_PUBLISH_ENABLED"),
        default=publish_default,
        var_name="TFP_NOSTR_PUBLISH_ENABLED",
    )
    nostr_trusted_pubkeys = _parse_csv_set(
        environ.get("TFP_NOSTR_TRUSTED_PUBKEYS", ""),
        lowercase=True,
    )
    peer_secret = environ.get("TFP_PEER_SECRET", "").strip()
    admin_device_ids = _parse_csv_set(
        environ.get("TFP_ADMIN_DEVICE_IDS", ""),
        lowercase=False,
    )

    # New validations
    real_adapters = _parse_bool(
        environ.get("TFP_REAL_ADAPTERS"),
        default=False,
        var_name="TFP_REAL_ADAPTERS",
    )

    enable_rag = _parse_bool(
        environ.get("TFP_ENABLE_RAG"),
        default=False,
        var_name="TFP_ENABLE_RAG",
    )

    peer_nodes_str = environ.get("TFP_PEER_NODES", "")
    _validate_csv_urls(peer_nodes_str, var_name="TFP_PEER_NODES")
    peer_nodes = _parse_csv_set(peer_nodes_str, lowercase=False)

    redis_url = environ.get("TFP_REDIS_URL")
    if redis_url:
        _validate_url(redis_url, var_name="TFP_REDIS_URL")

    shard_size_kb = _parse_nonnegative_int(
        environ.get("TFP_SHARD_SIZE_KB"),
        default=64,
        var_name="TFP_SHARD_SIZE_KB",
    )

    supply_gossip_buffer = _parse_positive_int(
        environ.get("TFP_SUPPLY_GOSSIP_BUFFER"),
        default=1000,
        var_name="TFP_SUPPLY_GOSSIP_BUFFER",
    )

    if mode == "production":
        if db_path == ":memory:":
            raise ValueError("TFP_DB_PATH must be persistent in production mode")
        if not peer_secret:
            raise ValueError("TFP_PEER_SECRET is required in production mode")
        if not admin_device_ids:
            raise ValueError(
                "TFP_ADMIN_DEVICE_IDS must contain at least one device in production mode"
            )

        nostr_private_key = environ.get("NOSTR_PRIVATE_KEY", "").strip()
        if nostr_private_key:
            _validate_nostr_private_key(nostr_private_key)
        elif enable_nostr and nostr_publish_enabled:
            raise ValueError(
                "NOSTR_PRIVATE_KEY is required when Nostr publishing is enabled in production mode"
            )

    return RuntimeConfig(
        mode=mode,
        db_path=db_path,
        enable_nostr=enable_nostr,
        nostr_publish_enabled=nostr_publish_enabled,
        nostr_trusted_pubkeys=nostr_trusted_pubkeys,
        peer_secret=peer_secret,
        admin_device_ids=admin_device_ids,
        real_adapters=real_adapters,
        enable_rag=enable_rag,
        peer_nodes=peer_nodes,
        redis_url=redis_url,
        shard_size_kb=shard_size_kb,
        supply_gossip_buffer=supply_gossip_buffer,
    )
