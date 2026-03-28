"""唤醒词检测器：使用 sherpa-onnx keyword spotting。

sherpa-onnx 支持直接传中文文字作为关键词，无需训练模型文件。
"""

import asyncio
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class SherpaWakeWordDetector:
    """基于 sherpa-onnx 的唤醒词检测器。"""

    _MIC_RETRY_DELAY: float = 5.0

    def __init__(self, keywords: list[str], model_path: str = "") -> None:
        self._keywords = keywords
        self._model_path = model_path
        self._listening = False
        self._callbacks: list[Callable[[], None]] = []
        self._recognizer: object | None = None
        self._pa: object | None = None
        self._stream: object | None = None
        self._sample_rate = 16000

    def on_wake_word(self, callback: Callable[[], None]) -> None:
        """注册唤醒词检测回调。"""
        self._callbacks.append(callback)

    async def start_listening(self) -> None:
        """开始监听唤醒词。"""
        try:
            import sherpa_onnx  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "sherpa-onnx is required. Install with: pip install sherpa-onnx"
            ) from e

        try:
            import pyaudio  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "pyaudio is required. Install with: pip install pyaudio"
            ) from e

        self._listening = True
        self._recognizer = self._create_recognizer(sherpa_onnx)

        while self._listening:
            try:
                if self._pa is None:
                    self._pa = pyaudio.PyAudio()
                    self._stream = self._pa.open(
                        format=pyaudio.paInt16,
                        channels=1,
                        rate=self._sample_rate,
                        input=True,
                        frames_per_buffer=1024,
                    )

                data = self._stream.read(1024, exception_on_overflow=False)  # type: ignore[union-attr]
                stream = self._recognizer.create_stream()  # type: ignore[union-attr]
                stream.accept_waveform(
                    self._sample_rate,
                    list(
                        int.from_bytes(data[i : i + 2], "little", signed=True)
                        for i in range(0, len(data), 2)
                    ),
                )

                while self._recognizer.is_ready(stream):  # type: ignore[union-attr]
                    self._recognizer.decode_stream(stream)  # type: ignore[union-attr]

                result = self._recognizer.get_result(stream)  # type: ignore[union-attr]
                if result and result.strip():
                    keyword = result.strip().lower()
                    for kw in self._keywords:
                        if kw.lower() in keyword or keyword in kw.lower():
                            logger.info("唤醒词已检测到: %s", keyword)
                            for cb in self._callbacks:
                                cb()
                            break

            except OSError as exc:
                logger.error("麦克风访问错误: %s，%s 秒后重试", exc, self._MIC_RETRY_DELAY)
                self._close_audio_stream()
                await asyncio.sleep(self._MIC_RETRY_DELAY)
                continue

            await asyncio.sleep(0)

    def _create_recognizer(self, sherpa_onnx: object) -> object:
        """创建 sherpa-onnx keyword spotter。"""
        keywords_str = "/".join(self._keywords)
        config = sherpa_onnx.KeywordSpotterConfig(  # type: ignore[attr-defined]
            keywords_buf=keywords_str,
        )
        if self._model_path:
            config.model_config.transducer.encoder = self._model_path

        return sherpa_onnx.KeywordSpotter(config)  # type: ignore[attr-defined]

    async def stop_listening(self) -> None:
        """停止监听，释放资源。"""
        self._listening = False
        self._close_audio_stream()
        self._recognizer = None

    def _close_audio_stream(self) -> None:
        """关闭音频流。"""
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
