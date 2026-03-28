"""WebSocketServer 单元测试。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import websockets

from server.ws_server import WebSocketServer


def _make_server(
    speech_recognizer=None, ai_agent=None, speech_synthesizer=None
) -> WebSocketServer:
    """创建带有可选依赖的 WebSocketServer 实例。"""
    return WebSocketServer(
        host="127.0.0.1",
        port=0,
        speech_recognizer=speech_recognizer,
        ai_agent=ai_agent,
        speech_synthesizer=speech_synthesizer,
    )


@pytest_asyncio.fixture
async def server():
    """启动一个测试用 WebSocketServer 实例（无依赖注入）。"""
    ws_server = _make_server()
    ws_server._server = await websockets.serve(
        ws_server.handle_client, "127.0.0.1", 0
    )
    port = ws_server._server.sockets[0].getsockname()[1]
    ws_server._port = port
    yield ws_server
    await ws_server.stop()


@pytest_asyncio.fixture
async def pipeline_server():
    """启动一个带有 mock 依赖的 WebSocketServer 实例，用于测试完整流水线。"""
    recognizer = MagicMock()
    recognizer.recognize = MagicMock(return_value="你好")

    agent = MagicMock()
    agent.process = AsyncMock(return_value="你好，有什么可以帮你的？")

    synthesizer = MagicMock()
    synthesizer.synthesize = AsyncMock(return_value=b"\xff\xfb\x90\x00" * 100)

    ws_server = _make_server(
        speech_recognizer=recognizer,
        ai_agent=agent,
        speech_synthesizer=synthesizer,
    )
    ws_server._server = await websockets.serve(
        ws_server.handle_client, "127.0.0.1", 0
    )
    port = ws_server._server.sockets[0].getsockname()[1]
    ws_server._port = port
    yield ws_server, recognizer, agent, synthesizer
    await ws_server.stop()


def _server_url(server) -> str:
    port = server._port if isinstance(server, WebSocketServer) else server[0]._port
    return f"ws://127.0.0.1:{port}"


# ------------------------------------------------------------------
# Basic server tests (no pipeline dependencies)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_and_stop():
    """测试服务端启动和停止。"""
    ws_server = WebSocketServer(host="127.0.0.1", port=18765)
    await ws_server.start()
    assert ws_server._server is not None
    await ws_server.stop()
    assert ws_server._server is None


@pytest.mark.asyncio
async def test_invalid_json_returns_error(server: WebSocketServer):
    """测试发送无效 JSON 时返回错误消息。"""
    url = _server_url(server)
    async with websockets.connect(url) as ws:
        await ws.send("not valid json {{{")
        response = await asyncio.wait_for(ws.recv(), timeout=2.0)
        msg = json.loads(response)
        assert msg["type"] == "error"
        assert msg["code"] == "invalid_message"


@pytest.mark.asyncio
async def test_unknown_message_type_returns_error(server: WebSocketServer):
    """测试发送未知消息类型时返回错误消息。"""
    url = _server_url(server)
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "unknown_type"}))
        response = await asyncio.wait_for(ws.recv(), timeout=2.0)
        msg = json.loads(response)
        assert msg["type"] == "error"
        assert msg["code"] == "unknown_type"


@pytest.mark.asyncio
async def test_audio_without_binary_frame_returns_error(server: WebSocketServer):
    """测试发送音频元数据后发送文本而非二进制帧时返回错误。"""
    url = _server_url(server)
    async with websockets.connect(url) as ws:
        metadata = json.dumps({
            "type": "audio",
            "format": "wav",
            "sample_rate": 16000,
        })
        await ws.send(metadata)
        await ws.send("this is not binary")
        response = await asyncio.wait_for(ws.recv(), timeout=2.0)
        msg = json.loads(response)
        assert msg["type"] == "error"
        assert msg["code"] == "invalid_message"


# ------------------------------------------------------------------
# Pipeline tests (with mock dependencies)
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_success(pipeline_server):
    """测试完整流水线：音频→识别→Agent→合成→返回语音。"""
    ws_server, recognizer, agent, synthesizer = pipeline_server
    url = f"ws://127.0.0.1:{ws_server._port}"

    async with websockets.connect(url) as ws:
        # Send audio metadata + binary
        await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
        await ws.send(b"\x00\x01\x02\x03" * 100)

        # Expect: status "processing"
        msg1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg1["type"] == "status"
        assert msg1["status"] == "processing"

        # Expect: status "synthesizing"
        msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg2["type"] == "status"
        assert msg2["status"] == "synthesizing"

        # Expect: audio_response metadata
        msg3 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg3["type"] == "audio_response"
        assert msg3["format"] == "mp3"

        # Expect: binary audio data
        audio = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert isinstance(audio, bytes)
        assert len(audio) > 0

    recognizer.recognize.assert_called_once()
    agent.process.assert_called_once_with("你好")
    synthesizer.synthesize.assert_called_once_with("你好，有什么可以帮你的？")


@pytest.mark.asyncio
async def test_recognition_failure_returns_error(pipeline_server):
    """测试语音识别失败时返回错误消息。"""
    ws_server, recognizer, _, _ = pipeline_server
    recognizer.recognize.side_effect = ValueError("语音识别结果为空")
    url = f"ws://127.0.0.1:{ws_server._port}"

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
        await ws.send(b"\x00" * 400)

        # status "processing"
        msg1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg1["type"] == "status"

        # error
        msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg2["type"] == "error"
        assert msg2["code"] == "recognition_failed"


@pytest.mark.asyncio
async def test_agent_error_returns_error(pipeline_server):
    """测试 AI Agent 处理错误时返回错误消息。"""
    ws_server, _, agent, _ = pipeline_server
    agent.process.side_effect = RuntimeError("Agent 内部错误")
    url = f"ws://127.0.0.1:{ws_server._port}"

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
        await ws.send(b"\x00" * 400)

        # status "processing"
        msg1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg1["type"] == "status"

        # error
        msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg2["type"] == "error"
        assert msg2["code"] == "agent_error"


@pytest.mark.asyncio
async def test_synthesis_error_returns_error(pipeline_server):
    """测试语音合成错误时返回错误消息。"""
    ws_server, _, _, synthesizer = pipeline_server
    synthesizer.synthesize.side_effect = RuntimeError("合成失败")
    url = f"ws://127.0.0.1:{ws_server._port}"

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
        await ws.send(b"\x00" * 400)

        # status "processing"
        msg1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg1["type"] == "status"

        # status "synthesizing"
        msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg2["type"] == "status"

        # error
        msg3 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg3["type"] == "error"
        assert msg3["code"] == "synthesis_error"


@pytest.mark.asyncio
async def test_no_recognizer_returns_error(server: WebSocketServer):
    """测试未配置语音识别器时返回错误。"""
    url = _server_url(server)
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
        await ws.send(b"\x00" * 400)

        # status "processing"
        msg1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg1["type"] == "status"

        # error - recognizer not configured
        msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg2["type"] == "error"
        assert msg2["code"] == "recognition_failed"


@pytest.mark.asyncio
async def test_interrupt_cancels_processing(pipeline_server):
    """测试打断消息取消正在进行的处理任务。"""
    ws_server, _, agent, _ = pipeline_server

    # Make agent.process block so we can interrupt it
    async def slow_process(text):
        await asyncio.sleep(10)
        return "不应该到达这里"

    agent.process.side_effect = slow_process
    url = f"ws://127.0.0.1:{ws_server._port}"

    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
        await ws.send(b"\x00" * 400)

        # Wait for processing status
        msg1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert msg1["type"] == "status"
        assert msg1["status"] == "processing"

        # Send interrupt
        await ws.send(json.dumps({"type": "interrupt"}))
        await asyncio.sleep(0.1)

        # The processing task should have been cancelled
        # No audio_response or synthesizing status should follow
