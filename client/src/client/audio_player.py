"""客户端播放器：使用系统音频播放器播放 MP3 音频数据。

在树莓派上通过 subprocess 调用 mpg123/ffplay/aplay 播放音频，
使用 asyncio.subprocess 实现非阻塞、可取消的播放。
"""

import asyncio
import logging
import shlex
import tempfile
from collections.abc import AsyncIterator, Callable
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

    def __init__(self, player_command: str = "", output_device: str = "") -> None:
        self._playing = False
        self._process: asyncio.subprocess.Process | None = None
        self._temp_file: Path | None = None
        self._on_complete_callback: Callable[[], None] | None = None
        self._player_command = player_command.strip()
        self._output_device = output_device.strip()

    @property
    def is_playing(self) -> bool:
        """当前是否正在播放。"""
        return self._playing

    def on_complete(self, callback: Callable[[], None]) -> None:
        """注册播放完成回调。"""
        self._on_complete_callback = callback

    async def play_stream(self, chunks: AsyncIterator[bytes], audio_format: str = "mp3") -> None:
        """流式播放音频 chunk。"""
        if self._playing:
            await self.stop()

        self._playing = True
        cancelled = False
        cmd: list[str] = []
        total_bytes = 0
        try:
            cmd = self._build_stream_command(
                self._player_command,
                self._output_device,
                audio_format,
            )
            logger.info(
                "开始流式播放: format=%s, cmd=%s, output_device=%s",
                audio_format,
                cmd[0],
                self._output_device or "default",
            )

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            if self._process.stdin is None:
                raise RuntimeError("Player stdin is not available for streaming")

            async for chunk in chunks:
                if not chunk:
                    continue
                total_bytes += len(chunk)
                self._process.stdin.write(chunk)
                await self._process.stdin.drain()

            try:
                self._process.stdin.close()
            except Exception:
                pass

            wait_result = await self._process.wait()
            if isinstance(wait_result, int):
                return_code = wait_result
            elif isinstance(self._process.returncode, int):
                return_code = self._process.returncode
            else:
                return_code = 0

            stderr_text = ""
            if self._process.stderr is not None:
                stderr_bytes = await self._process.stderr.read()
                if isinstance(stderr_bytes, (bytes, bytearray)):
                    stderr_text = bytes(stderr_bytes).decode(errors="ignore").strip()
                elif stderr_bytes:
                    stderr_text = str(stderr_bytes).strip()

            if return_code != 0:
                logger.error(
                    "流式播放失败: cmd=%s, return_code=%d, stderr=%s",
                    cmd[0],
                    return_code,
                    self._truncate_log(stderr_text),
                )
                raise RuntimeError(
                    f"Audio streaming playback failed with code {return_code}: "
                    f"{self._truncate_log(stderr_text)}"
                )

            if stderr_text:
                logger.warning(
                    "流式播放 stderr 输出: cmd=%s, stderr=%s",
                    cmd[0],
                    self._truncate_log(stderr_text),
                )

            logger.info("流式播放完成: cmd=%s, size=%d bytes", cmd[0], total_bytes)
        except asyncio.CancelledError:
            cancelled = True
            await self._kill_process()
            raise
        except FileNotFoundError:
            raise RuntimeError(
                "No audio player found. Install mpg123, ffplay, or aplay."
            )
        except Exception:
            logger.exception("Audio streaming playback error")
            raise
        finally:
            self._playing = False
            self._process = None
            if not cancelled and self._on_complete_callback is not None:
                try:
                    self._on_complete_callback()
                except Exception:
                    logger.exception("Error in on_complete callback")

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

        # 自动识别音频格式，避免 WAV 被当作 MP3 播放
        audio_format = self._detect_audio_format(audio_data)

        # 写入临时文件
        tmp = tempfile.NamedTemporaryFile(suffix=f".{audio_format}", delete=False)
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
        cmd: list[str] = []
        try:
            cmd = self._build_command(
                str(self._temp_file),
                self._player_command,
                self._output_device,
                audio_format,
            )
            logger.info(
                "开始播放: %d bytes, format=%s, cmd=%s, output_device=%s",
                len(audio_data),
                audio_format,
                cmd[0],
                self._output_device or "default",
            )
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            self._process = proc
            wait_result = await proc.wait()
            if isinstance(wait_result, int):
                return_code = wait_result
            elif isinstance(proc.returncode, int):
                return_code = proc.returncode
            else:
                return_code = 0
            stderr_text = ""
            if proc.stderr is not None:
                stderr_bytes = await proc.stderr.read()
                if isinstance(stderr_bytes, (bytes, bytearray)):
                    stderr_text = bytes(stderr_bytes).decode(errors="ignore").strip()
                elif stderr_bytes:
                    stderr_text = str(stderr_bytes).strip()

            if return_code != 0:
                logger.error(
                    "播放失败: cmd=%s, return_code=%d, stderr=%s",
                    cmd[0],
                    return_code,
                    self._truncate_log(stderr_text),
                )
                raise RuntimeError(
                    f"Audio playback failed with code {return_code}: "
                    f"{self._truncate_log(stderr_text)}"
                )

            if stderr_text:
                logger.warning(
                    "播放 stderr 输出: cmd=%s, stderr=%s",
                    cmd[0],
                    self._truncate_log(stderr_text),
                )

            logger.info("播放完成: cmd=%s", cmd[0])
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
    def _truncate_log(text: str, max_len: int = 240) -> str:
        """截断日志文本，避免刷屏。"""
        if len(text) <= max_len:
            return text
        return f"{text[:max_len]}..."

    @staticmethod
    def _build_command(
        file_path: str,
        player_command: str = "",
        output_device: str = "",
        audio_format: str = "mp3",
    ) -> list[str]:
        """构建播放器命令，按优先级尝试查找可用播放器。

        Args:
            file_path: 音频文件路径。

        Returns:
            播放器命令参数列表。

        Raises:
            RuntimeError: 找不到可用的系统音频播放器。
        """
        import shutil

        if player_command:
            cmd = shlex.split(player_command)
            if not cmd:
                raise RuntimeError("AUDIO_PLAYER_COMMAND is empty")
            if any("{file}" in part for part in cmd):
                return [part.replace("{file}", file_path) for part in cmd]
            return [*cmd, file_path]

        preferred_players = ["mpg123", "ffplay", "aplay"]
        if audio_format == "wav":
            preferred_players = ["aplay", "ffplay", "mpg123"]

        command_map = {name: template for name, template in _PLAYER_COMMANDS}

        for name in preferred_players:
            template = command_map[name]
            if shutil.which(name) is not None:
                cmd = [arg.replace("{file}", file_path) for arg in template]
                if output_device:
                    if name == "mpg123":
                        cmd = ["mpg123", "-a", output_device, "-q", file_path]
                    elif name == "aplay":
                        cmd = ["aplay", "-D", output_device, "-q", file_path]
                return cmd
        raise RuntimeError(
            "No audio player found. Install mpg123, ffplay, or aplay."
        )

    @staticmethod
    def _build_stream_command(
        player_command: str = "",
        output_device: str = "",
        audio_format: str = "mp3",
    ) -> list[str]:
        """构建流式播放命令，播放器从 stdin 读取音频数据。"""
        import shutil

        if player_command:
            cmd = shlex.split(player_command)
            if not cmd:
                raise RuntimeError("AUDIO_PLAYER_COMMAND is empty")
            # 若用户沿用 {file} 占位符配置，流式模式下自动替换为 stdin
            cmd = [part.replace("{file}", "-") for part in cmd]
            if "-" not in cmd:
                cmd.append("-")
            return cmd

        preferred_players = ["mpg123", "ffplay", "aplay"]
        if audio_format == "wav":
            preferred_players = ["aplay", "ffplay", "mpg123"]

        for name in preferred_players:
            if shutil.which(name) is None:
                continue
            if name == "mpg123":
                if output_device:
                    return ["mpg123", "-a", output_device, "-q", "-"]
                return ["mpg123", "-q", "-"]
            if name == "ffplay":
                return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"]
            if name == "aplay":
                if output_device:
                    return ["aplay", "-D", output_device, "-q", "-"]
                return ["aplay", "-q", "-"]

        raise RuntimeError(
            "No audio player found. Install mpg123, ffplay, or aplay."
        )

    @staticmethod
    def _detect_audio_format(audio_data: bytes) -> str:
        """检测音频格式，仅区分当前链路需要的 mp3 / wav。"""
        if len(audio_data) >= 12 and audio_data[:4] == b"RIFF" and audio_data[8:12] == b"WAVE":
            return "wav"
        if audio_data[:3] == b"ID3" or (len(audio_data) >= 2 and audio_data[0] == 0xFF and (audio_data[1] & 0xE0) == 0xE0):
            return "mp3"
        # 默认按 mp3 处理，兼容原有服务端返回格式
        return "mp3"
