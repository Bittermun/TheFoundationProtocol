from dataclasses import dataclass
from typing import Mapping


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


def _validate_nostr_private_key(raw_key: str) -> None:
    try:
        key = bytes.fromhex(raw_key)
    except ValueError as exc:
        raise ValueError("NOSTR_PRIVATE_KEY must be valid hex") from exc
    if len(key) != 32:
        raise ValueError(f"NOSTR_PRIVATE_KEY must be 64 hex chars (got {len(key) * 2})")


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
    )
