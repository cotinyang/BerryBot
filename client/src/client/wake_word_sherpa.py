"""唤醒词检测器：使用 sherpa-onnx keyword spotter。

需要预先下载 KWS 模型并准备 keywords 文件。
模型下载: https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html
推荐中文模型: sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01

keywords 文件需要用 sherpa-onnx-cli text2token 工具生成：
  echo "小艺小艺 @小艺小艺" > keywords_raw.txt
  sherpa-onnx-cli text2token --tokens tokens.txt --tokens-type ppinyin keywords_raw.txt keywords.txt
"""

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from client.audio_backend import create_pyaudio, open_input_stream

logger = logging.getLogger(__name__)


class SherpaWakeWordDetector:
    """基于 sherpa-onnx KeywordSpotter 的唤醒词检测器。

    需要配置 model_path 指向包含模型文件的目录，目录下应有：
    - encoder-*.onnx
    - decoder-*.onnx
    - joiner-*.onnx
    - tokens.txt
    - keywords.txt (编码后的关键词文件)
    """

    _MIC_RETRY_DELAY: float = 5.0

    def __init__(self, keywords: list[str], model_path: str = "") -> None:
        self._keywords = keywords
        self._model_path = model_path
        self._listening = False
        self._callbacks: list[Callable[[], None]] = []
        self._kws: object | None = None
        self._pa: object | None = None
        self._stream_obj: object | None = None
        self._audio_stream: object | None = None
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
        self._kws = self._create_kws(sherpa_onnx)
        self._stream_obj = self._kws.create_stream()  # type: ignore[union-attr]

        while self._listening:
            try:
                if self._pa is None:
                    self._pa = create_pyaudio(pyaudio)
                    self._audio_stream = open_input_stream(
                        self._pa,
                        format=pyaudio.paFloat32,
                        channels=1,
                        rate=self._sample_rate,
                        input=True,
                        frames_per_buffer=1024,
                    )

                data = self._audio_stream.read(1024, exception_on_overflow=False)  # type: ignore[union-attr]
                import numpy as np
                samples = np.frombuffer(data, dtype=np.float32)
                self._stream_obj.accept_waveform(self._sample_rate, samples)  # type: ignore[union-attr]

                while self._kws.is_ready(self._stream_obj):  # type: ignore[union-attr]
                    self._kws.decode_stream(self._stream_obj)  # type: ignore[union-attr]

                result = self._kws.get_result(self._stream_obj)  # type: ignore[union-attr]
                if result and result.strip():
                    logger.info("唤醒词已检测到: %s", result.strip())
                    self._kws.reset_stream(self._stream_obj)  # type: ignore[union-attr]
                    for cb in self._callbacks:
                        cb()

            except OSError as exc:
                logger.error("麦克风访问错误: %s，%s 秒后重试", exc, self._MIC_RETRY_DELAY)
                self._close_audio_stream()
                await asyncio.sleep(self._MIC_RETRY_DELAY)
                continue

            await asyncio.sleep(0)

    def _create_kws(self, sherpa_onnx: object) -> object:
        """创建 sherpa-onnx KeywordSpotter。"""
        model_dir = Path(self._model_path)
        if not model_dir.exists():
            raise RuntimeError(
                f"sherpa-onnx 模型目录不存在: {model_dir}\n"
                "请下载模型: https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html"
            )

        # 自动查找模型文件（优先 int8 版本，树莓派上更快更省内存）
        encoder = self._find_file(model_dir, "encoder-*.int8.onnx", "encoder-*.onnx")
        decoder = self._find_file(model_dir, "decoder-*.onnx")
        joiner = self._find_file(model_dir, "joiner-*.int8.onnx", "joiner-*.onnx")
        tokens = model_dir / "tokens.txt"
        keywords_file = model_dir / "keywords.txt"

        if not tokens.exists():
            raise RuntimeError(f"tokens.txt 未找到: {tokens}")
        if not keywords_file.exists():
            raise RuntimeError(
                f"keywords.txt 未找到: {keywords_file}\n"
                "请用 sherpa-onnx-cli text2token 生成关键词文件"
            )

        logger.info(
            "加载 sherpa-onnx KWS 模型: encoder=%s, keywords=%s",
            encoder.name, keywords_file
        )

        return sherpa_onnx.KeywordSpotter(  # type: ignore[attr-defined]
            tokens=str(tokens),
            encoder=str(encoder),
            decoder=str(decoder),
            joiner=str(joiner),
            num_threads=2,
            keywords_file=str(keywords_file),
            provider="cpu",
        )

    def _find_file(self, directory: Path, *patterns: str) -> Path:
        """在目录中查找匹配的文件。"""
        for pattern in patterns:
            matches = list(directory.glob(pattern))
            if matches:
                return matches[0]
        raise RuntimeError(
            f"在 {directory} 中未找到匹配 {patterns} 的文件"
        )

    async def stop_listening(self) -> None:
        """停止监听，释放资源。"""
        self._listening = False
        self._close_audio_stream()
        self._kws = None
        self._stream_obj = None

    def _close_audio_stream(self) -> None:
        """关闭音频流。"""
        if self._audio_stream is not None:
            try:
                self._audio_stream.stop_stream()  # type: ignore[union-attr]
                self._audio_stream.close()  # type: ignore[union-attr]
            except OSError:
                pass
            self._audio_stream = None

        if self._pa is not None:
            self._pa.terminate()  # type: ignore[union-attr]
            self._pa = None
