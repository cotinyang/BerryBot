"""model_tools 单元测试。"""

import types
from unittest.mock import MagicMock, patch

import pytest

from server.model_manager import ModelConfig, ModelManager
from server.model_tools import _list_models, _switch_model, create_model_tools


def _make_manager() -> ModelManager:
    configs = [
        ModelConfig(name="gemini-flash", provider="gemini", model_id="gemini-2.5-flash"),
        ModelConfig(name="deepseek", provider="openai_compatible", model_id="deepseek-chat"),
    ]
    return ModelManager(models=configs, default_model="gemini-flash")


class TestListModels:
    def test_lists_all_models(self):
        mgr = _make_manager()
        result = _list_models(mgr)
        assert "gemini-flash" in result
        assert "deepseek" in result
        assert "(当前)" in result

    def test_marks_current_model(self):
        mgr = _make_manager()
        result = _list_models(mgr)
        assert "gemini-flash (当前)" in result


class TestSwitchModel:
    def test_switch_success(self):
        mgr = _make_manager()
        with patch.object(mgr, "_create_model", return_value=MagicMock()):
            result = _switch_model("deepseek", mgr)
        assert "已切换到 deepseek" in result

    def test_switch_not_found(self):
        mgr = _make_manager()
        result = _switch_model("nonexistent", mgr)
        assert "不存在" in result


class TestCreateModelTools:
    def test_returns_two_tools(self):
        mgr = _make_manager()
        mock_strands = types.ModuleType("strands")
        mock_strands.tool = lambda fn: fn
        with patch.dict("sys.modules", {"strands": mock_strands}):
            tools = create_model_tools(mgr)
        assert len(tools) == 2

    def test_tools_are_callable(self):
        mgr = _make_manager()
        mock_strands = types.ModuleType("strands")
        mock_strands.tool = lambda fn: fn
        with patch.dict("sys.modules", {"strands": mock_strands}):
            tools = create_model_tools(mgr)
        for t in tools:
            assert callable(t)

    @patch.dict("sys.modules", {"strands": None})
    def test_import_error(self):
        mgr = _make_manager()
        with pytest.raises(ImportError, match="strands-agents 未安装"):
            create_model_tools(mgr)
