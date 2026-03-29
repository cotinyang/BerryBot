"""客户端录音器：音频采集、WAV 编码、静音检测。"""

import asyncio
import io
import logging
import struct
import wave

from client.audio_backend import create_pyaudio, open_input_stream

logger = logging.getLogger(__name__)


class AudioRecorder:
    """录音器，使用 pyaudio 进行音频采集。

    pyaudio 为可选依赖（需要系统 portaudio），仅在 start_recording 时延迟导入。
    encode_wav 和 detect_silence 为纯 Python 实现，无需硬件依赖。
    """

    def __init__(
        self,
        silence_threshold: float = 1.5,
        max_recording_duration: float = 10.0,
        sample_rate: int = 16000,
        energy_threshold: float = 500.0,
        enable_gentle_trim: bool = True,
        trim_frame_ms: int = 20,
        trim_min_silence_sec: float = 0.35,
        trim_padding_sec: float = 0.25,
        trim_energy_ratio: float = 0.6,
    ) -> None:
        self.silence_threshold = silence_threshold
        self.max_recording_duration = max_recording_duration
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self._channels = 1
        self._sample_width = 2  # 16-bit
        self._chunk_size = 1024
        self._recording = False
        self._frames: list[bytes] = []
        self._pa: object | None = None
        self._stream: object | None = None
        self._level_log_interval_sec = 2.0
        self._trim_enabled = enable_gentle_trim
        self._trim_frame_ms = trim_frame_ms
        self._trim_min_silence_sec = trim_min_silence_sec
        self._trim_padding_sec = trim_padding_sec
        self._trim_energy_ratio = trim_energy_ratio

    def _should_stop_recording(
        self,
        *,
        voice_detected: bool,
        continuous_silence_sec: float,
        total_duration_sec: float,
    ) -> bool:
        """判断是否应停止录音。

        规则：
        - 已检测到语音后，连续静音达到阈值则停止。
        - 若一直未检测到语音，超过兜底时长后停止，避免无限录音。
        """
        if voice_detected and continuous_silence_sec >= self.silence_threshold:
            return True

        if total_duration_sec >= self.max_recording_duration:
            return True

        # 无语音兜底：至少等待 1 秒，且不短于 silence_threshold
        no_voice_timeout = max(self.silence_threshold, 1.0)
        if (not voice_detected) and total_duration_sec >= no_voice_timeout:
            return True

        return False

    async def start_recording(self) -> None:
        """开始录音。延迟导入 pyaudio，打开音频流并持续采集。"""
        try:
            import pyaudio  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "pyaudio is required for recording. "
                "Install it with: pip install pyaudio"
            ) from e

        self._frames = []
        self._recording = True
        self._pa = create_pyaudio(pyaudio)
        logger.info("开始录音: sample_rate=%d, channels=%d", self.sample_rate, self._channels)
        self._stream = open_input_stream(
            self._pa,
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self._chunk_size,
        )

        chunk_duration_sec = self._chunk_size / self.sample_rate
        total_duration_sec = 0.0
        continuous_silence_sec = 0.0
        voice_detected = False
        next_level_log_sec = self._level_log_interval_sec

        while self._recording:
            data = self._stream.read(self._chunk_size, exception_on_overflow=False)  # type: ignore[union-attr]
            self._frames.append(data)

            total_duration_sec += chunk_duration_sec
            rms = self._compute_rms(data)
            peak = self._compute_peak(data)
            is_silent = rms < self.energy_threshold
            if is_silent:
                continuous_silence_sec += chunk_duration_sec
            else:
                voice_detected = True
                continuous_silence_sec = 0.0

            if total_duration_sec >= next_level_log_sec:
                logger.info(
                    "录音电平: rms=%.1f, peak=%d, threshold=%.1f, over_threshold=%s, is_silent=%s, duration=%.1fs, silence=%.1fs, voice_detected=%s",
                    rms,
                    peak,
                    self.energy_threshold,
                    not is_silent,
                    is_silent,
                    total_duration_sec,
                    continuous_silence_sec,
                    voice_detected,
                )
                next_level_log_sec += self._level_log_interval_sec

            if self._should_stop_recording(
                voice_detected=voice_detected,
                continuous_silence_sec=continuous_silence_sec,
                total_duration_sec=total_duration_sec,
            ):
                break
            await asyncio.sleep(0)

    async def stop_recording(self) -> bytes:
        """停止录音，返回 WAV 编码的音频数据。"""
        self._recording = False

        if self._stream is not None:
            self._stream.stop_stream()  # type: ignore[union-attr]
            self._stream.close()  # type: ignore[union-attr]
            self._stream = None

        if self._pa is not None:
            self._pa.terminate()  # type: ignore[union-attr]
            self._pa = None

        raw_audio = b"".join(self._frames)
        self._frames = []
        logger.info("录音结束: %d bytes raw PCM", len(raw_audio))
        trimmed_audio = self._gentle_trim_silence(raw_audio)
        return self.encode_wav(trimmed_audio, self.sample_rate)

    def encode_wav(self, raw_audio: bytes, sample_rate: int) -> bytes:
        """将原始 PCM 音频数据编码为 WAV 格式。

        Args:
            raw_audio: 16-bit 单声道 PCM 数据。
            sample_rate: 采样率。

        Returns:
            WAV 格式的字节数据。
        """
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self._channels)
            wf.setsampwidth(self._sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(raw_audio)
        return buf.getvalue()

    def detect_silence(self, audio_chunk: bytes) -> bool:
        """检测音频块是否为静音（基于能量阈值）。

        计算音频块中所有 16-bit 采样的均方根 (RMS) 能量，
        若 RMS 低于 energy_threshold 则判定为静音。

        Args:
            audio_chunk: 16-bit 单声道 PCM 数据块。

        Returns:
            True 表示静音，False 表示有声音。
        """
        return self._compute_rms(audio_chunk) < self.energy_threshold

    def _compute_rms(self, audio_chunk: bytes) -> float:
        """计算音频块的 RMS 能量。"""
        if len(audio_chunk) < self._sample_width:
            return 0.0

        # 确保数据长度是 sample_width 的整数倍
        num_samples = len(audio_chunk) // self._sample_width
        if num_samples == 0:
            return 0.0

        # 解析 16-bit little-endian 有符号整数
        samples = struct.unpack(f"<{num_samples}h", audio_chunk[: num_samples * self._sample_width])

        # 计算 RMS 能量
        sum_squares = sum(s * s for s in samples)
        return (sum_squares / num_samples) ** 0.5

    def _compute_peak(self, audio_chunk: bytes) -> int:
        """计算音频块峰值振幅。"""
        if len(audio_chunk) < self._sample_width:
            return 0

        num_samples = len(audio_chunk) // self._sample_width
        if num_samples == 0:
            return 0

        samples = struct.unpack(f"<{num_samples}h", audio_chunk[: num_samples * self._sample_width])
        return max(abs(sample) for sample in samples)

    def _gentle_trim_silence(self, raw_audio: bytes) -> bytes:
        """温和裁剪首尾静音，保留前后缓冲，避免切碎语音。"""
        if not self._trim_enabled or not raw_audio:
            return raw_audio

        bytes_per_second = self.sample_rate * self._channels * self._sample_width
        frame_bytes = (bytes_per_second * self._trim_frame_ms) // 1000
        if frame_bytes <= 0 or len(raw_audio) <= frame_bytes:
            return raw_audio

        frame_count = len(raw_audio) // frame_bytes
        if frame_count == 0:
            return raw_audio

        rms_threshold = self.energy_threshold * self._trim_energy_ratio
        frame_is_silent: list[bool] = []
        for idx in range(frame_count):
            start = idx * frame_bytes
            end = start + frame_bytes
            frame = raw_audio[start:end]
            frame_is_silent.append(self._compute_rms(frame) < rms_threshold)

        first_voice_idx = -1
        last_voice_idx = -1
        for idx, is_silent in enumerate(frame_is_silent):
            if not is_silent:
                first_voice_idx = idx
                break
        for idx in range(frame_count - 1, -1, -1):
            if not frame_is_silent[idx]:
                last_voice_idx = idx
                break

        if first_voice_idx < 0 or last_voice_idx < 0:
            return raw_audio

        frame_sec = self._trim_frame_ms / 1000.0
        leading_silence_sec = first_voice_idx * frame_sec
        trailing_silence_sec = (frame_count - 1 - last_voice_idx) * frame_sec

        pad_frames = max(1, int(self._trim_padding_sec / frame_sec))
        start_idx = 0
        end_idx = frame_count

        if leading_silence_sec >= self._trim_min_silence_sec:
            start_idx = max(0, first_voice_idx - pad_frames)
        if trailing_silence_sec >= self._trim_min_silence_sec:
            end_idx = min(frame_count, last_voice_idx + 1 + pad_frames)

        if start_idx == 0 and end_idx == frame_count:
            return raw_audio

        trimmed = raw_audio[start_idx * frame_bytes:end_idx * frame_bytes]

        min_kept_sec = 0.4
        if len(trimmed) < int(bytes_per_second * min_kept_sec):
            return raw_audio

        logger.info(
            "温和静音裁剪: raw=%.2fs -> trimmed=%.2fs (lead=%.2fs, tail=%.2fs, pad=%.2fs)",
            len(raw_audio) / bytes_per_second,
            len(trimmed) / bytes_per_second,
            leading_silence_sec,
            trailing_silence_sec,
            self._trim_padding_sec,
        )
        return trimmed
