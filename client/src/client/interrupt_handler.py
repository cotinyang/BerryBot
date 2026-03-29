"""客户端打断处理器：播放期间监听用户语音以触发打断。"""

import asyncio
import logging
import struct
from collections.abc import Callable

from client.audio_backend import create_pyaudio, open_input_stream

logger = logging.getLogger(__name__)


class InterruptHandler:
    """打断处理器，在播放状态下持续监听麦克风以检测用户语音。

    pyaudio 为可选依赖（需要系统 portaudio），仅在 start_monitoring 时延迟导入。
    is_voice 为纯 Python 实现，无需硬件依赖。
    """

    def __init__(
        self,
        energy_threshold: float = 500.0,
        grace_period: float = 0.8,
        min_voice_duration: float = 0.3,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.grace_period = grace_period
        self.min_voice_duration = min_voice_duration
        self._monitoring = False
        self._callbacks: list[Callable[[], None]] = []
        self._sample_rate = 16000
        self._channels = 1
        self._sample_width = 2  # 16-bit
        self._chunk_size = 1024
        self._pa: object | None = None
        self._stream: object | None = None
        self._level_log_interval_sec = 2.0

    def on_interrupt(self, callback: Callable[[], None]) -> None:
        """注册打断回调。检测到用户语音时调用。"""
        self._callbacks.append(callback)

    def is_voice(self, audio_chunk: bytes) -> bool:
        """区分环境噪音和用户语音（基于 RMS 能量阈值）。

        计算音频块中所有 16-bit 采样的均方根 (RMS) 能量，
        若 RMS 大于等于 energy_threshold 则判定为语音。

        与 AudioRecorder.detect_silence 逻辑相反：
        detect_silence 返回 True 当 RMS < threshold（静音），
        is_voice 返回 True 当 RMS >= threshold（语音）。

        Args:
            audio_chunk: 16-bit 单声道 PCM 数据块。

        Returns:
            True 表示检测到用户语音，False 表示环境噪音。
        """
        if len(audio_chunk) < self._sample_width:
            return False

        num_samples = len(audio_chunk) // self._sample_width
        if num_samples == 0:
            return False

        samples = struct.unpack(
            f"<{num_samples}h", audio_chunk[: num_samples * self._sample_width]
        )

        sum_squares = sum(s * s for s in samples)
        rms = (sum_squares / num_samples) ** 0.5

        return rms >= self.energy_threshold

    async def start_monitoring(self) -> None:
        """开始监听麦克风以检测语音打断。延迟导入 pyaudio。"""
        try:
            import pyaudio  # type: ignore[import-untyped]
        except ImportError as e:
            raise RuntimeError(
                "pyaudio is required for interrupt monitoring. "
                "Install it with: pip install pyaudio"
            ) from e

        self._monitoring = True
        self._pa = create_pyaudio(pyaudio)
        logger.info(
            "开始打断监听: threshold=%.1f, grace=%.1fs, min_voice=%.1fs",
            self.energy_threshold,
            self.grace_period,
            self.min_voice_duration,
        )
        self._stream = open_input_stream(
            self._pa,
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self._sample_rate,
            input=True,
            frames_per_buffer=self._chunk_size,
        )

        chunk_duration_sec = self._chunk_size / self._sample_rate
        elapsed_sec = 0.0
        consecutive_voice_sec = 0.0
        next_level_log_sec = self._level_log_interval_sec

        while self._monitoring:
            data = self._stream.read(self._chunk_size, exception_on_overflow=False)  # type: ignore[union-attr]
            rms = self._compute_rms(data)
            peak = self._compute_peak(data)
            over_threshold = rms >= self.energy_threshold

            elapsed_sec += chunk_duration_sec

            if elapsed_sec < self.grace_period:
                consecutive_voice_sec = 0.0
            elif over_threshold:
                consecutive_voice_sec += chunk_duration_sec
            else:
                consecutive_voice_sec = 0.0

            if elapsed_sec >= next_level_log_sec:
                logger.info(
                    "打断电平: rms=%.1f, peak=%d, threshold=%.1f, over_threshold=%s, elapsed=%.1fs, consecutive_voice=%.1fs",
                    rms,
                    peak,
                    self.energy_threshold,
                    over_threshold,
                    elapsed_sec,
                    consecutive_voice_sec,
                )
                next_level_log_sec += self._level_log_interval_sec

            if (
                elapsed_sec >= self.grace_period
                and consecutive_voice_sec >= self.min_voice_duration
            ):
                logger.info(
                    "打断监听: 检测到用户语音，触发打断 (rms=%.1f, peak=%d, consecutive_voice=%.1fs)",
                    rms,
                    peak,
                    consecutive_voice_sec,
                )
                for cb in self._callbacks:
                    cb()
                break
            await asyncio.sleep(0)

    async def stop_monitoring(self) -> None:
        """停止监听。"""
        self._monitoring = False

        if self._stream is not None:
            self._stream.stop_stream()  # type: ignore[union-attr]
            self._stream.close()  # type: ignore[union-attr]
            self._stream = None

        if self._pa is not None:
            self._pa.terminate()  # type: ignore[union-attr]
            self._pa = None

    def _compute_rms(self, audio_chunk: bytes) -> float:
        """计算音频块的 RMS 能量。"""
        if len(audio_chunk) < self._sample_width:
            return 0.0

        num_samples = len(audio_chunk) // self._sample_width
        if num_samples == 0:
            return 0.0

        samples = struct.unpack(
            f"<{num_samples}h", audio_chunk[: num_samples * self._sample_width]
        )
        sum_squares = sum(sample * sample for sample in samples)
        return (sum_squares / num_samples) ** 0.5

    def _compute_peak(self, audio_chunk: bytes) -> int:
        """计算音频块峰值振幅。"""
        if len(audio_chunk) < self._sample_width:
            return 0

        num_samples = len(audio_chunk) // self._sample_width
        if num_samples == 0:
            return 0

        samples = struct.unpack(
            f"<{num_samples}h", audio_chunk[: num_samples * self._sample_width]
        )
        return max(abs(sample) for sample in samples)
