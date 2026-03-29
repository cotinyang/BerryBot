"""客户端主控流程：启动、初始化组件、串联完整交互循环。"""

import argparse
import asyncio
import logging
import signal

from client.audio_backend import create_pyaudio, open_input_stream
from client.audio_player import AudioPlayer
from client.audio_recorder import AudioRecorder
from client.config import ClientConfig
from client.interrupt_handler import InterruptHandler
from client.state_machine import ClientState, StateMachine
from client.wake_prompt import handle_wake_prompt
from client.wake_word import create_wake_word_detector
from client.ws_client import WebSocketClient

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> ClientConfig:
    """解析命令行参数并返回 ClientConfig。"""
    parser = argparse.ArgumentParser(description="语音助手客户端")
    parser.add_argument(
        "--server-url",
        required=True,
        help="WebSocket 服务端地址，例如 wss://your-domain.com:8765",
    )
    parser.add_argument(
        "--auth-token",
        default="",
        help="预共享认证 token",
    )
    parser.add_argument(
        "--wake-word-engine",
        default="sherpa_onnx",
        choices=["porcupine", "sherpa_onnx"],
        help="唤醒词引擎（默认: sherpa_onnx）",
    )
    parser.add_argument(
        "--wake-word-access-key",
        default="",
        help="Porcupine 唤醒词引擎访问密钥（仅 porcupine 引擎需要）",
    )
    parser.add_argument(
        "--wake-word-keyword-path",
        default="",
        help="Porcupine 唤醒词模型文件路径（仅 porcupine 引擎需要）",
    )
    parser.add_argument(
        "--wake-word-keywords",
        default="小艺小艺",
        help="唤醒词列表，逗号分隔（仅 sherpa_onnx 引擎，默认: 小艺小艺）",
    )
    parser.add_argument(
        "--wake-word-model-path",
        default="",
        help="sherpa-onnx 关键词检测模型路径（留空自动下载）",
    )
    parser.add_argument(
        "--wake-prompt-audio-path",
        default="assets/wo_zai.mp3",
        help="唤醒提示音文件路径（默认: assets/wo_zai.mp3）",
    )
    parser.add_argument(
        "--wake-prompt-delay",
        type=float,
        default=0.3,
        help="唤醒后等待后续语音的窗口期秒数（默认: 0.3）",
    )
    parser.add_argument(
        "--silence-threshold",
        type=float,
        default=1.5,
        help="静音检测阈值秒数（默认: 1.5）",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=16000,
        help="音频采样率（默认: 16000）",
    )
    parser.add_argument(
        "--energy-threshold",
        type=float,
        default=500.0,
        help="语音能量阈值（默认: 500.0）",
    )
    parser.add_argument(
        "--reconnect-interval",
        type=float,
        default=5.0,
        help="重连间隔秒数（默认: 5.0）",
    )
    parser.add_argument(
        "--max-reconnect-retries",
        type=int,
        default=3,
        help="最大重连次数（默认: 3）",
    )
    parser.add_argument(
        "--session-timeout",
        type=float,
        default=5.0,
        help="连续对话超时秒数（默认: 5.0）",
    )
    parser.add_argument(
        "--session-end-audio-path",
        default="assets/end.wav",
        help="会话结束提示音文件路径（默认: assets/end.wav）",
    )
    parser.add_argument(
        "--audio-player-command",
        default="",
        help="自定义音频播放命令，支持 {file} 占位符",
    )
    parser.add_argument(
        "--audio-output-device",
        default="",
        help="音频输出设备名称（例如 bluealsa）",
    )

    args = parser.parse_args(argv)
    return ClientConfig(
        server_url=args.server_url,
        wake_word_engine=args.wake_word_engine,
        wake_word_access_key=args.wake_word_access_key,
        wake_word_keyword_path=args.wake_word_keyword_path,
        wake_word_keywords=args.wake_word_keywords,
        wake_word_model_path=args.wake_word_model_path,
        auth_token=args.auth_token,
        wake_prompt_audio_path=args.wake_prompt_audio_path,
        wake_prompt_delay=args.wake_prompt_delay,
        silence_threshold=args.silence_threshold,
        sample_rate=args.sample_rate,
        energy_threshold=args.energy_threshold,
        reconnect_interval=args.reconnect_interval,
        max_reconnect_retries=args.max_reconnect_retries,
        session_timeout=args.session_timeout,
        session_end_audio_path=args.session_end_audio_path,
        audio_player_command=args.audio_player_command,
        audio_output_device=args.audio_output_device,
    )


