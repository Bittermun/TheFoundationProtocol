# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Verification suite for Hermetic Workshop Environment & Tooling Isolation (Requirement R1).

Enforces strict isolation boundaries:
1. pyproject.toml [project.dependencies] contains 0 test/dev packages.
2. requirements.txt contains 0 test/dev packages.
3. Developer & test tooling resides solely in requirements-dev.txt and optional-dependencies.
4. Packaging build manifest excludes test suites from production package discovery.
5. Multi-stage Docker definitions enforce isolated targets.
6. Testbed port synchronization is maintained.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

REPO_ROOT = Path(__file__).resolve().parent.parent

BANNED_DEV_TEST_TOOLS = {
    "pytest",
    "pytest-asyncio",
    "pytest-timeout",
    "hypothesis",
    "ruff",
    "mypy",
    "bandit",
    "ast-grep",
    "ast-grep-cli",
    "black",
    "flake8",
    "httpx",
    "fakeredis",
    "locust",
}


def _extract_pkg_name(req_line: str) -> str:
    """Extract canonical package name from a dependency specification string."""
    line = req_line.strip()
    if not line or line.startswith("#") or line.startswith("-"):
        return ""
    # Strip inline comments
    line = line.split("#")[0].strip()
    try:
        from packaging.requirements import Requirement
        return Requirement(line).name.lower().replace("_", "-")
    except Exception:
        # Fallback regex parser: strip bracketed extras e.g. [asyncio]
        line = re.sub(r"\[.*?\]", "", line)
        match = re.split(r"[=><!~; ]", line, maxsplit=1)
        name = match[0].strip()
        return name.lower().replace("_", "-")


