"""session_tools 单元测试。"""

import types
from unittest.mock import patch

import pytest

from server.session_tools import (
    COMMAND_PREFIX,
    _end_session,
    create_session_tools,
    is_command,
    parse_command,
)


class TestEndSession:
    def test_returns_command_prefix(self):
        result = _end_session()
        assert result.startswith(COMMAND_PREFIX)
        assert "end_session" in result


class TestIsCommand:
    def test_command_text(self):
        assert is_command(f"{COMMAND_PREFIX}end_session") is True

    def test_normal_text(self):
        assert is_command("你好，有什么可以帮你的？") is False

    def test_empty_text(self):
        assert is_command("") is False

    def test_whitespace_prefix(self):
        assert is_command(f"  {COMMAND_PREFIX}end_session") is True


class TestParseCommand:
    def test_parse_end_session(self):
        assert parse_command(f"{COMMAND_PREFIX}end_session") == "end_session"

    def test_parse_with_whitespace(self):
        assert parse_command(f"  {COMMAND_PREFIX}end_session  ") == "end_session"


class TestCreateSessionTools:
    def test_returns_one_tool(self):
        mock_strands = types.ModuleType("strands")
        mock_strands.tool = lambda fn: fn
        with patch.dict("sys.modules", {"strands": mock_strands}):
            tools = create_session_tools()
        assert len(tools) == 1
        assert callable(tools[0])

    @patch.dict("sys.modules", {"strands": None})
    def test_import_error(self):
        with pytest.raises(ImportError, match="strands-agents 未安装"):
            create_session_tools()
