"""AudioRecorder 单元测试：encode_wav 和 detect_silence（纯 Python，无需硬件）。"""

import io
import struct
import wave

import pytest

from client.audio_recorder import AudioRecorder


@pytest.fixture
def recorder() -> AudioRecorder:
    return AudioRecorder(silence_threshold=1.5, sample_rate=16000, energy_threshold=500.0)


# ── encode_wav 测试 ──────────────────────────────────────────────


class TestEncodeWav:
    def test_produces_valid_wav(self, recorder: AudioRecorder) -> None:
        """编码结果应为合法 WAV 文件。"""
        pcm = struct.pack("<4h", 0, 1000, -1000, 32767)
        wav_data = recorder.encode_wav(pcm, 16000)

        with wave.open(io.BytesIO(wav_data), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 4

    def test_roundtrip_preserves_pcm(self, recorder: AudioRecorder) -> None:
        """编码后解码应还原原始 PCM 数据。"""
        pcm = struct.pack("<6h", 0, 100, -100, 32767, -32768, 12345)
        wav_data = recorder.encode_wav(pcm, 16000)

        with wave.open(io.BytesIO(wav_data), "rb") as wf:
            decoded = wf.readframes(wf.getnframes())

        assert decoded == pcm

    def test_empty_pcm(self, recorder: AudioRecorder) -> None:
        """空 PCM 数据应产生有效的零帧 WAV。"""
        wav_data = recorder.encode_wav(b"", 16000)

        with wave.open(io.BytesIO(wav_data), "rb") as wf:
            assert wf.getnframes() == 0
            assert wf.getnchannels() == 1

    def test_different_sample_rates(self, recorder: AudioRecorder) -> None:
        """不同采样率应正确写入 WAV 头。"""
        pcm = struct.pack("<2h", 100, -100)
        for rate in (8000, 16000, 44100, 48000):
            wav_data = recorder.encode_wav(pcm, rate)
            with wave.open(io.BytesIO(wav_data), "rb") as wf:
                assert wf.getframerate() == rate


# ── detect_silence 测试 ──────────────────────────────────────────


class TestDetectSilence:
    def test_silence_detected_for_zeros(self, recorder: AudioRecorder) -> None:
        """全零采样应判定为静音。"""
        chunk = struct.pack("<100h", *([0] * 100))
        assert recorder.detect_silence(chunk) is True

    def test_loud_signal_not_silent(self, recorder: AudioRecorder) -> None:
        """高能量信号不应判定为静音。"""
        chunk = struct.pack("<100h", *([20000] * 100))
        assert recorder.detect_silence(chunk) is False

    def test_low_energy_is_silent(self, recorder: AudioRecorder) -> None:
        """低能量信号（RMS < threshold）应判定为静音。"""
        # RMS of constant 100 = 100, well below default threshold 500
        chunk = struct.pack("<100h", *([100] * 100))
        assert recorder.detect_silence(chunk) is True

    def test_threshold_boundary(self) -> None:
        """能量恰好等于阈值时应判定为静音（严格小于才是静音）。"""
        # RMS = 500 exactly, threshold = 500 → rms < threshold is False
        recorder = AudioRecorder(energy_threshold=500.0)
        chunk = struct.pack("<100h", *([500] * 100))
        assert recorder.detect_silence(chunk) is False

    def test_just_below_threshold(self) -> None:
        """能量略低于阈值应判定为静音。"""
        recorder = AudioRecorder(energy_threshold=500.0)
        chunk = struct.pack("<100h", *([499] * 100))
        assert recorder.detect_silence(chunk) is True

    def test_empty_chunk_is_silent(self, recorder: AudioRecorder) -> None:
        """空数据块应判定为静音。"""
        assert recorder.detect_silence(b"") is True

    def test_single_byte_is_silent(self, recorder: AudioRecorder) -> None:
        """不足一个采样的数据应判定为静音。"""
        assert recorder.detect_silence(b"\x00") is True

    def test_custom_energy_threshold(self) -> None:
        """自定义能量阈值应生效。"""
        recorder = AudioRecorder(energy_threshold=100.0)
        # RMS = 200, threshold = 100 → not silent
        chunk = struct.pack("<50h", *([200] * 50))
        assert recorder.detect_silence(chunk) is False

        # RMS = 50, threshold = 100 → silent
        chunk = struct.pack("<50h", *([50] * 50))
        assert recorder.detect_silence(chunk) is True


# ── 录音停止条件测试 ─────────────────────────────────────────────


class TestStopRecordingCondition:
    def test_stops_after_continuous_silence_when_voice_detected(self) -> None:
        recorder = AudioRecorder(silence_threshold=1.5)
        should_stop = recorder._should_stop_recording(
            voice_detected=True,
            continuous_silence_sec=1.5,
            total_duration_sec=2.0,
        )
        assert should_stop is True

    def test_does_not_stop_on_short_silence_after_voice(self) -> None:
        recorder = AudioRecorder(silence_threshold=1.5)
        should_stop = recorder._should_stop_recording(
            voice_detected=True,
            continuous_silence_sec=0.2,
            total_duration_sec=2.0,
        )
        assert should_stop is False

    def test_stops_after_no_voice_timeout(self) -> None:
        recorder = AudioRecorder(silence_threshold=1.5)
        should_stop = recorder._should_stop_recording(
            voice_detected=False,
            continuous_silence_sec=1.5,
            total_duration_sec=1.5,
        )
        assert should_stop is True

    def test_no_voice_timeout_has_minimum_one_second(self) -> None:
        recorder = AudioRecorder(silence_threshold=0.3)
        should_stop = recorder._should_stop_recording(
            voice_detected=False,
            continuous_silence_sec=0.3,
            total_duration_sec=0.9,
        )
        assert should_stop is False
