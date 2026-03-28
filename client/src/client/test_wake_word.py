"""WakeWordDetector 单元测试：使用 mock 替代 pvporcupine 和 pyaudio。"""

import asyncio
import struct
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from client.wake_word_porcupine import PorcupineWakeWordDetector


@pytest.fixture
def detector() -> PorcupineWakeWordDetector:
    return PorcupineWakeWordDetector(access_key="test-key", keyword_path="/tmp/keyword.ppn")


# ── 初始化测试 ──────────────────────────────────────────────


class TestInit:
    def test_initial_state(self, detector: PorcupineWakeWordDetector) -> None:
        """初始状态应为未监听。"""
        assert detector._listening is False
        assert detector._porcupine is None
        assert detector._pa is None
        assert detector._stream is None

    def test_stores_config(self, detector: PorcupineWakeWordDetector) -> None:
        """应保存 access_key 和 keyword_path。"""
        assert detector._access_key == "test-key"
        assert detector._keyword_path == "/tmp/keyword.ppn"


# ── on_wake_word 回调测试 ────────────────────────────────────


class TestOnWakeWord:
    def test_register_callback(self, detector: PorcupineWakeWordDetector) -> None:
        """注册回调后应存储在回调列表中。"""
        cb = MagicMock()
        detector.on_wake_word(cb)
        assert cb in detector._callbacks

    def test_register_multiple_callbacks(self, detector: PorcupineWakeWordDetector) -> None:
        """应支持注册多个回调。"""
        cb1 = MagicMock()
        cb2 = MagicMock()
        detector.on_wake_word(cb1)
        detector.on_wake_word(cb2)
        assert len(detector._callbacks) == 2


# ── start_listening 测试 ─────────────────────────────────────


class TestStartListening:
    @pytest.mark.asyncio
    async def test_import_error_pvporcupine(self, detector: PorcupineWakeWordDetector) -> None:
        """pvporcupine 未安装时应抛出 RuntimeError。"""
        with patch.dict("sys.modules", {"pvporcupine": None}):
            with pytest.raises(RuntimeError, match="pvporcupine is required"):
                await detector.start_listening()

    @pytest.mark.asyncio
    async def test_import_error_pyaudio(self, detector: PorcupineWakeWordDetector) -> None:
        """pyaudio 未安装时应抛出 RuntimeError（pvporcupine 可用）。"""
        mock_porcupine_mod = MagicMock()
        with patch.dict("sys.modules", {"pvporcupine": mock_porcupine_mod, "pyaudio": None}):
            with pytest.raises(RuntimeError, match="pyaudio is required"):
                await detector.start_listening()

    @pytest.mark.asyncio
    async def test_wake_word_detected_triggers_callbacks(self) -> None:
        """检测到唤醒词时应触发所有注册的回调。"""
        mock_porcupine = MagicMock()
        mock_porcupine.sample_rate = 16000
        mock_porcupine.frame_length = 512

        mock_porcupine_mod = MagicMock()
        mock_porcupine_mod.create.return_value = mock_porcupine

        mock_pa_instance = MagicMock()
        mock_stream = MagicMock()
        mock_pa_instance.open.return_value = mock_stream

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.PyAudio.return_value = mock_pa_instance
        mock_pyaudio_mod.paInt16 = 8

        # 第一次检测到唤醒词，之后停止
        frame_bytes = struct.pack(f"<{512}h", *([100] * 512))
        mock_stream.read.return_value = frame_bytes

        detect_count = 0

        def process_side_effect(pcm):
            nonlocal detect_count
            detect_count += 1
            if detect_count == 1:
                return 0  # 检测到唤醒词
            return -1  # 后续不再检测到

        mock_porcupine.process.side_effect = process_side_effect

        detector = PorcupineWakeWordDetector(access_key="key", keyword_path="/tmp/kw.ppn")
        cb1 = MagicMock()
        cb2 = MagicMock()
        detector.on_wake_word(cb1)
        detector.on_wake_word(cb2)

        with patch.dict("sys.modules", {
            "pvporcupine": mock_porcupine_mod,
            "pyaudio": mock_pyaudio_mod,
        }):
            async def stop_after_one():
                await asyncio.sleep(0.01)
                detector._listening = False

            task = asyncio.create_task(detector.start_listening())
            stop_task = asyncio.create_task(stop_after_one())
            await asyncio.gather(task, stop_task)

        cb1.assert_called_once()
        cb2.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_wake_word_no_callback(self) -> None:
        """未检测到唤醒词时不应触发回调。"""
        mock_porcupine = MagicMock()
        mock_porcupine.sample_rate = 16000
        mock_porcupine.frame_length = 512

        mock_porcupine_mod = MagicMock()
        mock_porcupine_mod.create.return_value = mock_porcupine

        mock_pa_instance = MagicMock()
        mock_stream = MagicMock()
        mock_pa_instance.open.return_value = mock_stream

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.PyAudio.return_value = mock_pa_instance
        mock_pyaudio_mod.paInt16 = 8

        frame_bytes = struct.pack(f"<{512}h", *([100] * 512))
        mock_stream.read.return_value = frame_bytes
        mock_porcupine.process.return_value = -1  # 未检测到

        detector = PorcupineWakeWordDetector(access_key="key", keyword_path="/tmp/kw.ppn")
        cb = MagicMock()
        detector.on_wake_word(cb)

        with patch.dict("sys.modules", {
            "pvporcupine": mock_porcupine_mod,
            "pyaudio": mock_pyaudio_mod,
        }):
            async def stop_after_brief():
                await asyncio.sleep(0.01)
                detector._listening = False

            task = asyncio.create_task(detector.start_listening())
            stop_task = asyncio.create_task(stop_after_brief())
            await asyncio.gather(task, stop_task)

        cb.assert_not_called()


    @pytest.mark.asyncio
    async def test_mic_error_retries_after_delay(self) -> None:
        """麦克风访问错误时应记录日志并在延迟后重试。"""
        mock_porcupine = MagicMock()
        mock_porcupine.sample_rate = 16000
        mock_porcupine.frame_length = 512

        mock_porcupine_mod = MagicMock()
        mock_porcupine_mod.create.return_value = mock_porcupine

        mock_pa_instance = MagicMock()
        mock_stream = MagicMock()
        mock_pa_instance.open.return_value = mock_stream

        mock_pyaudio_mod = MagicMock()
        mock_pyaudio_mod.PyAudio.return_value = mock_pa_instance
        mock_pyaudio_mod.paInt16 = 8

        # 第一次读取抛出 OSError，第二次正常后停止
        call_count = 0
        frame_bytes = struct.pack(f"<{512}h", *([100] * 512))

        def read_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("Device unavailable")
            return frame_bytes

        mock_stream.read.side_effect = read_side_effect
        mock_porcupine.process.return_value = -1

        detector = PorcupineWakeWordDetector(access_key="key", keyword_path="/tmp/kw.ppn")
        # 使用较短的重试延迟以加速测试
        detector._MIC_RETRY_DELAY = 0.01

        with patch.dict("sys.modules", {
            "pvporcupine": mock_porcupine_mod,
            "pyaudio": mock_pyaudio_mod,
        }):
            async def stop_after_retry():
                await asyncio.sleep(0.05)
                detector._listening = False

            task = asyncio.create_task(detector.start_listening())
            stop_task = asyncio.create_task(stop_after_retry())
            await asyncio.gather(task, stop_task)

        # 验证在 OSError 后重新创建了 PyAudio 实例（重试）
        assert mock_pyaudio_mod.PyAudio.call_count >= 2


