"""模型切换工具：让 Agent 可以在对话中切换 LLM 模型。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.model_manager import ModelManager

logger = logging.getLogger(__name__)


def _list_models(manager: ModelManager) -> str:
    """列出所有可用模型。"""
    models = manager.available_models
    current = manager.current_model_name
    lines = []
    for name in models:
        marker = " (当前)" if name == current else ""
        lines.append(f"- {name}{marker}")
    return "可用模型:\n" + "\n".join(lines)


def _switch_model(name: str, manager: ModelManager) -> str:
    """切换到指定模型。"""
    result = manager.switch_model(name)
    logger.info("模型切换: %s", result)
    return result


def create_model_tools(manager: ModelManager) -> list:
    """创建 strands-agents 兼容的模型管理工具列表。

    Args:
        manager: ModelManager 实例。

    Returns:
        包含 list_models 和 switch_model 两个 @tool 函数的列表。
    """
    try:
        from strands import tool
    except ImportError:
        raise ImportError(
            "strands-agents 未安装，请运行: uv add strands-agents"
        )

    @tool
    def list_models() -> str:
        """列出所有可用的 AI 模型。返回模型名称列表，标注当前使用的模型。"""
        return _list_models(manager)

    @tool
    def switch_model(model_name: str) -> str:
        """切换当前使用的 AI 模型。

        Args:
            model_name: 要切换到的模型别名。
        """
        return _switch_model(model_name, manager)

    return [list_models, switch_model]
