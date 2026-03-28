"""Memory 工具模块：为 strands-agents 提供 MEMORY.md 读写工具。

提供两个核心功能：
- read_memory: 读取 MEMORY.md 文件内容
- update_memory: 将新信息追加或更新到 MEMORY.md

工具以纯函数形式实现，可独立测试。通过 create_memory_tools() 工厂函数
包装为 strands @tool 装饰器版本供 Agent 使用。
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_PATH = "MEMORY.md"


def _read_memory(memory_path: str = DEFAULT_MEMORY_PATH) -> str:
    """读取 MEMORY.md 文件内容。

    Args:
        memory_path: 记忆文件路径，默认为 MEMORY.md。

    Returns:
        文件内容字符串；文件不存在时返回空字符串。
    """
    path = Path(memory_path)
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.debug("MEMORY.md 文件未找到: %s", path)
        return ""
    except OSError as e:
        logger.error("读取 MEMORY.md 失败: %s", e)
        return ""


def _update_memory(content: str, memory_path: str = DEFAULT_MEMORY_PATH) -> str:
    """将新内容写入 MEMORY.md 文件。

    Args:
        content: 要写入的完整记忆内容。
        memory_path: 记忆文件路径，默认为 MEMORY.md。

    Returns:
        操作结果描述字符串。
    """
    path = Path(memory_path)
    try:
        path.write_text(content, encoding="utf-8")
        return f"记忆已更新: {path}"
    except OSError as e:
        logger.error("更新 MEMORY.md 失败: %s", e)
        return f"记忆更新失败: {e}"


def create_memory_tools(memory_path: str = DEFAULT_MEMORY_PATH) -> list:
    """创建 strands-agents 兼容的 memory 工具列表。

    延迟导入 strands，仅在调用时才需要 strands-agents 已安装。

    Args:
        memory_path: 记忆文件路径，默认为 MEMORY.md。

    Returns:
        包含 read_memory 和 update_memory 两个 @tool 装饰函数的列表。

    Raises:
        ImportError: 如果 strands-agents 未安装。
    """
    try:
        from strands import tool
    except ImportError:
        raise ImportError(
            "strands-agents 未安装，请运行: uv add strands-agents"
        )

    @tool
    def read_memory() -> str:
        """读取记忆文件内容。返回 MEMORY.md 中保存的所有记忆信息。"""
        return _read_memory(memory_path)

    @tool
    def update_memory(content: str) -> str:
        """更新记忆文件。将提供的内容写入 MEMORY.md，替换原有内容。

        Args:
            content: 要写入的完整记忆内容（Markdown 格式）。
        """
        return _update_memory(content, memory_path)

    return [read_memory, update_memory]
