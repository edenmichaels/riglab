"""Shared test setup: import RigLab from the repo and keep its settings in a temp folder."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    # RigLab writes settings/logs to %APPDATA%\RigLab - point that at a throwaway folder for the tests
    import tempfile
    tmp = tempfile.mkdtemp(prefix="riglab-tests-")
    os.environ["APPDATA"] = tmp
    os.environ["RIGLAB_VENDOR"] = os.path.join(tmp, "vendor")
