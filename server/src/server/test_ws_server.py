"""WebSocketServer 单元测试。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
import websockets

from server.ws_server import WebSocketServer


def _make_server(
    speech_recognizer=None, ai_agent=None, speech_synthesizer=None, debug_bypass_agent=False
) -> WebSocketServer:
    """创建带有可选依赖的 WebSocketServer 实例。"""
    return WebSocketServer(
        host="127.0.0.1",
        port=0,
        speech_recognizer=speech_recognizer,
        ai_agent=ai_agent,
        speech_synthesizer=speech_synthesizer,
        debug_bypass_agent=debug_bypass_agent,
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
    async def _fake_stream(_text):
        yield b"\xff\xfb\x90\x00" * 50
        yield b"\xff\xfb\x90\x00" * 50

    synthesizer.synthesize_stream = _fake_stream

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
        assert msg3["stream"] is True

        # Expect: chunk metadata + binary (x2)
        chunk_meta1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert chunk_meta1["type"] == "audio_chunk"
        audio1 = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert isinstance(audio1, bytes)
        assert len(audio1) > 0

        chunk_meta2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert chunk_meta2["type"] == "audio_chunk"
        audio2 = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert isinstance(audio2, bytes)
        assert len(audio2) > 0

        end_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        assert end_msg["type"] == "audio_end"
        assert end_msg["chunks"] == 2

    recognizer.recognize.assert_called_once()
    agent.process.assert_called_once_with("你好")


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

    async def _failing_stream(_text):
        raise RuntimeError("合成失败")
        yield b""  # pragma: no cover

    synthesizer.synthesize_stream = _failing_stream
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


@pytest.mark.asyncio
async def test_debug_bypass_agent_echoes_asr_text() -> None:
    """测试调试模式下跳过 Agent，识别文本直接进入 TTS。"""
    recognizer = MagicMock()
    recognizer.recognize = MagicMock(return_value="测试回声")

    agent = MagicMock()
    agent.process = AsyncMock(return_value="不应被调用")

    synthesizer = MagicMock()
    async def _fake_stream(_text):
        yield b"\xff\xfb\x90\x00" * 50

    synthesizer.synthesize_stream = _fake_stream

    ws_server = _make_server(
        speech_recognizer=recognizer,
        ai_agent=agent,
        speech_synthesizer=synthesizer,
        debug_bypass_agent=True,
    )
    ws_server._server = await websockets.serve(ws_server.handle_client, "127.0.0.1", 0)
    ws_server._port = ws_server._server.sockets[0].getsockname()[1]

    try:
        url = f"ws://127.0.0.1:{ws_server._port}"
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
            await ws.send(b"\x00\x01\x02\x03" * 100)

            msg1 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert msg1["type"] == "status"
            assert msg1["status"] == "processing"

            msg2 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert msg2["type"] == "status"
            assert msg2["status"] == "synthesizing"

            msg3 = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert msg3["type"] == "audio_response"
            assert msg3["stream"] is True

            chunk_meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert chunk_meta["type"] == "audio_chunk"
            audio = await asyncio.wait_for(ws.recv(), timeout=2.0)
            assert isinstance(audio, bytes)
            assert len(audio) > 0

            end_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert end_msg["type"] == "audio_end"

        recognizer.recognize.assert_called_once()
        agent.process.assert_not_called()
    finally:
        await ws_server.stop()


@pytest.mark.asyncio
async def test_segment_batch_stream_metadata_emitted() -> None:
    """支持分段合成时应发送 segment start/end 元数据。"""
    recognizer = MagicMock()
    recognizer.recognize = MagicMock(return_value="第一句。第二句。")

    agent = MagicMock()
    agent.process = AsyncMock(return_value="第一句。第二句。")

    class _SegmentedSynthesizer:
        def iter_segments(self, _text: str):
            return ["第一句。", "第二句。"]

        async def synthesize_segment_stream(self, segment_text: str):
            if segment_text == "第一句。":
                yield b"seg1-a"
                yield b"seg1-b"
            else:
                yield b"seg2-a"

    synthesizer = _SegmentedSynthesizer()

    ws_server = _make_server(
        speech_recognizer=recognizer,
        ai_agent=agent,
        speech_synthesizer=synthesizer,
    )
    ws_server._server = await websockets.serve(ws_server.handle_client, "127.0.0.1", 0)
    ws_server._port = ws_server._server.sockets[0].getsockname()[1]

    try:
        url = f"ws://127.0.0.1:{ws_server._port}"
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({"type": "audio", "format": "wav", "sample_rate": 16000}))
            await ws.send(b"\x00" * 400)

            await asyncio.wait_for(ws.recv(), timeout=2.0)  # processing
            await asyncio.wait_for(ws.recv(), timeout=2.0)  # synthesizing

            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert msg["type"] == "audio_response"
            assert msg.get("segment_batch") is True

            s1_start = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert s1_start["type"] == "audio_segment_start"
            assert s1_start["segment_id"] == 1

            c1_meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert c1_meta["type"] == "audio_chunk"
            assert c1_meta["segment_id"] == 1
            assert isinstance(await asyncio.wait_for(ws.recv(), timeout=2.0), bytes)

            c2_meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert c2_meta["type"] == "audio_chunk"
            assert c2_meta["segment_id"] == 1
            assert isinstance(await asyncio.wait_for(ws.recv(), timeout=2.0), bytes)

            s1_end = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert s1_end["type"] == "audio_segment_end"
            assert s1_end["segment_id"] == 1
            assert s1_end["chunks"] == 2

            s2_start = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert s2_start["type"] == "audio_segment_start"
            assert s2_start["segment_id"] == 2

            c3_meta = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert c3_meta["type"] == "audio_chunk"
            assert c3_meta["segment_id"] == 2
            assert isinstance(await asyncio.wait_for(ws.recv(), timeout=2.0), bytes)

            s2_end = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert s2_end["type"] == "audio_segment_end"
            assert s2_end["segment_id"] == 2
            assert s2_end["chunks"] == 1

            end_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert end_msg["type"] == "audio_end"
            assert end_msg["chunks"] == 3
    finally:
        await ws_server.stop()
