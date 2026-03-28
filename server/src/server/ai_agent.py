"""AI Agent 模块：使用 strands-agents 处理用户文字输入。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.model_manager import ModelManager

logger = logging.getLogger(__name__)


class AIAgent:
    """AI 代理，使用 strands-agents 处理用户文字输入并生成回复。

    通过 SOUL.md 定义 Agent 人格，通过 MEMORY.md 实现持久化记忆。
    支持多模型切换。
    """

    def __init__(
        self,
        soul_path: str = "SOUL.md",
        memory_path: str = "MEMORY.md",
        tools: list | None = None,
        model_manager: ModelManager | None = None,
    ) -> None:
        self._soul_path = Path(soul_path)
        self._memory_path = Path(memory_path)
        self._tools = tools or []
        self._model_manager = model_manager
        self._agent = None
        self._current_model_name: str = ""

    def _load_soul(self) -> str:
        """读取 SOUL.md 文件内容作为 Agent 的人格/系统提示。"""
        try:
            return self._soul_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("SOUL.md 文件未找到: %s，使用默认系统提示", self._soul_path)
            return "你是一个友好的中文语音助手。"
        except OSError as e:
            logger.error("读取 SOUL.md 失败: %s", e)
            return "你是一个友好的中文语音助手。"

    def _load_memory(self) -> str:
        """读取 MEMORY.md 文件内容作为对话上下文。"""
        try:
            return self._memory_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.debug("MEMORY.md 文件未找到: %s", self._memory_path)
            return ""
        except OSError as e:
            logger.error("读取 MEMORY.md 失败: %s", e)
            return ""

    def _update_memory(self, new_content: str) -> None:
        """更新 MEMORY.md 文件，记录值得保存的信息。"""
        try:
            self._memory_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            logger.error("更新 MEMORY.md 失败: %s", e)

    def _ensure_agent(self) -> None:
        """延迟初始化 strands Agent 实例。模型切换时重新创建。"""
        model_name = self._model_manager.current_model_name if self._model_manager else ""
        need_rebuild = (
            self._agent is None
            or (model_name and model_name != self._current_model_name)
        )
        if not need_rebuild:
            return

        try:
            from strands import Agent
        except ImportError:
            raise ImportError(
                "strands-agents 未安装，请运行: uv add strands-agents"
            )

        soul = self._load_soul()
        kwargs: dict[str, Any] = {
            "system_prompt": soul,
            "tools": self._tools,
        }
        if self._model_manager:
            kwargs["model"] = self._model_manager.get_model()
            self._current_model_name = model_name
            logger.info("Agent 使用模型: %s", model_name)

        self._agent = Agent(**kwargs)

    async def process(self, text: str) -> str:
        """处理用户文字输入，返回 AI 回复文字。

        处理前读取 MEMORY.md 作为上下文，处理后按需更新 MEMORY.md。
        """
        try:
            self._ensure_agent()
        except ImportError:
            raise
        except Exception as e:
            raise RuntimeError(f"AI Agent 初始化错误: {e}") from e

        memory = self._load_memory()
        prompt = text
        if memory:
            logger.info("加载记忆上下文: %d chars", len(memory))
            prompt = f"[记忆上下文]\n{memory}\n\n[用户输入]\n{text}"

        try:
            logger.info("AI Agent 处理中: input=%s", text[:50])
            result = self._agent(prompt)
            response_text = str(result)
            logger.info("AI Agent 回复: %s", response_text[:50])
            return response_text
        except Exception as e:
            logger.error("AI Agent 处理错误: %s", e)
            raise RuntimeError(f"AI Agent 处理错误: {e}") from e
