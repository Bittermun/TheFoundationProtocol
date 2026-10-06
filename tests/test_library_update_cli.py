from pathlib import Path
import subprocess
import sys


def test_optional_commands_available_without_importing_reader_tools():
    result = subprocess.run([sys.executable, '-m', 'tfp_core_v4.cli', '--help'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert 'library-prepare' in result.stdout
    assert 'library-recover' in result.stdout
    assert 'audio-encode' in result.stdout


def test_invalid_update_inputs_exit_nonzero(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'tfp_core_v4.cli', 'library-prepare', str(tmp_path / 'missing'), str(tmp_path / 'missing2'), '--library-id', 'school', '--revision', '1', '--signing-key', str(tmp_path / 'key'), '--out', str(tmp_path / 'package')], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert not (tmp_path / 'package').exists()


def test_cli_explicit_delta_backend_zstd_and_auto(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    keyfile = tmp_path / 'pub.key'
    keyfile.write_bytes(key.private_bytes_raw())

    base = Path('tests/fixtures/library_update/base.zim')
    target = Path('tests/fixtures/library_update/target.zim')

    # Explicit zstd backend via CLI
    out_zstd = tmp_path / 'pkg_zstd'
    res_zstd = subprocess.run(
        [sys.executable, '-m', 'tfp_core_v4.cli', 'library-prepare', str(base), str(target),
         '--library-id', 'testlib', '--revision', '1', '--signing-key', str(keyfile),
         '--out', str(out_zstd), '--delta-backend', 'zstd'],
        capture_output=True, text=True, timeout=15
    )
    assert res_zstd.returncode == 0
    assert (out_zstd / 'artifact.zst').exists()
    assert (out_zstd / 'update.json').exists()

    # Auto backend via CLI
    out_auto = tmp_path / 'pkg_auto'
    res_auto = subprocess.run(
        [sys.executable, '-m', 'tfp_core_v4.cli', 'library-prepare', str(base), str(target),
         '--library-id', 'testlib', '--revision', '2', '--signing-key', str(keyfile),
         '--out', str(out_auto), '--delta-backend', 'auto'],
        capture_output=True, text=True, timeout=15
    )
    assert res_auto.returncode == 0
    assert (out_auto / 'artifact.zst').exists()

    # Invalid backend exits nonzero and leaves no package
    out_bad = tmp_path / 'pkg_bad'
    res_bad = subprocess.run(
        [sys.executable, '-m', 'tfp_core_v4.cli', 'library-prepare', str(base), str(target),
         '--library-id', 'testlib', '--revision', '3', '--signing-key', str(keyfile),
         '--out', str(out_bad), '--delta-backend', 'bad_backend'],
        capture_output=True, text=True, timeout=10
    )
    assert res_bad.returncode != 0
    assert not out_bad.exists()

