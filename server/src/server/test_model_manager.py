"""ModelManager 单元测试。"""

import json
import sys
from types import ModuleType
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


class TestFuzzyMatch:
    def _make_named_configs(self) -> list[ModelConfig]:
        return [
            ModelConfig(name="Gemini Flash", provider="gemini", model_id="gemini-2.5-flash"),
            ModelConfig(name="Gemini Pro", provider="gemini", model_id="gemini-2.5-pro"),
            ModelConfig(name="DeepSeek", provider="openai_compatible", model_id="deepseek-chat"),
            ModelConfig(name="通义千问", provider="openai_compatible", model_id="qwen-plus"),
        ]

    def test_exact_match_case_insensitive(self):
        mgr = ModelManager(models=self._make_named_configs())
        assert mgr._fuzzy_match("gemini flash") == "Gemini Flash"
        assert mgr._fuzzy_match("DEEPSEEK") == "DeepSeek"

    def test_partial_match_query_in_name(self):
        mgr = ModelManager(models=self._make_named_configs())
        assert mgr._fuzzy_match("flash") == "Gemini Flash"
        assert mgr._fuzzy_match("pro") == "Gemini Pro"
        assert mgr._fuzzy_match("千问") == "通义千问"

    def test_partial_match_name_in_query(self):
        mgr = ModelManager(models=self._make_named_configs())
        assert mgr._fuzzy_match("用deepseek吧") == "DeepSeek"

    def test_no_match(self):
        mgr = ModelManager(models=self._make_named_configs())
        assert mgr._fuzzy_match("gpt4") is None

    def test_switch_with_fuzzy(self):
        mgr = ModelManager(models=self._make_named_configs())
        with patch.object(mgr, "_create_model", return_value=MagicMock()):
            result = mgr.switch_model("deepseek")
        assert "已切换到 DeepSeek" in result

    def test_switch_with_chinese_fuzzy(self):
        mgr = ModelManager(models=self._make_named_configs())
        with patch.object(mgr, "_create_model", return_value=MagicMock()):
            result = mgr.switch_model("千问")
        assert "已切换到 通义千问" in result

    def test_empty_models(self):
        mgr = ModelManager(models=[])
        assert mgr.current_model_name == ""
        assert mgr.available_models == []


class TestLoadModelsConfig:
    def test_load_grouped_config(self, tmp_path):
        config = {
            "default_model": "gemini-flash",
            "providers": {
                "gemini": {
                    "api_key": "shared-key",
                    "proxy": "http://proxy:8080",
                    "models": [
                        {"name": "gemini-flash", "model_id": "gemini-2.5-flash"},
                        {"name": "gemini-pro", "model_id": "gemini-2.5-pro"},
                    ]
                },
                "openai_compatible": {
                    "models": [
                        {"name": "deepseek", "model_id": "deepseek-chat", "api_key": "ds-key", "base_url": "https://api.deepseek.com"},
                    ]
                }
            }
        }
        path = tmp_path / "models.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        models, default = load_models_config(str(path))
        assert len(models) == 3
        assert default == "gemini-flash"
        # gemini models inherit shared api_key and proxy
        flash = next(m for m in models if m.name == "gemini-flash")
        assert flash.api_key == "shared-key"
        assert flash.proxy == "http://proxy:8080"
        # deepseek has its own api_key, no proxy
        ds = next(m for m in models if m.name == "deepseek")
        assert ds.api_key == "ds-key"
        assert ds.proxy == ""

    def test_model_overrides_provider(self, tmp_path):
        config = {
            "providers": {
                "gemini": {
                    "api_key": "shared-key",
                    "proxy": "http://proxy:8080",
                    "models": [
                        {"name": "custom", "model_id": "gemini-2.5-flash", "api_key": "override-key", "proxy": ""},
                    ]
                }
            }
        }
        path = tmp_path / "models.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        models, _ = load_models_config(str(path))
        assert models[0].api_key == "override-key"
        assert models[0].proxy == ""

    def test_load_flat_config_backward_compat(self, tmp_path):
        config = {
            "default_model": "test",
            "models": [
                {"name": "test", "provider": "gemini", "model_id": "gemini-2.5-flash"},
            ]
        }
        path = tmp_path / "models.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        models, default = load_models_config(str(path))
        assert len(models) == 1
        assert models[0].name == "test"
        assert default == "test"

    def test_missing_file(self, tmp_path):
        models, default = load_models_config(str(tmp_path / "nonexistent.json"))
        assert models == []
        assert default == ""

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "models.json"
        path.write_text("not json", encoding="utf-8")
        models, default = load_models_config(str(path))
        assert models == []
        assert default == ""


class TestCreateGeminiModel:
    def test_proxy_passed_via_http_options_client_args(self):
        captured: dict[str, object] = {}

        class FakeGeminiModel:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        fake_module = ModuleType("strands.models.gemini")
        fake_module.GeminiModel = FakeGeminiModel

        with patch.dict(sys.modules, {"strands.models.gemini": fake_module}):
            mgr = ModelManager(models=[])
            cfg = ModelConfig(
                name="gemini-flash",
                provider="gemini",
                model_id="gemini-2.5-flash",
                api_key="k",
                proxy="http://127.0.0.1:40000",
            )
            mgr._create_gemini_model(cfg)

        assert captured["model_id"] == "gemini-2.5-flash"
        assert captured["client_args"] == {
            "api_key": "k",
            "http_options": {
                "client_args": {"proxy": "http://127.0.0.1:40000"},
                "async_client_args": {"proxy": "http://127.0.0.1:40000"},
            },
        }
