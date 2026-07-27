import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def file_tool(tmp_dir):
    from app.tools.file_tool import FileTool
    return FileTool(base_dir=tmp_dir)
