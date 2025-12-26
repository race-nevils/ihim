"""
Pytest configuration and shared fixtures for iHIM tests.
"""
import pytest
import sys
from pathlib import Path

# Ensure the iHIM package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))
