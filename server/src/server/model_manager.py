"""多模型管理器：支持预配置多个 LLM 模型并在运行时切换。

配置按 provider 分组，同一 provider 下的模型共享 api_key、proxy 等通用配置，
单个模型可覆盖 provider 级别的配置。

支持的 provider:
- gemini: Google Gemini (strands.models.gemini.GeminiModel)
- openai_compatible: OpenAI 兼容接口 (strands.models.openai.OpenAIModel)
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
    """单个模型的最终配置（已合并 provider 级别配置）。"""

    name: str
    provider: str
    model_id: str
    api_key: str = ""
    base_url: str = ""
    proxy: str = ""
    params: dict[str, Any] = field(default_factory=dict)


def load_models_config(config_path: str = "models.json") -> tuple[list[ModelConfig], str]:
    """从 JSON 文件加载模型配置。

    支持两种格式：
    1. 按 provider 分组（推荐）：providers.{gemini|openai_compatible}.models
    2. 扁平列表（向后兼容）：models[]

    Returns:
        (模型配置列表, 默认模型名称)
    """
    path = Path(config_path)
    if not path.exists():
        logger.warning("模型配置文件未找到: %s", path)
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        default_model = data.get("default_model", "")

        # 新格式：按 provider 分组
        if "providers" in data:
            models = _load_grouped_config(data["providers"])
        # 旧格式：扁平列表（向后兼容）
        elif "models" in data:
            models = _load_flat_config(data["models"])
        else:
            models = []

        logger.info("已加载 %d 个模型配置", len(models))
        return models, default_model
    except Exception as e:
        logger.error("加载模型配置失败: %s", e)
        return [], ""


def _load_grouped_config(providers: dict) -> list[ModelConfig]:
    """解析按 provider 分组的配置。"""
    models = []
    for provider_name, provider_cfg in providers.items():
        # provider 级别的通用配置
        shared_api_key = provider_cfg.get("api_key", "")
        shared_base_url = provider_cfg.get("base_url", "")
        shared_proxy = provider_cfg.get("proxy", "")
        shared_params = provider_cfg.get("params", {})

        for item in provider_cfg.get("models", []):
            # 模型级别覆盖 provider 级别
            params = {**shared_params, **item.get("params", {})}
            models.append(ModelConfig(
                name=item["name"],
                provider=provider_name,
                model_id=item["model_id"],
                api_key=item.get("api_key", shared_api_key),
                base_url=item.get("base_url", shared_base_url),
                proxy=item.get("proxy", shared_proxy),
                params=params,
            ))
    return models


def _load_flat_config(items: list) -> list[ModelConfig]:
    """解析扁平列表配置（向后兼容）。"""
    return [
        ModelConfig(
            name=item["name"],
            provider=item["provider"],
            model_id=item["model_id"],
            api_key=item.get("api_key", ""),
            base_url=item.get("base_url", ""),
            proxy=item.get("proxy", ""),
            params=item.get("params", {}),
        )
        for item in items
    ]


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
        return self._current_name

    @property
    def available_models(self) -> list[str]:
        return list(self._models.keys())

    def get_model(self) -> Any:
        if self._current_model is None:
            self._current_model = self._create_model(self._current_name)
        return self._current_model

    def switch_model(self, name: str) -> str:
        resolved = self._fuzzy_match(name)
        if resolved is None:
            available = ", ".join(self._models.keys())
            return f"模型 '{name}' 不存在。可用模型: {available}"

        if resolved == self._current_name and self._current_model is not None:
            return f"当前已在使用 {resolved}"

        self._current_name = resolved
        self._current_model = self._create_model(resolved)
        logger.info("模型已切换: %s (model_id=%s)", resolved, self._models[resolved].model_id)
        return f"已切换到 {resolved}"

    def _fuzzy_match(self, query: str) -> str | None:
        """模糊匹配模型名称。

        匹配规则（按优先级）：
        1. 精确匹配（忽略大小写）
        2. 模型名包含查询词（忽略大小写）
        3. 查询词包含模型名（忽略大小写）

        Returns:
            匹配到的模型名称，未匹配返回 None。
        """
        q = query.strip().lower()

        # 精确匹配
        for name in self._models:
            if name.lower() == q:
                return name

        # 模型名包含查询词
        candidates = [name for name in self._models if q in name.lower()]
        if len(candidates) == 1:
            return candidates[0]

        # 查询词包含模型名
        candidates = [name for name in self._models if name.lower() in q]
        if len(candidates) == 1:
            return candidates[0]

        # 多个匹配时取最短的（最具体的）
        if candidates:
            return min(candidates, key=len)

        return None

    def _create_model(self, name: str) -> Any:
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
        try:
            from strands.models.gemini import GeminiModel
        except ImportError:
            raise ImportError(
                "strands-agents[gemini] 未安装，请运行: uv add 'strands-agents[gemini]'"
            )

        client_args: dict[str, Any] = {}
        if config.api_key:
            client_args["api_key"] = config.api_key
        if config.proxy:
            # google-genai 的 HttpOptions 不接受顶层 proxy，
            # 需要通过 client_args 透传给底层 httpx.Client。
            client_args["http_options"] = {"client_args": {"proxy": config.proxy}}
            logger.info("Gemini 模型 %s 使用代理: %s", config.name, config.proxy)

        return GeminiModel(
            model_id=config.model_id,
            client_args=client_args or None,
            **config.params,
        )

    def _create_openai_model(self, config: ModelConfig) -> Any:
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
        if config.proxy:
            import httpx
            client_args["http_client"] = httpx.Client(proxy=config.proxy)
            logger.info("OpenAI 模型 %s 使用代理: %s", config.name, config.proxy)

        return OpenAIModel(
            model_id=config.model_id,
            client_args=client_args or None,
            **config.params,
        )
