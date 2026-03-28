"""wake_prompt 单元测试：mock pyaudio 和 AudioPlayer，验证智能提示音逻辑。"""

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client.audio_player import AudioPlayer
from client.config import ClientConfig
from client.interrupt_handler import InterruptHandler
from client.wake_prompt import handle_wake_prompt


def _make_config(**overrides: object) -> ClientConfig:
    defaults = dict(
        server_url="ws://localhost:8765",
        wake_word_access_key="key",
        wake_word_keyword_path="kw.ppn",
        wake_prompt_delay=0.3,
        wake_prompt_audio_path="assets/wo_zai.wav",
    )
    defaults.update(overrides)
    return ClientConfig(**defaults)  # type: ignore[arg-type]


def _silent_chunk(n: int = 1024) -> bytes:
    """全零静音块。"""
    return struct.pack(f"<{n}h", *([0] * n))


def _loud_chunk(n: int = 1024) -> bytes:
    """高能量语音块。"""
    return struct.pack(f"<{n}h", *([20000] * n))


def _make_mock_pyaudio(mock_stream: MagicMock) -> MagicMock:
    """创建 mock pyaudio 模块和 PyAudio 实例。"""
    mock_pa_instance = MagicMock()
    mock_pa_instance.open = MagicMock(return_value=mock_stream)

    mock_pyaudio = MagicMock()
    mock_pyaudio.PyAudio.return_value = mock_pa_instance
    mock_pyaudio.paInt16 = 8
    return mock_pyaudio


# ── 检测到后续语音 → 跳过提示音 ─────────────────────────────────


class TestVoiceDetected:
    @pytest.mark.asyncio
    async def test_returns_true_when_voice_detected(self) -> None:
        """窗口期内检测到语音应返回 True。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        config = _make_config()

        mock_stream = MagicMock()
        mock_stream.read = MagicMock(return_value=_loud_chunk())

        with patch("client.wake_prompt._get_pyaudio", return_value=_make_mock_pyaudio(mock_stream)):
            result = await handle_wake_prompt(handler, player, config)

        assert result is True

    @pytest.mark.asyncio
    async def test_does_not_play_prompt_when_voice_detected(self) -> None:
        """检测到语音时不应播放提示音。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        player.play = AsyncMock()  # type: ignore[method-assign]
        config = _make_config()

        mock_stream = MagicMock()
        mock_stream.read = MagicMock(return_value=_loud_chunk())

        with patch("client.wake_prompt._get_pyaudio", return_value=_make_mock_pyaudio(mock_stream)):
            await handle_wake_prompt(handler, player, config)

        player.play.assert_not_called()


# ── 未检测到语音 → 播放提示音 ────────────────────────────────────


class TestNoVoice:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_voice(self) -> None:
        """窗口期内未检测到语音应返回 False。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        player.play = AsyncMock()  # type: ignore[method-assign]
        config = _make_config()

        mock_stream = MagicMock()
        mock_stream.read = MagicMock(return_value=_silent_chunk())

        prompt_bytes = b"fake-wav-data"

        with (
            patch("client.wake_prompt._get_pyaudio", return_value=_make_mock_pyaudio(mock_stream)),
            patch("client.wake_prompt._read_prompt_file", return_value=prompt_bytes),
        ):
            result = await handle_wake_prompt(handler, player, config)

        assert result is False

    @pytest.mark.asyncio
    async def test_plays_prompt_when_no_voice(self) -> None:
        """未检测到语音时应播放提示音文件。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        player.play = AsyncMock()  # type: ignore[method-assign]
        config = _make_config(wake_prompt_audio_path="assets/wo_zai.wav")

        mock_stream = MagicMock()
        mock_stream.read = MagicMock(return_value=_silent_chunk())

        prompt_bytes = b"fake-wav-data"

        with (
            patch("client.wake_prompt._get_pyaudio", return_value=_make_mock_pyaudio(mock_stream)),
            patch("client.wake_prompt._read_prompt_file", return_value=prompt_bytes) as mock_read,
        ):
            await handle_wake_prompt(handler, player, config)

        mock_read.assert_called_once_with("assets/wo_zai.wav")
        player.play.assert_awaited_once_with(prompt_bytes)


# ── 窗口期时长 ──────────────────────────────────────────────


