"""音频后端辅助工具。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os


def _should_suppress_native_audio_logs() -> bool:
    """是否静默底层音频库输出。"""
    value = os.environ.get("BERRYBOT_SUPPRESS_NATIVE_AUDIO_LOGS", "1")
    return value.lower() not in {"0", "false", "no", "off"}


@contextmanager
def suppress_native_audio_stderr() -> Iterator[None]:
    """临时静默 ALSA/JACK 等原生音频后端输出。"""
    if not _should_suppress_native_audio_logs():
        yield
        return

    try:
        stderr_fd = os.dup(2)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        yield
        return

    try:
        os.dup2(devnull_fd, 2)
        yield
    finally:
        os.dup2(stderr_fd, 2)
        os.close(stderr_fd)
        os.close(devnull_fd)


def create_pyaudio(pyaudio_module: object) -> object:
    """创建 PyAudio 实例，并静默原生音频后端日志。"""
    with suppress_native_audio_stderr():
        return pyaudio_module.PyAudio()  # type: ignore[attr-defined]


def open_input_stream(pa: object, **kwargs: object) -> object:
    """打开输入音频流，并静默原生音频后端日志。"""
    with suppress_native_audio_stderr():
        return pa.open(**kwargs)  # type: ignore[union-attr]