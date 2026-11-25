import os
import subprocess
import sys

from app.config import ROOT


def test_dashboard_imports_backend_when_script_folder_is_first():
    script = ROOT / "dashboard" / "app.py"
    code = """
import runpy
import sys
from pathlib import Path

script = Path(sys.argv[1])
sys.path.insert(0, str(script.parent))
runpy.run_path(str(script), run_name="__main__")
"""
    env = {**os.environ, "MOMENTRIX_DASHBOARD_API_URL": "http://127.0.0.1:1"}
    result = subprocess.run(
        [sys.executable, "-c", code, str(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
