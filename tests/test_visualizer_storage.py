# SPDX-License-Identifier: Apache-2.0
"""Visualizer runtime data must not depend on a writable installation."""

from pathlib import Path

from tfp_core_v4 import visualizer_server


def test_visualizer_does_not_write_to_installation(tmp_path, monkeypatch):
    installation = tmp_path / "installed"
    installation.mkdir()
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(visualizer_server, "_repo_root", installation)
    monkeypatch.setenv("TFP_VISUALIZER_DATA_DIR", str(runtime))
    original_mkdir = Path.mkdir

    def guarded_mkdir(path, *args, **kwargs):
        if path.is_relative_to(installation):
            raise PermissionError("read-only installation")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", guarded_mkdir)
    server, _ = visualizer_server.create_visualizer_server(port=0)
    try:
        assert len(list((runtime / "articles").glob("*.json"))) >= 6
        assert list(installation.iterdir()) == []
    finally:
        server.server_close()


def test_visualizer_defaults_to_user_storage(tmp_path, monkeypatch):
    monkeypatch.delenv("TFP_VISUALIZER_DATA_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    server, _ = visualizer_server.create_visualizer_server(port=0)
    try:
        assert len(list((tmp_path / ".tfp" / "visualizer" / "articles").glob("*.json"))) >= 6
    finally:
        server.server_close()


def test_explicit_storage_overrides_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TFP_VISUALIZER_DATA_DIR", str(tmp_path / "unused"))
    storage = tmp_path / "chosen"
    server, _ = visualizer_server.create_visualizer_server(port=0, data_dir=storage)
    try:
        assert len(list((storage / "articles").glob("*.json"))) >= 6
        assert not (tmp_path / "unused").exists()
    finally:
        server.server_close()
