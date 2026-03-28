"""客户端主控流程：启动、初始化组件、串联完整交互循环。"""

import argparse
import asyncio
import logging
import signal

from client.audio_player import AudioPlayer
from client.audio_recorder import AudioRecorder
from client.config import ClientConfig
from client.interrupt_handler import InterruptHandler
from client.state_machine import ClientState, StateMachine
from client.wake_prompt import handle_wake_prompt
from client.wake_word import WakeWordDetector
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
        "--wake-word-access-key",
        required=True,
        help="Porcupine 唤醒词引擎访问密钥",
    )
    parser.add_argument(
        "--wake-word-keyword-path",
        required=True,
        help="唤醒词模型文件路径",
    )
    parser.add_argument(
        "--wake-prompt-audio-path",
        default="assets/wo_zai.wav",
        help="唤醒提示音文件路径（默认: assets/wo_zai.wav）",
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

    args = parser.parse_args(argv)
    return ClientConfig(
        server_url=args.server_url,
        wake_word_access_key=args.wake_word_access_key,
        wake_word_keyword_path=args.wake_word_keyword_path,
        auth_token=args.auth_token,
        wake_prompt_audio_path=args.wake_prompt_audio_path,
        wake_prompt_delay=args.wake_prompt_delay,
        silence_threshold=args.silence_threshold,
        sample_rate=args.sample_rate,
        energy_threshold=args.energy_threshold,
        reconnect_interval=args.reconnect_interval,
        max_reconnect_retries=args.max_reconnect_retries,
    )


class VoiceAssistantClient:
    """语音助手客户端主控类，串联所有组件完成交互流程。"""

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self._running = False

        # 初始化组件
        self._state_machine = StateMachine()
        self._wake_word_detector = WakeWordDetector(
            access_key=config.wake_word_access_key,
            keyword_path=config.wake_word_keyword_path,
        )
        self._audio_recorder = AudioRecorder(
            silence_threshold=config.silence_threshold,
            sample_rate=config.sample_rate,
            energy_threshold=config.energy_threshold,
        )
        self._audio_player = AudioPlayer()
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
        asyncio.ensure_future(self._handle_interaction())

    def _on_playback_complete(self) -> None:
        """播放完成回调。"""
        if self._state_machine.state == ClientState.PLAYING:
            logger.info("播放完成，返回待机")
            self._state_machine.transition(ClientState.STANDBY)

    def _on_interrupt(self) -> None:
        """语音打断回调。"""
        if self._state_machine.state == ClientState.PLAYING:
            logger.info("检测到语音打断")
            asyncio.ensure_future(self._handle_interrupt())

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
        """完整交互流程：唤醒 → 提示音 → 录音 → 发送 → 等待 → 播放。"""
        try:
            # 1. 切换到录音状态
            self._state_machine.transition(ClientState.RECORDING)

            # 2. 智能提示音处理（返回值表示是否检测到后续语音）
            await handle_wake_prompt(
                self._interrupt_handler,
                self._audio_player,
                self._config,
            )

            # 3. 录音
            await self._audio_recorder.start_recording()
            audio_data = await self._audio_recorder.stop_recording()

            # 4. 发送音频
            if not self._ws_client.is_connected:
                logger.error("未连接到服务端，无法发送音频")
                self._state_machine.transition(ClientState.STANDBY)
                return

            await self._ws_client.send_audio(audio_data)

            # 5. 切换到等待响应状态
            self._state_machine.transition(ClientState.WAITING_RESPONSE)

            # 6. 接收服务端语音回复
            response_audio = await self._ws_client.receive_audio()

            # 7. 切换到播放状态并播放
            self._state_machine.transition(ClientState.PLAYING)

            # 启动打断监听
            monitor_task = asyncio.ensure_future(
                self._interrupt_handler.start_monitoring()
            )

            try:
                await self._audio_player.play(response_audio)
            finally:
                await self._interrupt_handler.stop_monitoring()
                if not monitor_task.done():
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass

        except ConnectionError as exc:
            logger.error("通信错误: %s", exc)
            self._safe_transition(ClientState.STANDBY)
        except RuntimeError as exc:
            logger.error("服务端错误: %s", exc)
            self._safe_transition(ClientState.STANDBY)
        except Exception:
            logger.exception("交互流程异常")
            self._safe_transition(ClientState.STANDBY)

    async def _handle_interrupt(self) -> None:
        """处理语音打断：停止播放 → 发送 interrupt → 录音。"""
        try:
            # 停止播放
            await self._audio_player.stop()
            await self._interrupt_handler.stop_monitoring()

            # 发送打断通知
            if self._ws_client.is_connected:
                await self._ws_client.send_interrupt()

            # 切换到录音状态
            self._state_machine.transition(ClientState.RECORDING)

            # 开始新一轮录音
            await self._audio_recorder.start_recording()
            audio_data = await self._audio_recorder.stop_recording()

            if not self._ws_client.is_connected:
                logger.error("未连接到服务端，无法发送音频")
                self._state_machine.transition(ClientState.STANDBY)
                return

            await self._ws_client.send_audio(audio_data)
            self._state_machine.transition(ClientState.WAITING_RESPONSE)

            response_audio = await self._ws_client.receive_audio()
            self._state_machine.transition(ClientState.PLAYING)

            monitor_task = asyncio.ensure_future(
                self._interrupt_handler.start_monitoring()
            )
            try:
                await self._audio_player.play(response_audio)
            finally:
                await self._interrupt_handler.stop_monitoring()
                if not monitor_task.done():
                    monitor_task.cancel()
                    try:
                        await monitor_task
                    except asyncio.CancelledError:
                        pass

        except ConnectionError as exc:
            logger.error("打断后通信错误: %s", exc)
            self._safe_transition(ClientState.STANDBY)
        except Exception:
            logger.exception("打断处理异常")
            self._safe_transition(ClientState.STANDBY)

    def _safe_transition(self, target: ClientState) -> None:
        """安全状态转换，忽略非法转换错误。"""
        try:
            if self._state_machine.state != target:
                self._state_machine.transition(target)
        except ValueError as exc:
            logger.warning("状态转换失败: %s", exc)

    # ── 启动与关闭 ────────────────────────────────────────

    async def start(self) -> None:
        """启动客户端：连接服务端并开始唤醒词监听。"""
        self._running = True
        logger.info("语音助手客户端启动中...")

        # 连接服务端
        try:
            await self._ws_client.connect()
            logger.info("已连接到服务端: %s", self._config.server_url)
        except ConnectionError:
            logger.warning("初始连接失败，进入离线待机")
            self._state_machine.transition(ClientState.OFFLINE_STANDBY)

        # 启动唤醒词监听（阻塞式主循环）
        logger.info("开始唤醒词监听...")
        try:
            await self._wake_word_detector.start_listening()
        except Exception:
            logger.exception("唤醒词监听异常退出")

    async def stop(self) -> None:
        """优雅关闭客户端，释放所有资源。"""
        logger.info("正在关闭语音助手客户端...")
        self._running = False

        await self._wake_word_detector.stop_listening()
        await self._audio_recorder.stop_recording()
        await self._audio_player.stop()
        await self._interrupt_handler.stop_monitoring()
        await self._ws_client.disconnect()

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
