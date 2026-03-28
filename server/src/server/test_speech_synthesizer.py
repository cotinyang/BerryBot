"""SpeechSynthesizer 单元测试。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from server.speech_synthesizer import SpeechSynthesizer


class TestSpeechSynthesizerInit:
    """初始化测试。"""

    def test_default_voice(self):
        synth = SpeechSynthesizer()
        assert synth._voice == "zh-CN-XiaoxiaoNeural"

    def test_custom_voice(self):
        synth = SpeechSynthesizer(voice="en-US-AriaNeural")
        assert synth._voice == "en-US-AriaNeural"


class TestSynthesize:
    """synthesize 方法测试。"""

    @pytest.mark.asyncio
    async def test_successful_synthesis(self):
        """成功合成应返回非空 MP3 字节数据。"""
        synth = SpeechSynthesizer()
        fake_audio = b"\xff\xfb\x90\x00" * 100  # fake MP3 bytes

        async def fake_stream():
            yield {"type": "audio", "data": fake_audio[:200]}
            yield {"type": "WordBoundary", "data": {}}
            yield {"type": "audio", "data": fake_audio[200:]}

        mock_communicate = MagicMock()
        mock_communicate.stream = fake_stream

        with patch("server.speech_synthesizer.edge_tts.Communicate", return_value=mock_communicate):
            result = await synth.synthesize("你好世界")

        assert result == fake_audio
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_filters_non_audio_chunks(self):
        """应只收集 type=audio 的 chunk 数据。"""
        synth = SpeechSynthesizer()
        audio_data = b"\x00\x01\x02\x03"

        async def fake_stream():
            yield {"type": "WordBoundary", "data": {"text": "你好"}}
            yield {"type": "audio", "data": audio_data}
            yield {"type": "SentenceBoundary", "data": {}}

        mock_communicate = MagicMock()
        mock_communicate.stream = fake_stream

        with patch("server.speech_synthesizer.edge_tts.Communicate", return_value=mock_communicate):
            result = await synth.synthesize("你好")

        assert result == audio_data

    @pytest.mark.asyncio
    async def test_empty_text_raises_value_error(self):
        """空文本应抛出 ValueError。"""
        synth = SpeechSynthesizer()
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await synth.synthesize("")

    @pytest.mark.asyncio
    async def test_whitespace_only_text_raises_value_error(self):
        """仅含空白的文本应抛出 ValueError。"""
        synth = SpeechSynthesizer()
        with pytest.raises(ValueError, match="合成文本不能为空"):
            await synth.synthesize("   ")

    @pytest.mark.asyncio
    async def test_no_audio_data_raises_runtime_error(self):
        """合成未产生音频数据时应抛出 RuntimeError。"""
        synth = SpeechSynthesizer()

        async def fake_stream():
            yield {"type": "WordBoundary", "data": {}}

        mock_communicate = MagicMock()
        mock_communicate.stream = fake_stream

        with patch("server.speech_synthesizer.edge_tts.Communicate", return_value=mock_communicate):
            with pytest.raises(RuntimeError, match="语音合成未产生音频数据"):
                await synth.synthesize("你好")

    @pytest.mark.asyncio
    async def test_edge_tts_error_raises_runtime_error(self):
        """edge-tts 异常应包装为 RuntimeError。"""
        synth = SpeechSynthesizer()

        async def failing_stream():
            raise ConnectionError("网络错误")
            yield  # noqa: unreachable - makes this an async generator

        mock_communicate = MagicMock()
        mock_communicate.stream = failing_stream

        with patch("server.speech_synthesizer.edge_tts.Communicate", return_value=mock_communicate):
            with pytest.raises(RuntimeError, match="语音合成错误"):
                await synth.synthesize("你好")

    @pytest.mark.asyncio
    async def test_voice_passed_to_communicate(self):
        """应将配置的语音角色传递给 Communicate。"""
        synth = SpeechSynthesizer(voice="zh-CN-YunxiNeural")

        async def fake_stream():
            yield {"type": "audio", "data": b"\x00"}

        mock_communicate = MagicMock()
        mock_communicate.stream = fake_stream

        with patch("server.speech_synthesizer.edge_tts.Communicate", return_value=mock_communicate) as mock_cls:
            await synth.synthesize("测试")
            mock_cls.assert_called_once_with("测试", "zh-CN-YunxiNeural")

    @pytest.mark.asyncio
    async def test_chinese_voice_default(self):
        """默认语音角色应为中文 XiaoxiaoNeural。"""
        synth = SpeechSynthesizer()

        async def fake_stream():
            yield {"type": "audio", "data": b"\x00"}

        mock_communicate = MagicMock()
        mock_communicate.stream = fake_stream

        with patch("server.speech_synthesizer.edge_tts.Communicate", return_value=mock_communicate) as mock_cls:
            await synth.synthesize("你好")
            mock_cls.assert_called_once_with("你好", "zh-CN-XiaoxiaoNeural")
