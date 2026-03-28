"""客户端录音器：音频采集、WAV 编码、静音检测。"""

import asyncio
import io
import logging
import struct
import wave

logger = logging.getLogger(__name__)


class AudioRecorder:
    """录音器，使用 pyaudio 进行音频采集。

    pyaudio 为可选依赖（需要系统 portaudio），仅在 start_recording 时延迟导入。
    encode_wav 和 detect_silence 为纯 Python 实现，无需硬件依赖。
    """

    def __init__(
        self,
        silence_threshold: float = 1.5,
        sample_rate: int = 16000,
        energy_threshold: float = 500.0,
    ) -> None:
        self.silence_threshold = silence_threshold
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self._channels = 1
        self._sample_width = 2  # 16-bit
        self._chunk_size = 1024
        self._recording = False
        self._frames: list[bytes] = []
        self._pa: object | None = None
        self._stream: object | None = None

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
        self._pa = pyaudio.PyAudio()
        logger.info("开始录音: sample_rate=%d, channels=%d", self.sample_rate, self._channels)
        self._stream = self._pa.open(  # type: ignore[union-attr]
            format=pyaudio.paInt16,
            channels=self._channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self._chunk_size,
        )

        while self._recording:
            data = self._stream.read(self._chunk_size, exception_on_overflow=False)  # type: ignore[union-attr]
            self._frames.append(data)
            if self.detect_silence(data):
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
        return self.encode_wav(raw_audio, self.sample_rate)

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
        if len(audio_chunk) < self._sample_width:
            return True

        # 确保数据长度是 sample_width 的整数倍
        num_samples = len(audio_chunk) // self._sample_width
        if num_samples == 0:
            return True

        # 解析 16-bit little-endian 有符号整数
        samples = struct.unpack(f"<{num_samples}h", audio_chunk[: num_samples * self._sample_width])

        # 计算 RMS 能量
        sum_squares = sum(s * s for s in samples)
        rms = (sum_squares / num_samples) ** 0.5

        return rms < self.energy_threshold
