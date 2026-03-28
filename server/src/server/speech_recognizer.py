"""语音识别模块：使用 pywhispercpp 将 WAV 音频转换为文字。"""

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class SpeechRecognizer:
    """语音识别器，使用 Whisper 模型将音频转换为文字。

    pywhispercpp 是可选依赖（需要编译 whisper.cpp），
    因此使用延迟导入，仅在实际调用时加载。
    """

    def __init__(self, model_size: str = "base", language: str = "zh") -> None:
        self._model_size = model_size
        self._language = language
        self._model = None

    def _ensure_model(self) -> None:
        """延迟加载 Whisper 模型。"""
        if self._model is not None:
            return
        try:
            from pywhispercpp.model import Model

            self._model = Model(self._model_size)
            logger.info(
                "Whisper 模型已加载: size=%s, language=%s",
                self._model_size,
                self._language,
            )
        except ImportError:
            raise ImportError(
                "pywhispercpp 未安装。请先编译 whisper.cpp 并安装 pywhispercpp。"
            )

    def recognize(self, audio_data: bytes) -> str:
        """将 WAV 音频数据转换为文字。

        Args:
            audio_data: WAV 格式的音频字节数据。

        Returns:
            识别出的文字内容。

        Raises:
            ValueError: 识别结果为空。
            RuntimeError: 识别过程中发生错误。
        """
        self._ensure_model()

        tmp_path = None
        try:
            # 写入临时 WAV 文件
            fd, tmp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            with open(tmp_path, "wb") as f:
                f.write(audio_data)

            # 调用 Whisper 转录
            segments = self._model.transcribe(tmp_path, language=self._language)
            text = "".join(seg.text for seg in segments).strip()

            if not text:
                raise ValueError("语音识别结果为空，未能识别语音内容")

            logger.info("语音识别完成: %s", text[:50])
            return text

        except ValueError:
            raise
        except Exception as e:
            logger.error("语音识别处理错误: %s", e)
            raise RuntimeError(f"语音识别处理错误: {e}") from e
        finally:
            # 清理临时文件
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    logger.warning("清理临时文件失败: %s", tmp_path)