class VoiceAssistantClient:
    """语音助手客户端主控类，串联所有组件完成交互流程。"""

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._running = False
        self._interrupt_task: asyncio.Task[None] | None = None
        self._wake_word_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[object]] = set()

        # 初始化组件
        self._state_machine = StateMachine()
        self._wake_word_detector = create_wake_word_detector(config)
        self._audio_recorder = AudioRecorder(
            silence_threshold=config.silence_threshold,
            sample_rate=config.sample_rate,
            energy_threshold=config.energy_threshold,
        )
        self._audio_player = AudioPlayer(
            player_command=config.audio_player_command,
            output_device=config.audio_output_device,
        )
        self._interrupt_handler = InterruptHandler(
            energy_threshold=config.energy_threshold,
        )
        self._ws_client = WebSocketClient(
            server_url=config.server_url,
            max_retries=config.max_reconnect_retries,
            retry_interval=config.reconnect_interval,
            auth_token=config.auth_token,
        )

        self._register_callbacks()

    @property
    def state_machine(self) -> StateMachine:
        """暴露状态机供测试使用。"""
        return self._state_machine

    def _register_callbacks(self) -> None:
        """注册所有组件回调，串联交互流程。"""
        # 唤醒词检测 → 开始交互
        self._wake_word_detector.on_wake_word(self._on_wake_word)

        # 播放完成 → 返回待机
        self._audio_player.on_complete(self._on_playback_complete)

        # 打断检测 → 停止播放并录音
        self._interrupt_handler.on_interrupt(self._on_interrupt)

        # WebSocket 连接失败 → 离线待机
        self._ws_client.on_connection_failed(self._on_connection_failed)

        # WebSocket 重连成功 → 恢复待机
        self._ws_client.on_reconnect(self._on_reconnect)

    # ── 回调处理 ──────────────────────────────────────────

    def _on_wake_word(self) -> None:
        """唤醒词检测到后触发。"""
        if self._state_machine.state != ClientState.STANDBY:
            return
        logger.info("唤醒词检测到，启动交互流程")
        self._track_task(asyncio.create_task(self._handle_interaction()))

    def _on_playback_complete(self) -> None:
        """播放完成回调 → 进入连续对话监听状态。"""
        if self._state_machine.state == ClientState.PLAYING:
            logger.info("播放完成，进入连续对话监听")
            self._state_machine.transition(ClientState.LISTENING)
            self._track_task(asyncio.create_task(self._handle_listening()))

    def _on_interrupt(self) -> None:
        """语音打断回调。"""
        if self._state_machine.state == ClientState.PLAYING:
            if self._interrupt_task is not None and not self._interrupt_task.done():
                logger.info("打断处理中，忽略重复打断事件")
                return
            logger.info("检测到语音打断")
            self._interrupt_task = asyncio.create_task(self._handle_interrupt())
            self._track_task(self._interrupt_task)

    def _on_connection_failed(self) -> None:
        """所有重连尝试失败后回调。"""
        logger.warning("连接失败，进入离线待机")
        try:
            self._state_machine.transition(ClientState.OFFLINE_STANDBY)
        except ValueError:
            pass

    def _on_reconnect(self) -> None:
        """重连成功回调。"""
        logger.info("重连成功，恢复待机")
        if self._state_machine.state == ClientState.OFFLINE_STANDBY:
            self._state_machine.transition(ClientState.STANDBY)

    # ── 交互流程 ──────────────────────────────────────────

    async def _handle_interaction(self) -> None:
        """首次唤醒交互：唤醒 → 提示音 → 录音 → 发送 → 等待 → 播放。

        播放完成后由 _on_playback_complete 进入 LISTENING 状态，
        开始连续对话循环。
        """
        try:
            # 1. 暂停唤醒词监听（避免抢占麦克风）
            await self._wake_word_detector.stop_listening()

            # 2. 切换到录音状态
            self._state_machine.transition(ClientState.RECORDING)

            # 3. 智能提示音处理
            await handle_wake_prompt(
                self._interrupt_handler,
                self._audio_player,
                self._config,
            )

            # 4. 录音 → 发送 → 等待 → 播放
            await self._do_record_send_play()

        except ConnectionError as exc:
            logger.error("通信错误: %s", exc)
            await self._end_session()
        except RuntimeError as exc:
            logger.error("服务端错误: %s", exc)
            await self._end_session()
        except Exception:
            logger.exception("交互流程异常")
            await self._end_session()

    async def _handle_listening(self) -> None:
        """连续对话监听：等待用户说话或超时结束会话。

        在 LISTENING 状态下打开麦克风，检测到语音则继续对话，
        超时则播放结束音并回到 STANDBY。
        """
        if self._state_machine.state != ClientState.LISTENING:
            return

        logger.info("连续对话监听中 (超时: %.1fs)", self._config.session_timeout)

        try:
            voice_detected = await self._wait_for_voice(self._config.session_timeout)

            if voice_detected:
                logger.info("连续对话: 检测到用户语音，继续录音")
                self._state_machine.transition(ClientState.RECORDING)
                await self._do_record_send_play()
            else:
                logger.info("连续对话超时，结束会话")
                await self._end_session()

        except Exception:
            logger.exception("连续对话监听异常")
            await self._end_session()

    async def _wait_for_voice(self, timeout: float) -> bool:
        """在指定时间内监听麦克风，检测是否有用户语音。

        Args:
            timeout: 超时时间（秒）。

        Returns:
            True 表示检测到语音，False 表示超时。
        """
        try:
            from client.wake_prompt import _get_pyaudio
            pyaudio = _get_pyaudio()
        except RuntimeError:
            return False

        pa = create_pyaudio(pyaudio)
        stream = None
        try:
            stream = open_input_stream(
                pa,
                format=pyaudio.paInt16,
                channels=1,
                rate=self._config.sample_rate,
                input=True,
                frames_per_buffer=1024,
            )

            chunk_duration = 1024 / self._config.sample_rate
            elapsed = 0.0

            while elapsed < timeout:
                data = stream.read(1024, exception_on_overflow=False)
                if self._interrupt_handler.is_voice(data):
                    return True
                elapsed += chunk_duration
                await asyncio.sleep(0)

            return False
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except OSError:
                    pass
            pa.terminate()

    async def _do_record_send_play(self) -> None:
        """录音 → 发送 → 等待响应 → 播放/执行指令的通用流程。

        调用前状态应为 RECORDING。播放完成后由回调进入 LISTENING。
        如果收到 end_session 指令，直接结束会话。
        """
        # 录音
        await self._audio_recorder.start_recording()
        audio_data = await self._audio_recorder.stop_recording()

        # 发送
        if not self._ws_client.is_connected:
            logger.error("未连接到服务端，无法发送音频")
            await self._end_session()
            return

        await self._ws_client.send_audio(audio_data)
        self._safe_transition(ClientState.WAITING_RESPONSE)
        if self._state_machine.state != ClientState.WAITING_RESPONSE:
            logger.warning(
                "发送后状态不是 waiting，终止本轮处理: %s",
                self._state_machine.state.value,
            )
            return

        # 接收响应（可能是音频或指令）
        response = await self._ws_client.receive_response()

        if response["type"] == "command":
            action = response["action"]
            logger.info("收到服务端指令: %s", action)
            if action == "end_session":
                await self._end_session()
                return
            logger.warning("未知指令: %s，忽略", action)
            await self._end_session()
            return

        if self._state_machine.state != ClientState.WAITING_RESPONSE:
            logger.warning(
                "收到响应时状态已变更为 %s，丢弃本次响应",
                self._state_machine.state.value,
            )
            return

        # 播放音频（播放完成后 _on_playback_complete 会转到 LISTENING）
        self._state_machine.transition(ClientState.PLAYING)

        monitor_task = asyncio.ensure_future(
            self._interrupt_handler.start_monitoring()
        )
        try:
            if response["type"] == "audio_stream":
                await self._audio_player.play_stream(
                    response["stream"],
                    audio_format=response.get("format", "mp3"),
                )
            else:
                response_audio = response["data"]
                await self._audio_player.play(response_audio)
        finally:
            await self._interrupt_handler.stop_monitoring()
            if not monitor_task.done():
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass

    async def _end_session(self) -> None:
        """结束会话：播放结束音 → 回到 STANDBY → 重启唤醒词监听。"""
        # 播放结束音
        try:
            from pathlib import Path
            end_audio_path = Path(self._config.session_end_audio_path)
            if end_audio_path.exists():
                end_audio = end_audio_path.read_bytes()
                await self._audio_player.play(end_audio)
                logger.info("已播放会话结束提示音")
        except Exception:
            logger.warning("播放结束提示音失败")

        # 回到 STANDBY
        self._safe_transition(ClientState.STANDBY)

        # 重启唤醒词监听
        logger.info("确保唤醒词监听任务处于运行状态")
        await self._restart_wake_word()

    async def _handle_interrupt(self) -> None:
        """处理语音打断：停止播放 → 发送 interrupt → 录音 → 继续对话。"""
        try:
            await self._audio_player.stop()
            await self._interrupt_handler.stop_monitoring()

            if self._ws_client.is_connected:
                await self._ws_client.send_interrupt()

            self._state_machine.transition(ClientState.RECORDING)
            await self._do_record_send_play()

        except ConnectionError as exc:
            logger.error("打断后通信错误: %s", exc)
            await self._end_session()
        except Exception:
            logger.exception("打断处理异常")
            await self._end_session()

    def _safe_transition(self, target: ClientState) -> None:
        """安全状态转换，忽略非法转换错误。"""
        try:
            if self._state_machine.state != target:
                self._state_machine.transition(target)
        except ValueError as exc:
            logger.warning("状态转换失败: %s", exc)

    def _track_task(self, task: asyncio.Task[object]) -> asyncio.Task[object]:
        """跟踪后台任务，便于停止时统一清理。"""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _ensure_wake_word_task(self) -> None:
        """确保仅存在一个唤醒词监听后台任务。"""
        if not self._running:
            return
        if self._wake_word_task is not None and not self._wake_word_task.done():
            return
        self._wake_word_task = asyncio.create_task(self._run_wake_word())
        self._track_task(self._wake_word_task)

    # ── 启动与关闭 ────────────────────────────────────────

    async def _restart_wake_word(self) -> None:
        """在需要时重建唤醒词监听后台任务。"""
        self._ensure_wake_word_task()

    async def start(self) -> None:
        """启动客户端：连接服务端并开始唤醒词监听。"""
        self._running = True
        self._stop_event = asyncio.Event()
        logger.info("语音助手客户端启动中...")

        # 连接服务端
        try:
            await self._ws_client.connect()
            logger.info("已连接到服务端: %s", self._config.server_url)
        except ConnectionError:
            logger.warning("初始连接失败，进入离线待机")
            self._state_machine.transition(ClientState.OFFLINE_STANDBY)

        # 启动唤醒词监听（后台任务）
        logger.info("开始唤醒词监听...")
        self._ensure_wake_word_task()

        # 保持事件循环运行，直到 stop() 被调用
        await self._stop_event.wait()

    async def _run_wake_word(self) -> None:
        """运行唤醒词监听，异常时自动重启。"""
        while self._running:
            try:
                await self._wake_word_detector.start_listening()
                # start_listening 正常返回意味着被 stop_listening 停止了，
                # 等待一下再检查是否需要重启（避免忙循环）
                await asyncio.sleep(0.1)
            except Exception:
                logger.exception("唤醒词监听异常")
                if self._running:
                    await asyncio.sleep(1)

    async def stop(self) -> None:
        """优雅关闭客户端，释放所有资源。"""
        logger.info("正在关闭语音助手客户端...")
        self._running = False

        await self._wake_word_detector.stop_listening()
        await self._audio_recorder.stop_recording()
        await self._audio_player.stop()
        await self._interrupt_handler.stop_monitoring()
        await self._ws_client.disconnect()

        current_task = asyncio.current_task()
        pending_tasks = [
            task for task in self._background_tasks
            if task is not current_task and not task.done()
        ]
        for task in pending_tasks:
            task.cancel()
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        self._background_tasks.clear()
        self._wake_word_task = None
        self._interrupt_task = None

        if hasattr(self, '_stop_event'):
            self._stop_event.set()

        logger.info("语音助手客户端已关闭")


def main(argv: list[str] | None = None) -> None:
    """客户端入口函数。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = parse_args(argv)
    client = VoiceAssistantClient(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 注册信号处理实现优雅关闭
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(client.stop()))
        except NotImplementedError:
            # Windows 不支持 add_signal_handler
            pass

    try:
        loop.run_until_complete(client.start())
    except KeyboardInterrupt:
        loop.run_until_complete(client.stop())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
