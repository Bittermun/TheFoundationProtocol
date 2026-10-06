"""Reproducible benchmark and comparison of archive-delta backends.

Runs CDC, Zstandard, and full-file baselines in separate measured subprocesses,
sampling process-tree RSS and elapsed time, and independently verifying reconstruction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any

try:
    import psutil
except ImportError:
    psutil = None

try:
    import zstandard as zstd
except ImportError:
    zstd = None


def file_sha3_256(path: Path) -> str:
    hasher = hashlib.sha3_256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def monitor_tree_peak_rss(proc: subprocess.Popen[bytes], timeout_seconds: float = 120.0) -> tuple[int, bool]:
    peak_rss = 0
    timed_out = False
    start_time = time.monotonic()

    if psutil is None:
        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            timed_out = True
        return peak_rss, timed_out

    try:
        p = psutil.Process(proc.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        proc.wait()
        return peak_rss, timed_out

    while proc.poll() is None:
        if time.monotonic() - start_time > timeout_seconds:
            timed_out = True
            try:
                for child in p.children(recursive=True):
                    child.kill()
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            proc.wait()
            break

        try:
            tree_rss = p.memory_info().rss + sum(
                child.memory_info().rss for child in p.children(recursive=True)
            )
            peak_rss = max(peak_rss, tree_rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        time.sleep(0.02)

    return peak_rss, timed_out


def run_worker_encode(backend: str, base: Path, target: Path, artifact: Path) -> None:
    if backend == "cdc":
        from tfp_core_v4.zim_sync import ZimDeltaEngine
        ZimDeltaEngine().create_patch(base, target, artifact)
    elif backend == "zstd":
        from tfp_core_v4.library_updates.zstd_delta import create_zstd_delta
        create_zstd_delta(base, target, artifact)
    elif backend == "full":
        shutil.copyfile(target, artifact)
    else:
        raise ValueError(f"Unknown backend: {backend}")


def run_worker_decode(
    backend: str,
    base: Path,
    artifact: Path,
    reconstructed: Path,
    target_size: int,
    base_sha3: str = "",
    target_sha3: str = "",
) -> None:
    if backend == "cdc":
        from tfp_core_v4.zim_sync import ZimDeltaEngine
        ZimDeltaEngine().apply_patch(base, artifact, reconstructed)
    elif backend == "zstd":
        from tfp_core_v4.library_updates.zstd_delta import apply_zstd_delta
        apply_zstd_delta(
            base,
            artifact,
            reconstructed,
            base_sha3=base_sha3,
            target_sha3=target_sha3,
            target_size=target_size,
        )
    elif backend == "full":
        shutil.copyfile(artifact, reconstructed)
    else:
        raise ValueError(f"Unknown backend: {backend}")


def measure_stage(
    python_exe: Path,
    args: list[str],
    timeout_seconds: float = 120.0,
) -> tuple[int, float, int, str, bool]:
    """Runs a worker command in a measured child process. Returns (returncode, elapsed, peak_rss, stdout/stderr, timed_out)."""
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{existing_pp}" if existing_pp else str(repo_root)
    start_time = time.monotonic()
    proc = subprocess.Popen(
        [str(python_exe), str(Path(__file__).resolve()), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(repo_root),
        env=env,
    )
    peak_rss, timed_out = monitor_tree_peak_rss(proc, timeout_seconds=timeout_seconds)
    stdout, stderr = proc.communicate()
    elapsed = round(time.monotonic() - start_time, 4)
    output = (stdout + stderr).decode("utf-8", errors="replace")
    return proc.returncode, elapsed, peak_rss, output, timed_out


def get_git_info() -> tuple[str, bool]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], text=True, stderr=subprocess.DEVNULL
        ).strip()
        return commit, len(status) > 0
    except Exception:
        return "unknown", False


def evaluate_backend(
    backend: str,
    base: Path,
    target: Path,
    work_dir: Path,
    python_exe: Path,
    target_sha3: str,
    base_sha3: str,
    target_size: int,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    backend_dir = work_dir / backend
    backend_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = backend_dir / f"artifact.{backend}"
    reconstructed_path = backend_dir / "reconstructed.zim"

    # Encode stage
    encode_args = [
        "--internal-worker-encode",
        "--backend", backend,
        "--base", str(base),
        "--target", str(target),
        "--artifact", str(artifact_path),
    ]
    ret, enc_elapsed, enc_rss, enc_out, enc_timeout = measure_stage(
        python_exe, encode_args, timeout_seconds=timeout_seconds
    )
    if enc_timeout:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": f"Encode timed out after {timeout_seconds}s",
            "raw_payload": None,
            "package": None,
        }
    if ret != 0:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": f"Encode exited with code {ret}: {enc_out.strip()}",
            "raw_payload": None,
            "package": None,
        }
    if not artifact_path.exists() or artifact_path.stat().st_size == 0:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": "Artifact was not produced or is 0 bytes",
            "raw_payload": None,
            "package": None,
        }

    artifact_size = artifact_path.stat().st_size
    artifact_sha3 = file_sha3_256(artifact_path)

    # Decode stage
    decode_args = [
        "--internal-worker-decode",
        "--backend", backend,
        "--base", str(base),
        "--artifact", str(artifact_path),
        "--reconstructed", str(reconstructed_path),
        "--target-size", str(target_size),
        "--base-sha3", base_sha3,
        "--target-sha3", target_sha3,
    ]
    ret, dec_elapsed, dec_rss, dec_out, dec_timeout = measure_stage(
        python_exe, decode_args, timeout_seconds=timeout_seconds
    )
    if dec_timeout:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": f"Decode timed out after {timeout_seconds}s",
            "raw_payload": None,
            "package": None,
        }
    if ret != 0:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": f"Decode exited with code {ret}: {dec_out.strip()}",
            "raw_payload": None,
            "package": None,
        }
    if not reconstructed_path.exists() or reconstructed_path.stat().st_size != target_size:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": "Reconstructed file missing or incorrect size",
            "raw_payload": None,
            "package": None,
        }

    rec_sha3 = file_sha3_256(reconstructed_path)
    rec_matches = (rec_sha3 == target_sha3)
    if not rec_matches:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": f"Reconstructed SHA3 mismatch: got {rec_sha3}, expected {target_sha3}",
            "raw_payload": None,
            "package": None,
        }

    max_rss = max(enc_rss, dec_rss)
    if max_rss > 256 * 1024 * 1024:
        return {
            "backend": backend,
            "status": "failed",
            "failure_reason": f"Peak RSS {max_rss} exceeded 256 MiB cap",
            "raw_payload": None,
            "package": None,
        }

    raw_payload_info = {
        "artifact_bytes": artifact_size,
        "artifact_sha3": artifact_sha3,
        "encode_elapsed_seconds": enc_elapsed,
        "decode_elapsed_seconds": dec_elapsed,
        "encode_peak_rss_bytes": enc_rss,
        "decode_peak_rss_bytes": dec_rss,
        "reconstructed_sha3": rec_sha3,
        "reconstructed_matches": rec_matches,
    }

    return {
        "backend": backend,
        "status": "passed",
        "failure_reason": None,
        "raw_payload": raw_payload_info,
        "package": None,
    }


def generate_benchmark_report(
    base: Path,
    target: Path,
    out: Path,
    python_exe: Path,
    backends: tuple[str, ...] = ("cdc", "zstd", "full"),
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    base = base.resolve()
    target = target.resolve()
    base_size = base.stat().st_size
    target_size = target.stat().st_size
    base_sha3 = file_sha3_256(base)
    target_sha3 = file_sha3_256(target)

    git_commit, git_dirty = get_git_info()

    provenance = "CC0-1.0"
    fixtures_json = base.parent / "fixtures.json"
    if fixtures_json.exists():
        try:
            data = json.loads(fixtures_json.read_bytes())
            provenance = data.get("content_license", provenance)
        except Exception:
            pass

    report: dict[str, Any] = {
        "schema_version": 1,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "python_version": sys.version,
        "library_versions": {
            "zstandard": zstd.__version__ if zstd is not None else None,
            "psutil": psutil.__version__ if psutil is not None else None,
        },
        "inputs": {
            "base": {
                "path": str(base),
                "size_bytes": base_size,
                "sha3_256": base_sha3,
            },
            "target": {
                "path": str(target),
                "size_bytes": target_size,
                "sha3_256": target_sha3,
            },
            "license_provenance": provenance,
        },
        "results": {},
    }

    with tempfile.TemporaryDirectory(prefix="tfp-bench-") as tmpdir:
        work_dir = Path(tmpdir)
        for b in backends:
            report["results"][b] = evaluate_backend(
                backend=b,
                base=base,
                target=target,
                work_dir=work_dir,
                python_exe=python_exe,
                target_sha3=target_sha3,
                base_sha3=base_sha3,
                target_size=target_size,
                timeout_seconds=timeout_seconds,
            )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Internal worker flags
    parser.add_argument("--internal-worker-encode", action="store_true")
    parser.add_argument("--internal-worker-decode", action="store_true")
    parser.add_argument("--backend", choices=["cdc", "zstd", "full"])
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--reconstructed", type=Path)
    parser.add_argument("--target-size", type=int, default=0)
    parser.add_argument("--base-sha3", default="")
    parser.add_argument("--target-sha3", default="")

    # Benchmark CLI flags
    parser.add_argument("--base", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--timeout", type=float, default=120.0)

    args = parser.parse_args()

    if args.internal_worker_encode:
        if not args.backend or not args.base or not args.target or not args.artifact:
            parser.error("Worker encode requires --backend, --base, --target, --artifact")
        run_worker_encode(args.backend, args.base, args.target, args.artifact)
        return 0

    if args.internal_worker_decode:
        if not args.backend or not args.base or not args.artifact or not args.reconstructed:
            parser.error("Worker decode requires --backend, --base, --artifact, --reconstructed")
        run_worker_decode(
            args.backend,
            args.base,
            args.artifact,
            args.reconstructed,
            args.target_size,
            args.base_sha3,
            args.target_sha3,
        )
        return 0

    if not args.base or not args.target or not args.out:
        parser.error("Benchmark requires --base, --target, --out")

    report = generate_benchmark_report(
        base=args.base,
        target=args.target,
        out=args.out,
        python_exe=args.python,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
