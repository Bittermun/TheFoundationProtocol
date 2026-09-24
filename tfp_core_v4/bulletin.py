# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Broadcast Bulletin Packaging & Verification Module for TFP v4.0.

Provides cohesive preparation, recoverable export, signature verification,
airtime budgeting, and audio recovery for broadcast bulletins.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from tfp_client.lib.audio.afsk_demodulator import AFSKDemodulator
from tfp_client.lib.audio.afsk_modulator import MAX_AFSK_PAYLOAD_SIZE, AFSKModulator

from tfp_core_v4.bulletin_identity import (
    SIGNATURE_VERSION,
    sign_bulletin_content,
    validate_identity,
    verify_bulletin_signature,
)
from tfp_core_v4.node import TFPNode

log = logging.getLogger("tfp.bulletin")

__all__ = [
    "AirtimeLimitExceededError",
    "estimate_bulletin_airtime",
    "import_bulletin_package",
    "prepare_bulletin_package",
    "sign_bulletin_content",
    "verify_bulletin_signature",
]


class AirtimeLimitExceededError(ValueError):
    """Raised when a bulletin payload exceeds the configured airtime limit."""


def estimate_bulletin_airtime(
    payload_len: int,
    baud_rate: int = 1200,
    preamble_flags: int = 16,
) -> float:
    """
    Calculates exact audio airtime in seconds for a framed packet.
    Layout: [PREAMBLE: N*8b] [LEN: 16b] [PAYLOAD: L*8b] [CRC: 16b] [POSTAMBLE: 4*8b]
    """
    total_frame_bytes = preamble_flags + 2 + payload_len + 2 + 4
    total_bits = total_frame_bytes * 8
    return total_bits / baud_rate


