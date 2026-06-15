import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "start_eclipse.sh"


def test_start_eclipse_dry_run_resolves_repo_root_from_any_cwd(tmp_path):
    env = {
        **os.environ,
        "ECLIPSE_START_DRY_RUN": "1",
        "ECLIPSE_PYTHON": str(PROJECT_ROOT / ".venv-wake" / "bin" / "python"),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert f"PYTHONPATH={PROJECT_ROOT / 'src'}" in result.stdout
    assert "wake-efficient" in result.stdout
    assert "--builtin-wakeword hey_jarvis" in result.stdout


def test_start_eclipse_missing_configured_python_exits_with_setup_message(tmp_path):
    env = {
        **os.environ,
        "ECLIPSE_START_DRY_RUN": "1",
        "ECLIPSE_PYTHON": str(tmp_path / "missing-python"),
    }

    result = subprocess.run(
        [str(SCRIPT)],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Configured Python environment is missing" in result.stderr
    assert "ECLIPSE_PYTHON" in result.stderr
