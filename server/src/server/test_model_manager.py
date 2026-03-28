"""ModelManager 单元测试。"""

import json
from unittest.mock import MagicMock, patch

import pytest

from server.model_manager import ModelConfig, ModelManager, load_models_config


def _make_configs() -> list[ModelConfig]:
    return [
        ModelConfig(name="gemini-flash", provider="gemini", model_id="gemini-2.5-flash", api_key="key1"),
        ModelConfig(name="deepseek", provider="openai_compatible", model_id="deepseek-chat", api_key="key2", base_url="https://api.deepseek.com"),
    ]


class TestModelManager:
    def test_default_model_is_first(self):
        mgr = ModelManager(models=_make_configs())
        assert mgr.current_model_name == "gemini-flash"

    def test_custom_default_model(self):
        mgr = ModelManager(models=_make_configs(), default_model="deepseek")
        assert mgr.current_model_name == "deepseek"

    def test_available_models(self):
        mgr = ModelManager(models=_make_configs())
        assert set(mgr.available_models) == {"gemini-flash", "deepseek"}

    def test_switch_model_success(self):
        mgr = ModelManager(models=_make_configs())
        with patch.object(mgr, "_create_model", return_value=MagicMock()):
            result = mgr.switch_model("deepseek")
        assert "已切换到 deepseek" in result
        assert mgr.current_model_name == "deepseek"

    def test_switch_model_not_found(self):
        mgr = ModelManager(models=_make_configs())
        result = mgr.switch_model("nonexistent")
        assert "不存在" in result
        assert mgr.current_model_name == "gemini-flash"

    def test_switch_to_same_model(self):
        mgr = ModelManager(models=_make_configs())
        with patch.object(mgr, "_create_model", return_value=MagicMock()):
            mgr.get_model()  # init current
            result = mgr.switch_model("gemini-flash")
        assert "已在使用" in result

    def test_empty_models(self):
        mgr = ModelManager(models=[])
        assert mgr.current_model_name == ""
        assert mgr.available_models == []


class TestLoadModelsConfig:
    def test_load_valid_config(self, tmp_path):
        config = {
            "models": [
                {"name": "test", "provider": "gemini", "model_id": "gemini-2.5-flash"},
            ]
        }
        path = tmp_path / "models.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        models = load_models_config(str(path))
        assert len(models) == 1
        assert models[0].name == "test"

    def test_missing_file(self, tmp_path):
        models = load_models_config(str(tmp_path / "nonexistent.json"))
        assert models == []

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "models.json"
        path.write_text("not json", encoding="utf-8")
        models = load_models_config(str(path))
        assert models == []
