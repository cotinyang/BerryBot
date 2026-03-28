"""唤醒词检测器工厂：根据配置选择 Porcupine 或 Sherpa-onnx 引擎。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol
from collections.abc import Callable

if TYPE_CHECKING:
    from client.config import ClientConfig

logger = logging.getLogger(__name__)


class WakeWordDetector(Protocol):
    """唤醒词检测器协议（接口）。"""

    def on_wake_word(self, callback: Callable[[], None]) -> None: ...
    async def start_listening(self) -> None: ...
    async def stop_listening(self) -> None: ...


def create_wake_word_detector(config: ClientConfig) -> WakeWordDetector:
    """根据配置创建唤醒词检测器实例。

    Args:
        config: 客户端配置。

    Returns:
        WakeWordDetector 实例（Porcupine 或 Sherpa-onnx）。
    """
    engine = config.wake_word_engine.lower()

    if engine == "porcupine":
        from client.wake_word_porcupine import PorcupineWakeWordDetector
        if not config.wake_word_access_key or not config.wake_word_keyword_path:
            raise ValueError(
                "Porcupine 引擎需要配置 WAKE_WORD_ACCESS_KEY 和 WAKE_WORD_KEYWORD_PATH"
            )
        logger.info("使用 Porcupine 唤醒词引擎")
        return PorcupineWakeWordDetector(
            access_key=config.wake_word_access_key,
            keyword_path=config.wake_word_keyword_path,
        )

    elif engine == "sherpa_onnx":
        from client.wake_word_sherpa import SherpaWakeWordDetector
        keywords = [kw.strip() for kw in config.wake_word_keywords.split(",") if kw.strip()]
        if not keywords:
            raise ValueError("Sherpa-onnx 引擎需要配置 WAKE_WORD_KEYWORDS")
        logger.info("使用 Sherpa-onnx 唤醒词引擎, keywords=%s", keywords)
        return SherpaWakeWordDetector(
            keywords=keywords,
            model_path=config.wake_word_model_path,
        )

    else:
        raise ValueError(f"不支持的唤醒词引擎: {engine}，可选: porcupine, sherpa_onnx")
