import os
import sys
import subprocess
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BAT_SCRIPT = PROJECT_ROOT / "scripts" / "start_eclipse.bat"


@pytest.mark.skipif(sys.platform != "win32", reason="start_eclipse.bat is only runnable on Windows")
def test_start_eclipse_bat_dry_run_resolves_repo_root_from_any_cwd(tmp_path):
    # Create a dummy python executable/file so exist checks pass
    dummy_venv = tmp_path / "dummy_venv"
    dummy_python_dir = dummy_venv / "Scripts"
    dummy_python_dir.mkdir(parents=True)
    dummy_python = dummy_python_dir / "python.exe"
    dummy_python.touch()

    env = {
        **os.environ,
        "ECLIPSE_START_DRY_RUN": "1",
        "ECLIPSE_PYTHON": str(dummy_python),
    }

    result = subprocess.run(
        [str(BAT_SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"PYTHONPATH={PROJECT_ROOT}\\src" in result.stdout
    assert "wake-efficient" in result.stdout
    assert "--builtin-wakeword hey_jarvis" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="start_eclipse.bat is only runnable on Windows")
def test_start_eclipse_bat_missing_configured_python_exits_with_setup_message(tmp_path):
    env = {
        **os.environ,
        "ECLIPSE_START_DRY_RUN": "1",
        "ECLIPSE_PYTHON": str(tmp_path / "missing-python.exe"),
    }

    result = subprocess.run(
        [str(BAT_SCRIPT)],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Configured Python environment is missing" in result.stderr
    assert "ECLIPSE_PYTHON" in result.stderr
