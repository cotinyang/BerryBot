"""服务端入口 main.py 单元测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.config import ServerConfig
from server.main import parse_args, run_server


class TestParseArgs:
    """parse_args 参数解析测试。"""

    def test_defaults(self) -> None:
        config = parse_args([])
        defaults = ServerConfig()
        assert config.host == defaults.host
        assert config.port == defaults.port
        assert config.whisper_model_size == defaults.whisper_model_size
        assert config.tts_voice == defaults.tts_voice
        assert config.soul_path == defaults.soul_path
        assert config.memory_path == defaults.memory_path

    def test_custom_args(self) -> None:
        config = parse_args([
            "--host", "127.0.0.1",
            "--port", "9000",
            "--whisper-model", "large",
            "--tts-voice", "zh-CN-YunxiNeural",
            "--soul-path", "/tmp/soul.md",
            "--memory-path", "/tmp/mem.md",
            "--debug-bypass-agent",
        ])
        assert config.host == "127.0.0.1"
        assert config.port == 9000
        assert config.whisper_model_size == "large"
        assert config.tts_voice == "zh-CN-YunxiNeural"
        assert config.soul_path == "/tmp/soul.md"
        assert config.memory_path == "/tmp/mem.md"
        assert config.debug_bypass_agent is True

    def test_partial_args(self) -> None:
        config = parse_args(["--port", "1234"])
        assert config.port == 1234
        assert config.host == ServerConfig().host


class TestRunServer:
    """run_server 启动/关闭流程测试。"""

    @pytest.mark.asyncio
    async def test_starts_and_stops(self) -> None:
        """验证 run_server 能正常启动并在收到信号后停止。"""
        config = ServerConfig()

        with (
            patch("server.speech_recognizer.SpeechRecognizer") as mock_sr,
            patch("server.ai_agent.AIAgent") as mock_agent,
            patch("server.speech_synthesizer.SpeechSynthesizer") as mock_ss,
            patch("server.memory_tools.create_memory_tools", return_value=[]),
            patch("server.ws_server.WebSocketServer") as mock_ws,
        ):
            mock_server_instance = MagicMock()
            mock_server_instance.start = AsyncMock()
            mock_server_instance.stop = AsyncMock()
            mock_ws.return_value = mock_server_instance

            async def stop_soon() -> None:
                await asyncio.sleep(0.05)
                import os
                import signal as _sig
                os.kill(os.getpid(), _sig.SIGINT)

            task = asyncio.create_task(run_server(config))
            stopper = asyncio.create_task(stop_soon())

            await asyncio.gather(task, stopper)

            mock_server_instance.start.assert_awaited_once()
            mock_server_instance.stop.assert_awaited_once()