def prepare_bulletin_package(
    bulletin_id: str,
    revision: int,
    title: str,
    content_text: str,
    output_dir: Path | str,
    private_key: Any | None = None,
    airtime_limit_seconds: float | None = None,
    baud_rate: int = 1200,
    sample_rate: int = 16000,
    preamble_flags: int = 16,
    metadata_extra: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Prepares a complete package and retains a backup during explicit replacement.

    Enforces airtime budget limits before synthesis.
    Outputs:
      - broadcast.wav
      - bulletin.txt
      - metadata.json
      - instructions.txt
      - preparation_record.json
    """
    if not bulletin_id or not bulletin_id.strip():
        raise ValueError("bulletin_id cannot be empty")
    validate_identity(bulletin_id, revision, title)
    if not content_text:
        raise ValueError("content_text cannot be empty")
    content_text = content_text.replace("\r\n", "\n").replace("\r", "\n")

    requested_path = Path(output_dir).absolute()
    if requested_path.is_symlink():
        raise ValueError("Refusing to replace a symbolic-link destination")
    target_path = requested_path.resolve()
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Target package directory already exists: {target_path}")
    if target_path.exists():
        try:
            previous_record = json.loads((target_path / "preparation_record.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Replacement requires an existing TFP bulletin package") from exc
        if previous_record.get("operation") != "bulletin_package_export":
            raise ValueError("Replacement requires an existing TFP bulletin package")

    # 1. Compute content hash over raw UTF-8 text
    content_bytes = content_text.encode("utf-8")
    content_hash = hashlib.sha3_256(content_bytes).hexdigest()

    # 2. Digital signature
    publisher_id = "unsigned"
    signature_hex = None
    verification_status = "unsigned"
    if private_key is not None:
        publisher_id, signature_hex = sign_bulletin_content(
            bulletin_id, revision, content_hash, private_key, title=title or bulletin_id
        )
        verification_status = "signed"

    # 3. Construct wire payload
    wire_dict: dict[str, Any] = {
        "v": SIGNATURE_VERSION,
        "id": bulletin_id,
        "rev": revision,
        "title": title or bulletin_id,
        "body": content_text,
        "pub": publisher_id if publisher_id != "unsigned" else None,
        "sig": signature_hex,
    }
    wire_payload = json.dumps(wire_dict, ensure_ascii=False).encode("utf-8")
    if len(wire_payload) > MAX_AFSK_PAYLOAD_SIZE:
        raise ValueError(
            f"Bulletin wire payload ({len(wire_payload)} bytes) exceeds maximum allowable "
            f"size ({MAX_AFSK_PAYLOAD_SIZE} bytes). Shorten text or split bulletin."
        )

    # 4. Check airtime limit BEFORE expensive audio synthesis
    estimated_duration = estimate_bulletin_airtime(
        len(wire_payload), baud_rate=baud_rate, preamble_flags=preamble_flags
    )
    if airtime_limit_seconds is not None and estimated_duration > airtime_limit_seconds:
        raise AirtimeLimitExceededError(
            f"Estimated bulletin airtime ({estimated_duration:.2f}s) exceeds configured "
            f"airtime limit ({airtime_limit_seconds:.2f}s). Encoding aborted."
        )

    # 5. Synthesize 16-bit PCM WAV audio
    modulator = AFSKModulator(
        sample_rate=sample_rate,
        baud_rate=baud_rate,
        preamble_flags=preamble_flags,
    )
    wav_bytes = modulator.synthesize_wav(wire_payload)
    actual_duration = len(wav_bytes) / (sample_rate * 2)

    # 6. Build metadata and preparation records
    now_ts = time.time()
    now_iso = datetime.datetime.now(datetime.UTC).isoformat()
    meta: dict[str, Any] = {
        "bulletin_id": bulletin_id,
        "revision": revision,
        "title": title or bulletin_id,
        "content_hash": content_hash,
        "publisher_id": publisher_id,
        "signature_hex": signature_hex,
        "verification_status": verification_status,
        "signature_version": SIGNATURE_VERSION,
        "publisher_trust": "not_established",
        "encoding_profile": f"bell202_{baud_rate}",
        "sample_rate": sample_rate,
        "baud_rate": baud_rate,
        "audio_duration_seconds": round(actual_duration, 3),
        "payload_bytes": len(wire_payload),
        "content_bytes": len(content_bytes),
        "created_at": now_ts,
        "created_at_iso": now_iso,
    }
    if metadata_extra:
        meta["extra"] = metadata_extra

    instructions = (
        "THE FOUNDATION PROTOCOL - BROADCAST PLAYBACK INSTRUCTIONS\n"
        "========================================================\n"
        f"Bulletin ID : {bulletin_id} (Rev {revision})\n"
        f"Title       : {title}\n"
        f"Duration    : {actual_duration:.2f} seconds\n"
        f"Profile     : Bell 202 AFSK @ {baud_rate} Baud ({sample_rate} Hz Mono)\n"
        "========================================================\n"
        "1. Connect audio player line-out / aux to FM transmitter or PA audio in.\n"
        "2. Set playback volume to 70-80% to avoid signal distortion / clipping.\n"
        "3. Air broadcast.wav once or schedule repeat playback as needed.\n"
        "4. Listeners decode using 'tfp bulletin-import' or browser acoustic receiver.\n"
    )

    prep_record = {
        "generator": "The Foundation Protocol v4.0.0",
        "operation": "bulletin_package_export",
        "timestamp_iso": now_iso,
        "bulletin_id": bulletin_id,
        "revision": revision,
        "airtime_seconds": round(actual_duration, 3),
        "airtime_limit_seconds": airtime_limit_seconds,
        "sha3_content_hash": content_hash,
        "signed": bool(signature_hex),
    }

    # 7. Stage complete files before installation; replacement keeps a backup.
    parent_dir = target_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = parent_dir / f".tmp_{target_path.name}_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=False)

    try:
        (temp_dir / "broadcast.wav").write_bytes(wav_bytes)
        (temp_dir / "bulletin.txt").write_bytes(content_text.encode("utf-8"))
        (temp_dir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (temp_dir / "instructions.txt").write_text(instructions, encoding="utf-8")
        (temp_dir / "preparation_record.json").write_text(json.dumps(prep_record, indent=2), encoding="utf-8")

        backup = None
        if target_path.exists():
            if not overwrite:
                raise FileExistsError(f"Target package directory already exists: {target_path}")
            # Move, never delete, an existing destination. Keep the previous
            # package recoverable even if installation or rollback fails.
            backup = parent_dir / f".previous_{target_path.name}_{uuid.uuid4().hex}"
            target_path.rename(backup)
        try:
            temp_dir.rename(target_path)
        except OSError:
            if backup is not None and not target_path.exists():
                try:
                    backup.rename(target_path)
                except OSError as rollback_error:
                    log.error("Previous package retained at %s: %s", backup, rollback_error)
            raise
        if backup is not None:
            meta["previous_package_path"] = str(backup)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    return meta


def import_bulletin_package(
    package_dir_or_wav: Path | str,
    node: TFPNode,
    baud_rate: int = 1200,
    sample_rate: int = 16000,
) -> dict[str, Any]:
    """
    Decodes audio from a broadcast package or WAV file, validates CRC16
    and Ed25519 digital signatures, and persists content into authoritative TFPNode storage.
    """
    p = Path(package_dir_or_wav).resolve()
    if p.is_dir():
        wav_path = p / "broadcast.wav"
        if not wav_path.exists():
            raise FileNotFoundError(f"broadcast.wav not found in package directory: {p}")
        wav_bytes = wav_path.read_bytes()
    elif p.is_file():
        wav_bytes = p.read_bytes()
    else:
        raise FileNotFoundError(f"Input path not found: {p}")

    demod = AFSKDemodulator(sample_rate=sample_rate, baud_rate=baud_rate)
    packets = demod.decode_wav(wav_bytes, fallback_300=True)

    if not packets:
        raise ValueError(f"Demodulation failed: 0 valid CRC16 packets recovered from {p.name}")

    imported_bulletins = []
    for pkt in packets:
        try:
            payload_str = pkt.decode("utf-8")
            wire_data = json.loads(payload_str)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            log.warning(f"Skipping non-bulletin packet payload: {exc}")
            continue

        if not isinstance(wire_data, dict):
            continue
        b_id = wire_data.get("id")
        rev = wire_data.get("rev", 1)
        title = wire_data.get("title", b_id)
        body = wire_data.get("body", "")
        pub_id = wire_data.get("pub") or "unsigned"
        sig_hex = wire_data.get("sig")

        if not isinstance(body, str) or not body:
            raise ValueError("Bulletin body must be a nonempty string")
        content_text = body.replace("\r\n", "\n").replace("\r", "\n")
        validate_identity(b_id, rev, title)

        body_bytes = content_text.encode("utf-8")
        c_hash = hashlib.sha3_256(body_bytes).hexdigest()

        # Check if authentic duplicate replay
        is_duplicate = False
        existing = node.get_bulletin(b_id, rev)
        if existing is not None:
            ex_meta, _ = existing
            if ex_meta.get("content_hash") == c_hash:
                is_duplicate = True
        else:
            wm = node.get_bulletin_watermark(pub_id, b_id)
            if wm and wm.get("max_revision") == rev and wm.get("latest_content_hash") == c_hash:
                is_duplicate = True

        # Durably persist into authoritative node storage
        recipe = node.store_bulletin(
            bulletin_id=b_id,
            revision=rev,
            data=body_bytes,
            title=title,
            publisher_id=pub_id,
            signature_hex=sig_hex,
            signature_version=wire_data.get("v", 1),
            metadata={"origin": "broadcast_audio", "source_file": p.name},
        )

        imported_bulletins.append({
            "bulletin_id": b_id,
            "revision": rev,
            "title": title,
            "content_hash": c_hash,
            "root_hash": recipe.root_hash,
            "publisher_id": pub_id,
            "signature_hex": sig_hex,
            "verified_status": recipe.metadata["verified_status"],
            "publisher_trust": "not_established",
            "data_size": len(body_bytes),
            "duplicate": is_duplicate,
            "status": "duplicate" if is_duplicate else "stored",
        })

    if not imported_bulletins:
        raise ValueError("No valid structured bulletin payloads could be extracted from audio packets")

    return imported_bulletins[0]
