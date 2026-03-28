"""InterruptHandler 单元测试：is_voice 和回调注册（纯 Python，无需硬件）。"""

import struct

import pytest

from client.interrupt_handler import InterruptHandler


@pytest.fixture
def handler() -> InterruptHandler:
    return InterruptHandler(energy_threshold=500.0)


# ── is_voice 测试 ──────────────────────────────────────────────


class TestIsVoice:
    def test_loud_signal_is_voice(self, handler: InterruptHandler) -> None:
        """高能量信号应判定为语音。"""
        chunk = struct.pack("<100h", *([20000] * 100))
        assert handler.is_voice(chunk) is True

    def test_silence_is_not_voice(self, handler: InterruptHandler) -> None:
        """全零采样应判定为非语音。"""
        chunk = struct.pack("<100h", *([0] * 100))
        assert handler.is_voice(chunk) is False

    def test_low_energy_is_not_voice(self, handler: InterruptHandler) -> None:
        """低能量信号（RMS < threshold）应判定为非语音。"""
        chunk = struct.pack("<100h", *([100] * 100))
        assert handler.is_voice(chunk) is False

    def test_threshold_boundary_is_voice(self) -> None:
        """能量恰好等于阈值时应判定为语音（RMS >= threshold）。"""
        handler = InterruptHandler(energy_threshold=500.0)
        chunk = struct.pack("<100h", *([500] * 100))
        assert handler.is_voice(chunk) is True

    def test_just_below_threshold_is_not_voice(self) -> None:
        """能量略低于阈值应判定为非语音。"""
        handler = InterruptHandler(energy_threshold=500.0)
        chunk = struct.pack("<100h", *([499] * 100))
        assert handler.is_voice(chunk) is False

    def test_empty_chunk_is_not_voice(self, handler: InterruptHandler) -> None:
        """空数据块应判定为非语音。"""
        assert handler.is_voice(b"") is False

    def test_single_byte_is_not_voice(self, handler: InterruptHandler) -> None:
        """不足一个采样的数据应判定为非语音。"""
        assert handler.is_voice(b"\x00") is False

    def test_custom_energy_threshold(self) -> None:
        """自定义能量阈值应生效。"""
        handler = InterruptHandler(energy_threshold=100.0)
        # RMS = 200, threshold = 100 → voice
        chunk = struct.pack("<50h", *([200] * 50))
        assert handler.is_voice(chunk) is True

        # RMS = 50, threshold = 100 → not voice
        chunk = struct.pack("<50h", *([50] * 50))
        assert handler.is_voice(chunk) is False

    def test_inverse_of_detect_silence(self) -> None:
        """is_voice 应与 AudioRecorder.detect_silence 互为反逻辑。"""
        from client.audio_recorder import AudioRecorder

        recorder = AudioRecorder(energy_threshold=500.0)
        handler = InterruptHandler(energy_threshold=500.0)

        for value in [0, 100, 499, 500, 501, 1000, 20000]:
            chunk = struct.pack("<50h", *([value] * 50))
            assert handler.is_voice(chunk) != recorder.detect_silence(chunk)


# ── on_interrupt 回调注册测试 ────────────────────────────────────


class TestOnInterrupt:
    def test_register_callback(self, handler: InterruptHandler) -> None:
        """注册的回调应被保存。"""
        called = []
        handler.on_interrupt(lambda: called.append(True))
        assert len(handler._callbacks) == 1

    def test_multiple_callbacks(self, handler: InterruptHandler) -> None:
        """支持注册多个回调。"""
        handler.on_interrupt(lambda: None)
        handler.on_interrupt(lambda: None)
        assert len(handler._callbacks) == 2
