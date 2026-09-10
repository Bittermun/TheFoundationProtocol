#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
The Foundation Protocol - Workshop & Testbed CLI Runner.

Provides cross-platform commands to manage the hermetic workshop environment:
  python scripts/workshop.py --start   # Launches testbed + workshop containers
  python scripts/workshop.py --test    # Runs pytest test suite
  python scripts/workshop.py --audit   # Runs tooling isolation & audit verification
  python scripts/workshop.py --stop    # Tears down testbed & workshop containers
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = [
    REPO_ROOT / "docker-compose.testbed.yml",
    REPO_ROOT / "docker-compose.workshop.yml",
]


def get_docker_compose_cmd() -> list[str]:
    """Detect docker compose v2 or docker-compose v1."""
    if shutil.which("docker"):
        # Check if 'docker compose' works
        res = subprocess.run(
            ["docker", "compose", "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if res.returncode == 0:
            return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return []


def run_cmd(cmd: list[str], cwd: Path | None = None) -> int:
    """Run a subprocess command and stream output."""
    print(f"[workshop] Executing: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT))
        return proc.returncode
    except FileNotFoundError as exc:
        print(f"[workshop] Error: Command not found: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[workshop] Execution error: {exc}", file=sys.stderr)
        return 1


def cmd_start(args: argparse.Namespace) -> int:
    """Launch testbed + workshop containers."""
    compose_cmd = get_docker_compose_cmd()
    if not compose_cmd:
        print("[workshop] Warning: Docker Compose not detected in PATH.", file=sys.stderr)
        print("[workshop] Ensure Docker Desktop / engine is installed and running.", file=sys.stderr)
        return 1

    cmd = list(compose_cmd)
    for cf in COMPOSE_FILES:
        cmd.extend(["-f", str(cf)])
    cmd.extend(["up", "-d"])
    if args.build:
        cmd.append("--build")

    print("[workshop] Starting testbed and workshop containers...")
    return run_cmd(cmd)


def cmd_stop(args: argparse.Namespace) -> int:
    """Tear down testbed and workshop containers."""
    compose_cmd = get_docker_compose_cmd()
    if not compose_cmd:
        print("[workshop] Warning: Docker Compose not detected in PATH.", file=sys.stderr)
        return 1

    cmd = list(compose_cmd)
    for cf in COMPOSE_FILES:
        cmd.extend(["-f", str(cf)])
    cmd.extend(["down"])
    if getattr(args, "volumes", False):
        cmd.append("-v")

    print("[workshop] Stopping testbed and workshop containers...")
    return run_cmd(cmd)


def cmd_test(args: argparse.Namespace) -> int:
    """Run test suite."""
    pytest_args = args.pytest_args or []
    if args.in_container:
        compose_cmd = get_docker_compose_cmd()
        if not compose_cmd:
            print("[workshop] Docker not detected; falling back to native test execution.")
        else:
            cmd = list(compose_cmd)
            for cf in COMPOSE_FILES:
                cmd.extend(["-f", str(cf)])
            cmd.extend(["exec", "-T", "tfp-workshop", "python", "-m", "pytest"])
            cmd.extend(pytest_args)
            return run_cmd(cmd)

    # Native test execution
    python_bin = sys.executable
    cmd = [python_bin, "-m", "pytest"]
    if not pytest_args:
        cmd.extend(["tests/test_tooling_isolation.py", "-v"])
    else:
        cmd.extend(pytest_args)

    return run_cmd(cmd)


def cmd_audit(args: argparse.Namespace) -> int:
    """Run tooling isolation, packaging, and configuration audits."""
    print("=" * 60)
    print("[workshop] Running Hermetic Tooling Isolation & Health Audit")
    print("=" * 60)

    # 1. Run isolation verification test
    python_bin = sys.executable
    test_file = REPO_ROOT / "tests" / "test_tooling_isolation.py"
    if not test_file.exists():
        print(f"[workshop] FAIL: {test_file} does not exist!", file=sys.stderr)
        return 1

    cmd = [python_bin, "-m", "pytest", str(test_file), "-v"]
    ret = run_cmd(cmd)
    if ret != 0:
        print("[workshop] FAIL: Tooling isolation tests failed!", file=sys.stderr)
        return ret

    # 2. Verify server module collection without syntax/type errors
    print("[workshop] Verifying FastAPI server route compilation...")
    verify_cmd = [
        python_bin,
        "-c",
        "import sys; sys.path.insert(0, 'tfp-foundation-protocol'); from tfp_demo import server; assert server.app is not None; print('FastAPI server loaded cleanly: OK')",
    ]
    ret = run_cmd(verify_cmd)
    if ret != 0:
        print("[workshop] FAIL: FastAPI server failed to import cleanly!", file=sys.stderr)
        return ret

    # 3. Verify port synchronization between generate_testbed.py and operate_testbed.py
    print("[workshop] Verifying port synchronization...")
    gen_file = REPO_ROOT / "tests" / "generate_testbed.py"
    if gen_file.exists():
        content = gen_file.read_text(encoding="utf-8")
        if "base_port = 8000" in content:
            print("[workshop] FAIL: tests/generate_testbed.py still uses base_port = 8000!", file=sys.stderr)
            return 1
        if "base_port = 9000" not in content:
            print("[workshop] FAIL: tests/generate_testbed.py does not define base_port = 9000!", file=sys.stderr)
            return 1
        print("[workshop] Port synchronization (base_port = 9000): OK")

    # 4. AST Structural Guardrail Linter
    print("=" * 60)
    print("[workshop] Running AST Structural Guardrail Linter...")
    print("=" * 60)
    ast_linter_script = REPO_ROOT / "scripts" / "lint_ast_rules.py"
    if not ast_linter_script.exists():
        print(f"[workshop] FAIL: {ast_linter_script} does not exist!", file=sys.stderr)
        return 1
    ret = run_cmd([python_bin, str(ast_linter_script)])
    if ret != 0:
        print("[workshop] FAIL: AST guardrail linting failed!", file=sys.stderr)
        return ret

    # 5. Autonomous Adversarial Fault Injection Runner
    print("=" * 60)
    print("[workshop] Running Autonomous Adversarial Fault Injection Audit...")
    print("=" * 60)
    adversarial_script = REPO_ROOT / "scripts" / "run_adversarial_audit.py"
    if not adversarial_script.exists():
        print(f"[workshop] FAIL: {adversarial_script} does not exist!", file=sys.stderr)
        return 1
    ret = run_cmd([python_bin, str(adversarial_script), "--quick"])
    if ret != 0:
        print("[workshop] FAIL: Adversarial fault injection audit failed!", file=sys.stderr)
        return ret

    print("=" * 60)
    print("[workshop] Audit SUCCESS: All hermetic isolation, AST rules, and adversarial gates PASSED.")
    print("=" * 60)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="The Foundation Protocol - Hermetic Workshop & Testbed CLI"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--start",
        action="store_true",
        help="Launch testbed and workshop containers in background",
    )
    group.add_argument(
        "--stop",
        action="store_true",
        help="Stop and tear down testbed and workshop containers",
    )
    group.add_argument(
        "--test",
        action="store_true",
        help="Execute pytest test suite",
    )
    group.add_argument(
        "--audit",
        action="store_true",
        help="Run tooling isolation & audit verification",
    )

    parser.add_argument(
        "--build",
        action="store_true",
        help="Build container images before starting",
    )
    parser.add_argument(
        "-v",
        "--volumes",
        action="store_true",
        help="Remove volumes on stop",
    )
    parser.add_argument(
        "--in-container",
        action="store_true",
        help="Run tests inside tfp-workshop container",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments passed directly to pytest when using --test",
    )

    args = parser.parse_args()

    if args.start:
        sys.exit(cmd_start(args))
    elif args.stop:
        sys.exit(cmd_stop(args))
    elif args.test:
        sys.exit(cmd_test(args))
    elif args.audit:
        sys.exit(cmd_audit(args))


if __name__ == "__main__":
    main()
