"""Pytest fixtures for the iHIM API.

STT autostart is disabled BEFORE the app import so the test app never
registers a global hotkey listener or touches the GPU.
"""

import os
import sys
from pathlib import Path

os.environ["IHIM_STT_AUTOSTART"] = "0"

IHIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IHIM_DIR))

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture(scope="session")
def client():
    # No context manager: lifespan (engine start, PID file) intentionally
    # not exercised — route behavior is the unit under test here.
    return TestClient(app, raise_server_exceptions=False)
