# SPDX-License-Identifier: Apache-2.0
"""Run with a fresh wheel installation using Python -I -B outside the checkout."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.afsk_modulator import AFSKModulator

import tfp_core_v4.bulletin
from tfp_core_v4.node import TFPNode
from tfp_core_v4.visualizer_server import get_static_assets_dir


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def cli(database, *args, succeeds=True):
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-m", "tfp_core_v4.cli", "--db", str(database), *args],
        capture_output=True, text=True, encoding="utf-8", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "TFP_DB_PATH": str(database)},
    )
    check((result.returncode == 0) == succeeds, result.stdout + result.stderr)
    return result.stdout


def main():
    prefix = Path(sys.prefix).resolve()
    origin = Path(tfp_core_v4.bulletin.__file__).resolve()
    check(origin.is_relative_to(prefix), f"Source checkout leaked into import: {origin}")
    assets = get_static_assets_dir().resolve()
    check(assets.is_relative_to(prefix), f"Assets are not installed: {assets}")
    check((assets / "acoustic_stream.js").is_file(), "Streaming decoder missing from wheel")
    key = Ed25519PrivateKey.generate().private_bytes_raw().hex()
    with tempfile.TemporaryDirectory(prefix="tfp_installed_bulletin_") as temporary:
        root = Path(temporary)
        database = root / "node.db"
        for revision in (1, 2):
            package = root / f"revision-{revision}"
            body = f"Unseen installed-package message {root.name}; correction {revision}."
            cli(database, "bulletin-prepare", body, "--id", "installed-journey",
                "--revision", str(revision), "--title", f"Notice {revision}",
                "--out-dir", str(package), "--key", key)
            audio = package / "broadcast.wav"
            result = cli(database, "bulletin-import", str(audio))
            check("verified_ed25519" in result, "Signature was not verified")
            before = TFPNode(db_path=database).get_bulletin("installed-journey")
            cli(database, "bulletin-import", str(audio))
            check(TFPNode(db_path=database).get_bulletin("installed-journey") == before,
                  "Duplicate import changed the accepted record")
            check(before[1] == body.encode(), "Installed CLI did not retain exact content")
            check(before[0]["publisher_trust"] == "not_established", "Signature confused with trust")

        packet = AFSKDemodulator().decode_wav(audio.read_bytes())[0]
        wire = json.loads(packet)
        wire["title"] = "Forged headline"
        tampered = root / "tampered.wav"
        tampered.write_bytes(AFSKModulator().synthesize_wav(json.dumps(wire).encode()))
        cli(database, "bulletin-import", str(tampered), succeeds=False)
        check(TFPNode(db_path=database).get_bulletin("installed-journey") == before,
              "Invalid signature replaced accepted data")
        check("installed-journey" in cli(database, "bulletin-list"), "CLI list missed bulletin")
        check(body in cli(database, "bulletin-read", "installed-journey"), "CLI read lost content")
        search = cli(database, "search", "correction")
        check(before[0]["root_hash"] in search and body in search, "CLI search missed bulletin content")
        old_audio = audio.read_bytes()
        cli(database, "bulletin-prepare", "collision", "--id", "collision",
            "--out-dir", str(package), succeeds=False)
        check(audio.read_bytes() == old_audio, "Export collision destroyed package")
    print(f"PASS: installed CLI preparation, receipt, revisions, persistence, rejection and discovery ({origin})")


if __name__ == "__main__":
    main()
