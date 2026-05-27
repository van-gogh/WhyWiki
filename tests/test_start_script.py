import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START_SCRIPT = ROOT / "start.sh"


def test_start_script_is_shell_checked_and_executable():
    result = subprocess.run(
        ["bash", "-n", str(START_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert os.access(START_SCRIPT, os.X_OK)


def test_start_script_bootstraps_local_runtime():
    script = START_SCRIPT.read_text(encoding="utf-8")

    assert "python3.12 python3.11 python3.10 python3 python" in script
    assert "python -m venv" in script
    assert "ensurepip" in script
    assert "-m pip install -e ." in script
    assert "WHYWIKI_DATA_DIR" in script
    assert "restart_existing_whywiki" in script
    assert "PortInUseError" in script
    assert "choose_port" in script
    assert "find_listening_process" in script
    assert "stop_process" in script
    assert "could not identify the process using" in script
    assert "whywiki.cli init-db" in script
    assert "whywiki.cli serve --host 127.0.0.1 --port 8765" in script
