import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voxkeypaste import config  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    """A fresh Config stored in a temporary folder (never the user's real settings)."""
    return config.init(str(tmp_path / 'config.yaml'))
