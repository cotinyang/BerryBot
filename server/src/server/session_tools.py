"""会话控制工具：让 Agent 可以发送控制指令给客户端。"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 特殊前缀，Agent 返回的文本以此开头时表示这是一个指令而非普通回复
COMMAND_PREFIX = "__CMD__:"


def _end_session() -> str:
    """结束当前会话，客户端将播放结束音并回到待机状态。"""
    logger.info("Agent 请求结束会话")
    return f"{COMMAND_PREFIX}end_session"


def create_session_tools() -> list:
    """创建 strands-agents 兼容的会话控制工具列表。"""
    try:
        from strands import tool
    except ImportError:
        raise ImportError(
            "strands-agents 未安装，请运行: uv add strands-agents"
        )

    @tool
    def end_session() -> str:
        """结束当前语音会话。当用户说"退出"、"不聊了"、"你退出吧"、"结束"等表达结束意图的话时调用此工具。
        调用后客户端会播放结束提示音并回到待机状态。"""
        return _end_session()

    return [end_session]


def is_command(text: str) -> bool:
    """判断 Agent 返回的文本是否为控制指令。"""
    return text.strip().startswith(COMMAND_PREFIX)


def parse_command(text: str) -> str:
    """解析指令名称。"""
    return text.strip().removeprefix(COMMAND_PREFIX).strip()