class TestWindowDuration:
    @pytest.mark.asyncio
    async def test_reads_correct_number_of_frames(self) -> None:
        """应根据 wake_prompt_delay 读取正确数量的帧。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        player.play = AsyncMock()  # type: ignore[method-assign]
        config = _make_config(wake_prompt_delay=0.3)

        read_calls: list[int] = []

        def mock_read(n: int, exception_on_overflow: bool = False) -> bytes:
            read_calls.append(n)
            return _silent_chunk(n)

        mock_stream = MagicMock()
        mock_stream.read = mock_read

        with (
            patch("client.wake_prompt._get_pyaudio", return_value=_make_mock_pyaudio(mock_stream)),
            patch("client.wake_prompt._read_prompt_file", return_value=b"data"),
        ):
            await handle_wake_prompt(handler, player, config)

        # 0.3s * 16000 Hz = 4800 frames total
        total_read = sum(read_calls)
        assert total_read == 4800


# ── 语音在窗口中间出现 ──────────────────────────────────────────


class TestVoiceMidWindow:
    @pytest.mark.asyncio
    async def test_voice_detected_mid_window_returns_true(self) -> None:
        """窗口期中间检测到语音应立即返回 True。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        player.play = AsyncMock()  # type: ignore[method-assign]
        config = _make_config(wake_prompt_delay=0.3)

        call_count = 0

        def mock_read(n: int, exception_on_overflow: bool = False) -> bytes:
            nonlocal call_count
            call_count += 1
            # 第 3 次读取返回语音
            if call_count >= 3:
                return _loud_chunk(n)
            return _silent_chunk(n)

        mock_stream = MagicMock()
        mock_stream.read = mock_read

        with patch("client.wake_prompt._get_pyaudio", return_value=_make_mock_pyaudio(mock_stream)):
            result = await handle_wake_prompt(handler, player, config)

        assert result is True
        # 应在第 3 次读取后提前退出，不读完全部帧
        assert call_count == 3
        player.play.assert_not_called()


# ── 资源清理 ─────────────────────────────────────────────────


class TestCleanup:
    @pytest.mark.asyncio
    async def test_stream_closed_on_voice_detected(self) -> None:
        """检测到语音后应关闭音频流和 PyAudio。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        config = _make_config()

        mock_stream = MagicMock()
        mock_stream.read = MagicMock(return_value=_loud_chunk())

        mock_pyaudio = _make_mock_pyaudio(mock_stream)
        mock_pa_instance = mock_pyaudio.PyAudio.return_value

        with patch("client.wake_prompt._get_pyaudio", return_value=mock_pyaudio):
            await handle_wake_prompt(handler, player, config)

        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_pa_instance.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_closed_on_no_voice(self) -> None:
        """未检测到语音后也应关闭音频流和 PyAudio。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        player.play = AsyncMock()  # type: ignore[method-assign]
        config = _make_config()

        mock_stream = MagicMock()
        mock_stream.read = MagicMock(return_value=_silent_chunk())

        mock_pyaudio = _make_mock_pyaudio(mock_stream)
        mock_pa_instance = mock_pyaudio.PyAudio.return_value

        with (
            patch("client.wake_prompt._get_pyaudio", return_value=mock_pyaudio),
            patch("client.wake_prompt._read_prompt_file", return_value=b"data"),
        ):
            await handle_wake_prompt(handler, player, config)

        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_pa_instance.terminate.assert_called_once()


# ── 提示音播放失败 ───────────────────────────────────────────


class TestPromptPlaybackError:
    @pytest.mark.asyncio
    async def test_returns_false_even_if_play_fails(self) -> None:
        """提示音播放失败时仍应返回 False（不抛异常）。"""
        handler = InterruptHandler(energy_threshold=500.0)
        player = AudioPlayer()
        player.play = AsyncMock(side_effect=RuntimeError("no player"))  # type: ignore[method-assign]
        config = _make_config()

        mock_stream = MagicMock()
        mock_stream.read = MagicMock(return_value=_silent_chunk())

        with (
            patch("client.wake_prompt._get_pyaudio", return_value=_make_mock_pyaudio(mock_stream)),
            patch("client.wake_prompt._read_prompt_file", return_value=b"data"),
        ):
            result = await handle_wake_prompt(handler, player, config)

        assert result is False
