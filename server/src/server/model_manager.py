"""多模型管理器：支持预配置多个 LLM 模型并在运行时切换。

支持的 provider:
- gemini: Google Gemini (strands.models.gemini.GeminiModel)
- openai_compatible: OpenAI 兼容接口 (strands.models.openai.OpenAIModel)
  适用于通义千问、DeepSeek、智谱等国内模型
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """单个模型配置。"""

    name: str                          # 模型别名，如 "gemini-flash", "deepseek"
    provider: str                      # "gemini" | "openai_compatible"
    model_id: str                      # 模型 ID，如 "gemini-2.5-flash", "deepseek-chat"
    api_key: str = ""                  # API Key
    base_url: str = ""                 # OpenAI 兼容接口的 base_url
    params: dict[str, Any] = field(default_factory=dict)  # 额外参数，如 temperature


def load_models_config(config_path: str = "models.json") -> list[ModelConfig]:
    """从 JSON 文件加载模型配置列表。"""
    path = Path(config_path)
    if not path.exists():
        logger.warning("模型配置文件未找到: %s", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        models = []
        for item in data.get("models", []):
            models.append(ModelConfig(
                name=item["name"],
                provider=item["provider"],
                model_id=item["model_id"],
                api_key=item.get("api_key", ""),
                base_url=item.get("base_url", ""),
                params=item.get("params", {}),
            ))
        logger.info("已加载 %d 个模型配置", len(models))
        return models
    except Exception as e:
        logger.error("加载模型配置失败: %s", e)
        return []


class ModelManager:
    """多模型管理器，支持运行时切换模型。"""

    def __init__(
        self,
        models: list[ModelConfig],
        default_model: str = "",
    ) -> None:
        self._models: dict[str, ModelConfig] = {m.name: m for m in models}
        self._current_name: str = default_model or (models[0].name if models else "")
        self._current_model: Any = None

        if self._current_name:
            logger.info("默认模型: %s", self._current_name)

    @property
    def current_model_name(self) -> str:
        """当前使用的模型名称。"""
        return self._current_name

    @property
    def available_models(self) -> list[str]:
        """所有可用模型名称列表。"""
        return list(self._models.keys())

    def get_model(self) -> Any:
        """获取当前模型实例（延迟创建）。"""
        if self._current_model is None:
            self._current_model = self._create_model(self._current_name)
        return self._current_model

    def switch_model(self, name: str) -> str:
        """切换到指定模型。

        Args:
            name: 模型别名。

        Returns:
            切换结果描述。
        """
        if name not in self._models:
            available = ", ".join(self._models.keys())
            return f"模型 '{name}' 不存在。可用模型: {available}"

        if name == self._current_name and self._current_model is not None:
            return f"当前已在使用 {name}"

        self._current_name = name
        self._current_model = self._create_model(name)
        logger.info("模型已切换: %s (model_id=%s)", name, self._models[name].model_id)
        return f"已切换到 {name}"

    def _create_model(self, name: str) -> Any:
        """根据配置创建模型实例。"""
        if name not in self._models:
            raise ValueError(f"模型 '{name}' 不存在")

        config = self._models[name]

        if config.provider == "gemini":
            return self._create_gemini_model(config)
        elif config.provider == "openai_compatible":
            return self._create_openai_model(config)
        else:
            raise ValueError(f"不支持的 provider: {config.provider}")

    def _create_gemini_model(self, config: ModelConfig) -> Any:
        """创建 Gemini 模型实例。"""
        try:
            from strands.models.gemini import GeminiModel
        except ImportError:
            raise ImportError(
                "strands-agents[gemini] 未安装，请运行: uv add 'strands-agents[gemini]'"
            )

        client_args: dict[str, Any] = {}
        if config.api_key:
            client_args["api_key"] = config.api_key

        return GeminiModel(
            model_id=config.model_id,
            client_args=client_args or None,
            **config.params,
        )

    def _create_openai_model(self, config: ModelConfig) -> Any:
        """创建 OpenAI 兼容模型实例。"""
        try:
            from strands.models.openai import OpenAIModel
        except ImportError:
            raise ImportError(
                "strands-agents[openai] 未安装，请运行: uv add 'strands-agents[openai]'"
            )

        client_args: dict[str, Any] = {}
        if config.api_key:
            client_args["api_key"] = config.api_key
        if config.base_url:
            client_args["base_url"] = config.base_url

        return OpenAIModel(
            model_id=config.model_id,
            client_args=client_args or None,
            **config.params,
        )
