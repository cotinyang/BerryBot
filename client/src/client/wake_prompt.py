"""唤醒后智能提示音逻辑。

唤醒词检测后，短暂监听麦克风判断用户是否已在说话：
- 有后续语音 → 跳过提示音，直接开始录音
- 无后续语音 → 播放预制提示音（"我在"）
"""

import logging
import sys

from client.audio_backend import create_pyaudio, open_input_stream
from client.audio_player import AudioPlayer
from client.config import ClientConfig
from client.interrupt_handler import InterruptHandler

logger = logging.getLogger(__name__)

# 监听窗口的音频参数（与 InterruptHandler 一致）
_SAMPLE_RATE = 16000
_CHANNELS = 1
_SAMPLE_WIDTH = 2  # 16-bit
_CHUNK_SIZE = 1024


def _get_pyaudio():  # type: ignore[no-untyped-def]
    """延迟导入 pyaudio，便于测试 mock。"""
    if "pyaudio" in sys.modules:
        return sys.modules["pyaudio"]
    try:
        import pyaudio  # type: ignore[import-untyped]
        return pyaudio
    except ImportError as exc:
        raise RuntimeError(
            "pyaudio is required for wake prompt detection. "
            "Install it with: pip install pyaudio"
        ) from exc


def _read_prompt_file(path: str) -> bytes:
    """读取提示音文件内容。"""
    with open(path, "rb") as f:
        return f.read()


async def handle_wake_prompt(
    interrupt_handler: InterruptHandler,
    audio_player: AudioPlayer,
    config: ClientConfig,
) -> bool:
    """唤醒后智能提示音处理。

    在唤醒词检测后，打开麦克风监听约 ``config.wake_prompt_delay`` 秒，
    利用 ``interrupt_handler.is_voice`` 判断用户是否已在说话。

    Args:
        interrupt_handler: 用于 ``is_voice`` 检测的打断处理器。
        audio_player: 用于播放提示音的播放器。
        config: 客户端配置，提供 ``wake_prompt_delay`` 和
            ``wake_prompt_audio_path``。

    Returns:
        ``True`` 表示检测到后续语音（跳过提示音，应直接录音）；
        ``False`` 表示未检测到语音（已播放提示音）。
    """
    pyaudio = _get_pyaudio()

    pa = create_pyaudio(pyaudio)
    stream = None
    try:
        stream = open_input_stream(
            pa,
            format=pyaudio.paInt16,
            channels=_CHANNELS,
            rate=_SAMPLE_RATE,
            input=True,
            frames_per_buffer=_CHUNK_SIZE,
        )

        # 计算需要读取的总帧数
        total_frames = int(_SAMPLE_RATE * config.wake_prompt_delay)
        frames_read = 0

        while frames_read < total_frames:
            to_read = min(_CHUNK_SIZE, total_frames - frames_read)
            data = stream.read(to_read, exception_on_overflow=False)
            frames_read += to_read

            if interrupt_handler.is_voice(data):
                logger.info("唤醒后检测到后续语音，跳过提示音")
                return True

    finally:
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except OSError:
                pass
        pa.terminate()

    # 窗口期内未检测到语音，播放提示音
    logger.info("唤醒后未检测到后续语音，播放提示音")
    try:
        prompt_data = _read_prompt_file(config.wake_prompt_audio_path)
        await audio_player.play(prompt_data)
    except Exception:
        logger.exception("播放唤醒提示音失败")

    return False