class TestToolingIsolation:
    """Automated audit tests for development tooling and production package isolation."""

    def test_pyproject_dependencies_contain_zero_test_or_dev_tooling(self):
        """Verify root pyproject.toml [project.dependencies] contains zero test/dev packages."""
        pyproject_path = REPO_ROOT / "pyproject.toml"
        assert pyproject_path.exists(), f"Missing root pyproject.toml at {pyproject_path}"

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        project = data.get("project", {})
        dependencies = project.get("dependencies", [])
        assert dependencies, "pyproject.toml [project.dependencies] must not be empty"

        extracted = set()
        for dep in dependencies:
            name = _extract_pkg_name(dep)
            if name:
                extracted.add(name)

        leaked_tools = extracted.intersection(BANNED_DEV_TEST_TOOLS)
        assert not leaked_tools, (
            f"BANNED test/dev tools found leaking into pyproject.toml [project.dependencies]: {leaked_tools}"
        )

        # Expected pure production dependencies
        expected_prod = {"fastapi", "uvicorn", "python-ndn", "websockets", "cryptography", "prometheus-client", "python-multipart"}
        for exp in expected_prod:
            assert exp in extracted, f"Expected production dependency '{exp}' missing from pyproject.toml"

    def test_requirements_txt_contains_zero_test_or_dev_tooling(self):
        """Verify root requirements.txt contains ONLY pure production runtime dependencies."""
        req_path = REPO_ROOT / "requirements.txt"
        assert req_path.exists(), f"Missing root requirements.txt at {req_path}"

        lines = req_path.read_text(encoding="utf-8").splitlines()
        extracted = set()
        for line in lines:
            name = _extract_pkg_name(line)
            if name:
                extracted.add(name)

        assert extracted, "requirements.txt must contain production packages"

        leaked_tools = extracted.intersection(BANNED_DEV_TEST_TOOLS)
        assert not leaked_tools, (
            f"BANNED test/dev tools found leaking into requirements.txt: {leaked_tools}"
        )

    def test_subpackage_requirements_txt_clean(self):
        """Verify tfp-foundation-protocol/requirements.txt contains no leaked test tools."""
        sub_req = REPO_ROOT / "tfp-foundation-protocol" / "requirements.txt"
        if sub_req.exists():
            lines = sub_req.read_text(encoding="utf-8").splitlines()
            extracted = set()
            for line in lines:
                name = _extract_pkg_name(line)
                if name:
                    extracted.add(name)
            leaked = extracted.intersection(BANNED_DEV_TEST_TOOLS)
            assert not leaked, f"BANNED tools leaking in tfp-foundation-protocol/requirements.txt: {leaked}"

    def test_requirements_dev_txt_contains_required_tooling(self):
        """Verify requirements-dev.txt contains developer & test tooling."""
        dev_req = REPO_ROOT / "requirements-dev.txt"
        assert dev_req.exists(), f"Missing requirements-dev.txt at {dev_req}"

        content = dev_req.read_text(encoding="utf-8").lower()
        required_tools = [
            "pytest",
            "pytest-asyncio",
            "pytest-timeout",
            "httpx",
            "hypothesis",
            "ruff",
            "mypy",
            "bandit",
            "ast-grep-cli",
        ]
        for tool in required_tools:
            assert tool in content, f"Required dev/test tool '{tool}' missing from requirements-dev.txt"

    def test_packaging_manifest_excludes_test_suites(self, monkeypatch):
        """Check actual discovered packages, independent of configuration syntax."""
        import runpy
        from unittest.mock import patch

        monkeypatch.chdir(REPO_ROOT)
        with patch("setuptools.setup") as setup:
            runpy.run_path(str(REPO_ROOT / "setup.py"))
        packages = setup.call_args.kwargs["packages"]
        assert {"tfp_cli", "tfp_demo", "tfp_client", "tfp_core_v4", "demo"} <= set(packages)
        for package in packages:
            assert not any(part.startswith("test") or part.endswith("_test") for part in package.split(".")), package
            assert not package.startswith(("docs", "scripts", "tfp_testbed")), package
        assert setup.call_args.kwargs["package_dir"]["tfp_cli"] == "./tfp_cli"

    def test_dockerfile_multi_stage_targets(self):
        """Verify Dockerfile and Dockerfile.workshop define clean production and workshop-dev targets."""
        for filename in ["Dockerfile", "Dockerfile.workshop"]:
            dockerfile_path = REPO_ROOT / filename
            assert dockerfile_path.exists(), f"Missing {filename}"
            content = dockerfile_path.read_text(encoding="utf-8")

            assert "AS production" in content or "as production" in content, (
                f"{filename} must define 'production' target stage"
            )
            assert "AS workshop-dev" in content or "as workshop-dev" in content, (
                f"{filename} must define 'workshop-dev' target stage"
            )
            assert "requirements-dev.txt" not in content.split("AS production")[1].split("AS workshop-dev")[0], (
                f"{filename} production stage must NOT reference requirements-dev.txt"
            )

    def test_docker_compose_workshop_wiring(self):
        """Verify docker-compose.workshop.yml defines tfp-workshop connecting to tfp-network."""
        compose_path = REPO_ROOT / "docker-compose.workshop.yml"
        assert compose_path.exists(), "Missing docker-compose.workshop.yml"
        content = compose_path.read_text(encoding="utf-8")

        assert "tfp-workshop:" in content, "docker-compose.workshop.yml must define tfp-workshop service"
        assert "target: workshop-dev" in content, "tfp-workshop service must target workshop-dev"
        assert "tfp-network" in content, "tfp-workshop service must connect to tfp-network"

    def test_devcontainer_configuration(self):
        """Verify .devcontainer/devcontainer.json references testbed and workshop compose files."""
        devcontainer_path = REPO_ROOT / ".devcontainer" / "devcontainer.json"
        assert devcontainer_path.exists(), "Missing .devcontainer/devcontainer.json"
        content = devcontainer_path.read_text(encoding="utf-8")

        assert "docker-compose.testbed.yml" in content, "devcontainer must reference docker-compose.testbed.yml"
        assert "docker-compose.workshop.yml" in content, "devcontainer must reference docker-compose.workshop.yml"
        assert "tfp-workshop" in content, "devcontainer must use tfp-workshop service"

    def test_port_synchronization(self):
        """Verify tests/generate_testbed.py base_port = 9000 matches operate_testbed.py (9001-9010)."""
        gen_file = REPO_ROOT / "tests" / "generate_testbed.py"
        assert gen_file.exists(), "Missing tests/generate_testbed.py"
        content = gen_file.read_text(encoding="utf-8")

        assert "base_port = 8000" not in content, (
            "tests/generate_testbed.py still has stale base_port = 8000! Must be 9000."
        )
        assert "base_port = 9000" in content, (
            "tests/generate_testbed.py must specify base_port = 9000."
        )

        compose_file = REPO_ROOT / "docker-compose.testbed.yml"
        compose_content = compose_file.read_text(encoding="utf-8")
        assert "9001:8000" in compose_content, "docker-compose.testbed.yml must map node 1 to port 9001"
        assert "9010:8000" in compose_content, "docker-compose.testbed.yml must map node 10 to port 9010"

    def test_extract_pkg_name_resilient_to_extras_and_adversarial_syntax(self):
        """Verify PEP 508 bracketed extras syntax cannot bypass banned package detection."""
        adversarial_cases = [
            ("pytest[asyncio]>=8.3.0", "pytest"),
            ("hypothesis[datetime]>=6.100.0", "hypothesis"),
            ("httpx[http2]>=0.28.0", "httpx"),
            ("fakeredis[lua]>=2.2.0", "fakeredis"),
            ("pytest-timeout[extra]==2.3.0", "pytest-timeout"),
            ("ruff[all]>0.4.0", "ruff"),
            ("mypy[reports]<=1.10.0", "mypy"),
        ]
        for spec, expected_canonical in adversarial_cases:
            extracted = _extract_pkg_name(spec)
            assert extracted == expected_canonical, f"Failed to normalize {spec} -> {expected_canonical}, got {extracted}"
            assert extracted in BANNED_DEV_TEST_TOOLS, f"Extracted {extracted} was not caught in BANNED_DEV_TEST_TOOLS!"

    def test_wheel_archive_contains_zero_test_files_and_zero_pytest_imports(self):
        """Verify built wheel archive contains ZERO test files, zero pytest imports, and valid CLI entry points."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Clean build directory if exists to prevent caching contamination
            bdir = REPO_ROOT / "build"
            if bdir.exists():
                shutil.rmtree(bdir, ignore_errors=True)

            cmd = [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", tmpdir]
            res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
            assert res.returncode == 0, f"Wheel build failed: {res.stderr}\n{res.stdout}"

            whl_files = list(Path(tmpdir).glob("*.whl"))
            assert whl_files, "No wheel file produced by build"
            whl_path = whl_files[0]

            with zipfile.ZipFile(whl_path, "r") as zf:
                names = zf.namelist()

                # Verify CLI main entry point exists
                assert "tfp_cli/main.py" in names, "Wheel missing console script target tfp_cli/main.py!"

                # Verify entry_points.txt specifies tfp = tfp_core_v4.cli:main
                entry_points = [n for n in names if n.endswith("entry_points.txt")]
                assert entry_points, "Wheel missing entry_points.txt"
                ep_content = zf.read(entry_points[0]).decode("utf-8")
                assert "tfp = tfp_core_v4.cli:main" in ep_content, "entry_points.txt missing tfp = tfp_core_v4.cli:main"

                # Check for leaked test files and testbeds
                leaked_test_files = [
                    n for n in names
                    if not n.endswith("RECORD")
                    and ".dist-info" not in n
                    and any(
                        part.startswith("test")
                        or part.endswith("test")
                        or "testbed" in part
                        or "_test" in part
                        for part in Path(n).parts
                    )
                ]
                assert not leaked_test_files, f"Leaked test files found in production wheel: {leaked_test_files}"

                # Check that ZERO files import pytest
                pytest_importers = []
                for name in names:
                    if name.endswith(".py"):
                        content = zf.read(name).decode("utf-8", errors="ignore")
                        for line in content.splitlines():
                            line_s = line.strip()
                            if line_s.startswith("import pytest") or line_s.startswith("from pytest"):
                                pytest_importers.append((name, line_s))
                assert not pytest_importers, f"Files in production wheel import pytest: {pytest_importers}"

    def test_isolated_runtime_imports_without_httpx(self):
        """Verify production code modules import cleanly in an environment where httpx is not present."""
        code = (
            "import sys\n"
            "sys.modules['httpx'] = None\n"
            "import tfp_ui.core_bridge.protocol_adapter\n"
            "import tfp_cli.main\n"
            "assert callable(tfp_cli.main.main)\n"
            "print('ISOLATION_OK')\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, f"Isolated runtime import failed: {res.stderr}\n{res.stdout}"
        assert "ISOLATION_OK" in res.stdout

    def test_dockerignore_excludes_test_suites_and_uses_forward_slashes(self):
        """Verify .dockerignore explicitly excludes tests and testbeds using forward slashes."""
        dockerignore_path = REPO_ROOT / ".dockerignore"
        assert dockerignore_path.exists(), "Missing .dockerignore"
        content = dockerignore_path.read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]

        # Enforce forward slashes on non-comment lines
        for line in lines:
            assert "\\" not in line, f"Pattern in .dockerignore contains Windows backslash: {line}"

        # Enforce explicit test exclusions
        assert any(line == "tests/" or line == "tests" for line in lines), ".dockerignore must explicitly exclude tests/"
        assert any("**/tests/**" in line for line in lines), ".dockerignore must exclude **/tests/**"
        assert any("**/test/**" in line for line in lines), ".dockerignore must exclude **/test/**"
        assert any("test_*.py" in line for line in lines), ".dockerignore must exclude test_*.py"
