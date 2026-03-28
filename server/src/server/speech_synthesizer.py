"""语音合成模块：使用 edge-tts 将文字转换为 MP3 语音数据。"""

import logging

import edge_tts

logger = logging.getLogger(__name__)


class SpeechSynthesizer:
    """语音合成器，使用 edge-tts 将文字转换为 MP3 格式语音。"""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural") -> None:
        self._voice = voice

    async def synthesize(self, text: str) -> bytes:
        """将文字转换为语音数据（MP3 格式）。

        Args:
            text: 要合成的文字内容。

        Returns:
            MP3 格式的音频字节数据。

        Raises:
            ValueError: 输入文本为空。
            RuntimeError: 语音合成过程中发生错误。
        """
        if not text or not text.strip():
            raise ValueError("合成文本不能为空")

        try:
            communicate = edge_tts.Communicate(text, self._voice)
            audio_bytes = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]

            if not audio_bytes:
                raise RuntimeError("语音合成未产生音频数据")

            logger.info("语音合成完成: text=%s, size=%d bytes", text[:30], len(audio_bytes))
            return audio_bytes

        except ValueError:
            raise
        except RuntimeError:
            raise
        except Exception as e:
            logger.error("语音合成错误: %s", e)
            raise RuntimeError(f"语音合成错误: {e}") from e
