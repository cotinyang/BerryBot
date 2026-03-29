"""客户端唤醒词检测器：使用 pvporcupine 进行唤醒词检测。"""

import asyncio
import logging
import struct
from collections.abc import Callable

from client.audio_backend import create_pyaudio, open_input_stream

logger = logging.getLogger(__name__)


class PorcupineWakeWordDetector:
    """唤醒词检测器，使用 pvporcupine 进行离线唤醒词检测。

    pvporcupine 为可选依赖，仅在 start_listening 时延迟导入。
    """

    _MIC_RETRY_DELAY: float = 5.0

    def __init__(self, access_key: str, keyword_path: str) -> None:
        self._access_key = access_key
        self._keyword_path = keyword_path
        self._listening = False
        self._callbacks: list[Callable[[], None]] = []
        self._porcupine: object | None = None
        self._pa: object | None = None
        self._stream: object | None = None

    def on_wake_word(self, callback: Callable[[], None]) -> None:
        """注册唤醒词检测回调。"""
        self._callbacks.append(callback)

    async def start_listening(self) -> None:
        """开始监听唤醒词。延迟导入 pvporcupine 和 pyaudio。"""
        try:
            import pvporcupine  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "pvporcupine is required for wake word detection. "
                "Install it with: pip install pvporcupine"
            ) from e

        try:
            import pyaudio  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "pyaudio is required for wake word detection. "
                "Install it with: pip install pyaudio"
            ) from e

        self._listening = True

        self._porcupine = pvporcupine.create(
            access_key=self._access_key,
            keyword_paths=[self._keyword_path],
        )

        while self._listening:
            try:
                if self._pa is None:
                    self._pa = create_pyaudio(pyaudio)
                    self._stream = open_input_stream(
                        self._pa,
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=self._porcupine.sample_rate,
                        input=True,
                        frames_per_buffer=self._porcupine.frame_length,
                    )

                raw = self._stream.read(  # type: ignore[union-attr]
                    self._porcupine.frame_length,
                    exception_on_overflow=False,
                )
                pcm = struct.unpack_from(
                    f"{self._porcupine.frame_length}h", raw
                )
                result = self._porcupine.process(pcm)

                if result >= 0:
                    logger.info("唤醒词已检测到")
                    for cb in self._callbacks:
                        cb()

            except OSError as exc:
                logger.error("麦克风访问错误: %s，%s 秒后重试", exc, self._MIC_RETRY_DELAY)
                self._close_audio_stream()
                await asyncio.sleep(self._MIC_RETRY_DELAY)
                continue

            await asyncio.sleep(0)

    async def stop_listening(self) -> None:
        """停止监听唤醒词，释放资源。"""
        self._listening = False
        self._close_audio_stream()

        if self._porcupine is not None:
            self._porcupine.delete()  # type: ignore[union-attr]
            self._porcupine = None

    def _close_audio_stream(self) -> None:
        """关闭音频流和 PyAudio 实例。"""
        if self._stream is not None:
            try:
                self._stream.stop_stream()  # type: ignore[union-attr]
                self._stream.close()  # type: ignore[union-attr]
            except OSError:
                pass
            self._stream = None

        if self._pa is not None:
            self._pa.terminate()  # type: ignore[union-attr]
            self._pa = None
