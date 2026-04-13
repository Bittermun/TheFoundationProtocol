from tfp_demo.config_validation import validate_runtime_config


def test_validate_runtime_config_defaults_to_demo():
    cfg = validate_runtime_config({}, default_db_path="test-default.db")
    assert cfg.mode == "demo"
    assert cfg.db_path == "test-default.db"
    assert cfg.nostr_publish_enabled is True


def test_validate_runtime_config_rejects_invalid_mode():
    try:
        validate_runtime_config({"TFP_MODE": "staging"}, default_db_path="pib.db")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "TFP_MODE" in str(exc)


def test_validate_runtime_config_requires_persistent_db_in_production():
    try:
        validate_runtime_config(
            {
                "TFP_MODE": "production",
                "TFP_DB_PATH": ":memory:",
                "TFP_PEER_SECRET": "peer-secret",
                "TFP_ADMIN_DEVICE_IDS": "admin-1",
            },
            default_db_path="pib.db",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "TFP_DB_PATH" in str(exc)


def test_validate_runtime_config_production_defaults_publish_disabled():
    cfg = validate_runtime_config(
        {
            "TFP_MODE": "production",
            "TFP_DB_PATH": "/tmp/tfp.db",
            "TFP_PEER_SECRET": "peer-secret",
            "TFP_ADMIN_DEVICE_IDS": "admin-1",
        },
        default_db_path="pib.db",
    )
    assert cfg.nostr_publish_enabled is False


def test_validate_runtime_config_requires_peer_secret_and_admin_allowlist():
    try:
        validate_runtime_config(
            {
                "TFP_MODE": "production",
                "TFP_DB_PATH": "/tmp/tfp.db",
            },
            default_db_path="pib.db",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "TFP_PEER_SECRET" in str(exc)


def test_validate_runtime_config_rejects_invalid_nostr_key_in_production():
    try:
        validate_runtime_config(
            {
                "TFP_MODE": "production",
                "TFP_DB_PATH": "/tmp/tfp.db",
                "TFP_PEER_SECRET": "peer-secret",
                "TFP_ADMIN_DEVICE_IDS": "admin-1",
                "NOSTR_PRIVATE_KEY": "invalid-key",
            },
            default_db_path="pib.db",
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "NOSTR_PRIVATE_KEY" in str(exc)
