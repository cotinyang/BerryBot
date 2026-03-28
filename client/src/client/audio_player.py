"""客户端播放器：使用系统音频播放器播放 MP3 音频数据。

在树莓派上通过 subprocess 调用 mpg123/ffplay/aplay 播放音频，
使用 asyncio.subprocess 实现非阻塞、可取消的播放。
"""

import asyncio
import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# 按优先级排列的播放器命令，每个元素为 (命令名, 参数模板)
# {file} 会被替换为临时文件路径
_PLAYER_COMMANDS: list[tuple[str, list[str]]] = [
    ("mpg123", ["mpg123", "-q", "{file}"]),
    ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "{file}"]),
    ("aplay", ["aplay", "-q", "{file}"]),
]


class AudioPlayer:
    """音频播放器，通过系统命令播放 MP3 数据。

    播放流程：将音频字节写入临时文件 → 调用系统播放器 → 播放完成后清理临时文件。
    支持通过 stop() 取消正在进行的播放。
    """

    def __init__(self) -> None:
        self._playing = False
        self._process: asyncio.subprocess.Process | None = None
        self._temp_file: Path | None = None
        self._on_complete_callback: Callable[[], None] | None = None

    @property
    def is_playing(self) -> bool:
        """当前是否正在播放。"""
        return self._playing

    def on_complete(self, callback: Callable[[], None]) -> None:
        """注册播放完成回调。"""
        self._on_complete_callback = callback

    async def play(self, audio_data: bytes) -> None:
        """播放 MP3 音频数据。

        将数据写入临时文件，通过系统播放器播放，播放完成后清理并触发回调。
        可通过 stop() 取消播放。

        Args:
            audio_data: MP3 格式的音频字节数据。

        Raises:
            RuntimeError: 找不到可用的系统音频播放器。
        """
        if self._playing:
            await self.stop()

        # 写入临时文件
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        try:
            tmp.write(audio_data)
            tmp.flush()
            tmp.close()
            self._temp_file = Path(tmp.name)
        except Exception:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
            raise

        self._playing = True
        cancelled = False
        try:
            cmd = self._build_command(str(self._temp_file))
            logger.info("开始播放: %d bytes, cmd=%s", len(audio_data), cmd[0])
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await self._process.wait()
        except asyncio.CancelledError:
            cancelled = True
            await self._kill_process()
            raise
        except FileNotFoundError:
            raise RuntimeError(
                "No audio player found. Install mpg123, ffplay, or aplay."
            )
        except Exception:
            logger.exception("Audio playback error")
            raise
        finally:
            self._playing = False
            self._process = None
            self._cleanup_temp()
            if not cancelled and self._on_complete_callback is not None:
                try:
                    self._on_complete_callback()
                except Exception:
                    logger.exception("Error in on_complete callback")

    async def stop(self) -> None:
        """停止当前播放。"""
        logger.info("停止播放")
        if self._process is not None:
            await self._kill_process()
        self._playing = False
        self._process = None
        self._cleanup_temp()

    async def _kill_process(self) -> None:
        """终止播放子进程。"""
        if self._process is None:
            return
        try:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass  # 进程已退出

    def _cleanup_temp(self) -> None:
        """清理临时文件。"""
        if self._temp_file is not None:
            self._temp_file.unlink(missing_ok=True)
            self._temp_file = None

    @staticmethod
    def _build_command(file_path: str) -> list[str]:
        """构建播放器命令，按优先级尝试查找可用播放器。

        Args:
            file_path: 音频文件路径。

        Returns:
            播放器命令参数列表。

        Raises:
            RuntimeError: 找不到可用的系统音频播放器。
        """
        import shutil

        for name, template in _PLAYER_COMMANDS:
            if shutil.which(name) is not None:
                return [arg.replace("{file}", file_path) for arg in template]
        raise RuntimeError(
            "No audio player found. Install mpg123, ffplay, or aplay."
        )
