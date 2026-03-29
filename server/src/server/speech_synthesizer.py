"""语音合成模块：使用 edge-tts 将文字转换为 MP3 语音数据。"""

from collections.abc import AsyncIterator
import logging
import re

import edge_tts

logger = logging.getLogger(__name__)


class SpeechSynthesizer:
    """语音合成器，使用 edge-tts 将文字转换为 MP3 格式语音。"""

    def __init__(
        self,
        voice: str = "zh-CN-XiaoxiaoNeural",
        sentence_stream: bool = True,
        sentence_max_chars: int = 80,
    ) -> None:
        self._voice = voice
        self._sentence_stream = sentence_stream
        self._sentence_max_chars = max(20, sentence_max_chars)

    async def synthesize_stream(self, text: str) -> AsyncIterator[bytes]:
        """流式合成语音数据（MP3 chunk）。

        Args:
            text: 要合成的文字内容。

        Yields:
            MP3 音频字节 chunk。

        Raises:
            ValueError: 输入文本为空。
            RuntimeError: 语音合成过程中发生错误。
        """
        if not text or not text.strip():
            raise ValueError("合成文本不能为空")

        try:
            if self._sentence_stream:
                segments = self._split_text_segments(text)
            else:
                segments = [text.strip()]

            for segment in segments:
                communicate = edge_tts.Communicate(segment, self._voice)
                async for chunk in communicate.stream():
                    if chunk.get("type") == "audio":
                        data = chunk.get("data", b"")
                        if data:
                            yield data
        except ValueError:
            raise
        except Exception as e:
            logger.error("语音合成错误: %s", e)
            raise RuntimeError(f"语音合成错误: {e}") from e

    def _split_text_segments(self, text: str) -> list[str]:
        """按句拆分文本；超长句进一步切块，降低单次 TTS 时延抖动。"""
        normalized = " ".join(text.split())
        if not normalized:
            return []

        parts = [
            part.strip()
            for part in re.split(r"(?<=[。！？!?；;])\s*", normalized)
            if part.strip()
        ]
        if not parts:
            parts = [normalized]

        segments: list[str] = []
        for part in parts:
            remaining = part
            while len(remaining) > self._sentence_max_chars:
                split_at = self._find_split_index(remaining, self._sentence_max_chars)
                head = remaining[:split_at].strip()
                if head:
                    segments.append(head)
                remaining = remaining[split_at:].strip()
            if remaining:
                segments.append(remaining)
        return segments

    @staticmethod
    def _find_split_index(text: str, limit: int) -> int:
        """优先在停顿符处分段，找不到则按字符硬切。"""
        candidates = [
            text.rfind("，", 0, limit),
            text.rfind(",", 0, limit),
            text.rfind("、", 0, limit),
            text.rfind(" ", 0, limit),
        ]
        best = max(candidates)
        if best <= 0:
            return limit
        return best + 1

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
        audio_chunks: list[bytes] = []
        async for chunk in self.synthesize_stream(text):
            audio_chunks.append(chunk)

        audio_bytes = b"".join(audio_chunks)
        if not audio_bytes:
            raise RuntimeError("语音合成未产生音频数据")

        logger.info("语音合成完成: text=%s, size=%d bytes", text[:30], len(audio_bytes))
        return audio_bytes
