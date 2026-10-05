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
