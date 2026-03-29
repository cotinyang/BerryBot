"""服务端入口：解析配置、初始化组件、启动 WebSocket 服务。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from server.config import ServerConfig

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    """解析命令行参数，返回 ServerConfig。

    未提供的参数使用 ServerConfig 默认值。
    """
    defaults = ServerConfig()
    parser = argparse.ArgumentParser(description="语音助手 WebSocket 服务端")
    parser.add_argument("--host", default=defaults.host, help="监听地址")
    parser.add_argument("--port", type=int, default=defaults.port, help="监听端口")
    parser.add_argument(
        "--whisper-model",
        default=defaults.whisper_model_size,
        help="Whisper 模型大小",
    )
    parser.add_argument(
        "--tts-voice",
        default=defaults.tts_voice,
        help="TTS 语音角色",
    )
    parser.add_argument(
        "--tts-sentence-stream",
        action=argparse.BooleanOptionalAction,
        default=defaults.tts_sentence_stream,
        help="是否按句分段进行 TTS 流式合成（默认: 启用）",
    )
    parser.add_argument(
        "--tts-sentence-max-chars",
        type=int,
        default=defaults.tts_sentence_max_chars,
        help="按句模式下单段最大字符数（默认: 80）",
    )
    parser.add_argument("--soul-path", default=defaults.soul_path, help="SOUL.md 路径")
    parser.add_argument(
        "--memory-path", default=defaults.memory_path, help="MEMORY.md 路径"
    )
    parser.add_argument(
        "--models-config", default="models.json", help="模型配置文件路径 (默认: models.json)"
    )
    parser.add_argument(
        "--auth-token", default=defaults.auth_token, help="预共享认证 token"
    )
    parser.add_argument(
        "--tls-cert", default=defaults.tls_cert_path, help="TLS 证书路径 (fullchain.pem)"
    )
    parser.add_argument(
        "--tls-key", default=defaults.tls_key_path, help="TLS 私钥路径 (privkey.pem)"
    )
    parser.add_argument(
        "--debug-bypass-agent",
        action="store_true",
        help="调试模式: 跳过 AI Agent，识别文本直接进入 TTS",
    )
    args = parser.parse_args(argv)
    config = ServerConfig(
        host=args.host,
        port=args.port,
        whisper_model_size=args.whisper_model,
        tts_voice=args.tts_voice,
        tts_sentence_stream=args.tts_sentence_stream,
        tts_sentence_max_chars=args.tts_sentence_max_chars,
        soul_path=args.soul_path,
        memory_path=args.memory_path,
        auth_token=args.auth_token,
        tls_cert_path=args.tls_cert,
        tls_key_path=args.tls_key,
        debug_bypass_agent=args.debug_bypass_agent,
    )
    config._models_config = args.models_config  # type: ignore[attr-defined]
    return config


async def run_server(config: ServerConfig) -> None:
    """根据配置创建组件并启动服务。"""
    from server.ai_agent import AIAgent
    from server.memory_tools import create_memory_tools
    from server.model_manager import ModelManager, load_models_config
    from server.model_tools import create_model_tools
    from server.session_tools import create_session_tools
    from server.speech_recognizer import SpeechRecognizer
    from server.speech_synthesizer import SpeechSynthesizer
    from server.ws_server import WebSocketServer

    recognizer = SpeechRecognizer(
        model_size=config.whisper_model_size,
        language=config.whisper_language,
    )

    # 加载模型配置
    models_config_path = getattr(config, "_models_config", "models.json")
    models, default_model = load_models_config(models_config_path)

    model_manager = ModelManager(models=models, default_model=default_model) if models else None

    # 创建工具
    memory_tools = create_memory_tools(config.memory_path)
    model_tools = create_model_tools(model_manager) if model_manager else []
    session_tools = create_session_tools()
    all_tools = memory_tools + model_tools + session_tools

    agent = None
    if not config.debug_bypass_agent:
        agent = AIAgent(
            soul_path=config.soul_path,
            memory_path=config.memory_path,
            tools=all_tools,
            model_manager=model_manager,
        )
    else:
        logger.warning("Debug mode enabled: bypassing AI Agent, ASR text will be sent to TTS")
    synthesizer = SpeechSynthesizer(
        voice=config.tts_voice,
        sentence_stream=config.tts_sentence_stream,
        sentence_max_chars=config.tts_sentence_max_chars,
    )

    server = WebSocketServer(
        host=config.host,
        port=config.port,
        speech_recognizer=recognizer,
        ai_agent=agent,
        speech_synthesizer=synthesizer,
        auth_token=config.auth_token,
        tls_cert_path=config.tls_cert_path,
        tls_key_path=config.tls_key_path,
        debug_bypass_agent=config.debug_bypass_agent,
    )

    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("收到终止信号，正在关闭服务…")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await server.start()
    protocol = "wss" if config.tls_cert_path else "ws"
    logger.info(
        "服务已启动 %s://%s:%d  (whisper=%s, voice=%s, sentence_stream=%s, bypass_agent=%s)",
        protocol,
        config.host,
        config.port,
        config.whisper_model_size,
        config.tts_voice,
        config.tts_sentence_stream,
        config.debug_bypass_agent,
    )

    await stop_event.wait()
    await server.stop()
    logger.info("服务已停止")


def main(argv: list[str] | None = None) -> None:
    """入口函数。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = parse_args(argv)
    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