# ── stop_listening 测试 ──────────────────────────────────────


class TestStopListening:
    @pytest.mark.asyncio
    async def test_stop_releases_resources(self) -> None:
        """stop_listening 应释放 porcupine、stream 和 PyAudio 资源。"""
        detector = PorcupineWakeWordDetector(access_key="key", keyword_path="/tmp/kw.ppn")

        mock_porcupine = MagicMock()
        mock_stream = MagicMock()
        mock_pa = MagicMock()

        detector._porcupine = mock_porcupine
        detector._stream = mock_stream
        detector._pa = mock_pa
        detector._listening = True

        await detector.stop_listening()

        assert detector._listening is False
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()
        mock_pa.terminate.assert_called_once()
        mock_porcupine.delete.assert_called_once()
        assert detector._porcupine is None
        assert detector._stream is None
        assert detector._pa is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self) -> None:
        """未启动时调用 stop_listening 不应报错。"""
        detector = PorcupineWakeWordDetector(access_key="key", keyword_path="/tmp/kw.ppn")
        await detector.stop_listening()  # 不应抛出异常
        assert detector._listening is False

    @pytest.mark.asyncio
    async def test_stop_handles_stream_close_error(self) -> None:
        """关闭 stream 出错时不应抛出异常。"""
        detector = PorcupineWakeWordDetector(access_key="key", keyword_path="/tmp/kw.ppn")

        mock_porcupine = MagicMock()
        mock_stream = MagicMock()
        mock_stream.stop_stream.side_effect = OSError("stream error")
        mock_pa = MagicMock()

        detector._porcupine = mock_porcupine
        detector._stream = mock_stream
        detector._pa = mock_pa
        detector._listening = True

        await detector.stop_listening()  # 不应抛出异常
        assert detector._stream is None
        assert detector._pa is None
