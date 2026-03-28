"""memory_tools 单元测试。"""

from unittest.mock import patch

import pytest

from server.memory_tools import _read_memory, _update_memory, create_memory_tools


class TestReadMemory:
    """_read_memory 纯函数测试。"""

    def test_read_existing_file(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("# 记忆\n用户喜欢猫", encoding="utf-8")
        result = _read_memory(str(mem_file))
        assert result == "# 记忆\n用户喜欢猫"

    def test_read_missing_file_returns_empty(self, tmp_path):
        result = _read_memory(str(tmp_path / "nonexistent.md"))
        assert result == ""

    def test_read_error_returns_empty(self, tmp_path):
        bad_path = tmp_path / "MEMORY.md"
        bad_path.mkdir()  # 目录而非文件，触发 OSError
        result = _read_memory(str(bad_path))
        assert result == ""

    def test_read_empty_file(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("", encoding="utf-8")
        result = _read_memory(str(mem_file))
        assert result == ""

    def test_read_utf8_content(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("用户偏好：中文回复 🐱", encoding="utf-8")
        result = _read_memory(str(mem_file))
        assert "中文回复" in result
        assert "🐱" in result


class TestUpdateMemory:
    """_update_memory 纯函数测试。"""

    def test_write_new_file(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        result = _update_memory("# 记忆\n新内容", str(mem_file))
        assert "记忆已更新" in result
        assert mem_file.read_text(encoding="utf-8") == "# 记忆\n新内容"

    def test_overwrite_existing_file(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("旧内容", encoding="utf-8")
        result = _update_memory("新内容", str(mem_file))
        assert "记忆已更新" in result
        assert mem_file.read_text(encoding="utf-8") == "新内容"

    def test_write_error_returns_failure_message(self):
        result = _update_memory("内容", "/nonexistent_dir/MEMORY.md")
        assert "记忆更新失败" in result

    def test_write_empty_content(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        result = _update_memory("", str(mem_file))
        assert "记忆已更新" in result
        assert mem_file.read_text(encoding="utf-8") == ""


class TestCreateMemoryTools:
    """create_memory_tools 工厂函数测试。"""

    @patch.dict("sys.modules", {"strands": None})
    def test_import_error_when_strands_not_installed(self):
        with pytest.raises(ImportError, match="strands-agents 未安装"):
            create_memory_tools()

    def test_returns_two_tools(self):
        """使用 mock strands 验证工厂函数返回两个工具。"""
        # 创建一个 mock @tool 装饰器（直接返回原函数）
        import types

        mock_strands = types.ModuleType("strands")
        mock_strands.tool = lambda fn: fn  # noqa: E731

        with patch.dict("sys.modules", {"strands": mock_strands}):
            tools = create_memory_tools()

        assert len(tools) == 2

    def test_tools_are_callable(self):
        import types

        mock_strands = types.ModuleType("strands")
        mock_strands.tool = lambda fn: fn  # noqa: E731

        with patch.dict("sys.modules", {"strands": mock_strands}):
            tools = create_memory_tools()

        for t in tools:
            assert callable(t)

    def test_tools_use_custom_path(self, tmp_path):
        mem_file = tmp_path / "custom_memory.md"
        mem_file.write_text("自定义记忆", encoding="utf-8")

        import types

        mock_strands = types.ModuleType("strands")
        mock_strands.tool = lambda fn: fn  # noqa: E731

        with patch.dict("sys.modules", {"strands": mock_strands}):
            tools = create_memory_tools(memory_path=str(mem_file))

        read_tool, update_tool = tools
        assert read_tool() == "自定义记忆"

        result = update_tool("更新后的记忆")
        assert "记忆已更新" in result
        assert mem_file.read_text(encoding="utf-8") == "更新后的记忆"
