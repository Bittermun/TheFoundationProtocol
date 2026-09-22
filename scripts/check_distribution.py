# SPDX-License-Identifier: Apache-2.0
"""Check a built wheel contains the runnable demo and no tests or local data."""

import argparse
import zipfile
from pathlib import Path

REQUIRED = {
    "tfp_cli/main.py", "tfp_cli/demo.py", "tfp_cli/smoke.py",
    "tfp_cli/operational_smoke.py",
    "tfp_demo/server.py", "tfp_demo/samples.py",
    "tfp_client/lib/core/tfp_engine.py", "tfp_core_v4/cdc.py",
    "tfp_core_v4/visualizer_server.py",
    "tfp_core_v4/bulletin.py", "tfp_core_v4/bulletin_identity.py",
    "tfp_demo/static/acoustic_stream.js",
    "tfp_demo/static/visualizer.html", "tfp_demo/static/legacy_visualizer_v1.html",
    "tfp_demo/static/acoustic_receiver.html", "tfp_demo/static/sample_motion.webm",
    "demo/index.html", "demo/manifest.json", "demo/service-worker.js",
    "demo/assets/app.js", "demo/assets/app.css", "demo/assets/icon.svg",
}


def check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as wheel:
        names = set(wheel.namelist())
    missing = REQUIRED - names
    if missing:
        raise ValueError(f"Missing runtime files: {sorted(missing)}")
    for name in sorted(names):
        parts = Path(name).parts
        if any(part in {"tests", "__pycache__", ".agents", "tfp_testbed"} for part in parts):
            raise ValueError(f"Non-runtime directory in wheel: {name}")
        if Path(name).name.startswith("test_") or name.endswith(("_test.py", ".db", ".db-wal", ".db-shm", ".pem", ".key")):
            raise ValueError(f"Test or local runtime data in wheel: {name}")
    print(f"PASS: {path.name} contains the complete demo and no test suites or local databases.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    check_wheel(parser.parse_args().wheel)
