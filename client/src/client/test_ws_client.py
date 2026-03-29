"""WebSocketClient 单元测试。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client.ws_client import WebSocketClient


@pytest.fixture
def client():
    """创建 WebSocketClient 实例，使用短重连间隔加速测试。"""
    return WebSocketClient(
        server_url="ws://localhost:8765",
        max_retries=3,
        retry_interval=0.01,  # 极短间隔加速测试
        receive_timeout=0.1,
    )


@pytest.fixture
def mock_ws():
    """创建 mock WebSocket 连接。"""
    ws = AsyncMock()
    ws.close = AsyncMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    return ws


class TestConnect:
    @pytest.mark.asyncio
    async def test_connect_success(self, client, mock_ws):
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            assert client.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_failure_raises(self, client):
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, side_effect=OSError("refused")):
            with pytest.raises(ConnectionError):
                await client.connect()
            assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_sets_max_size(self, mock_ws):
        client = WebSocketClient(
            server_url="ws://localhost:8765",
            max_message_size=16 * 1024 * 1024,
        )
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws) as mock_connect:
            await client.connect()
            assert mock_connect.await_count == 1
            assert mock_connect.await_args.kwargs["max_size"] == 16 * 1024 * 1024


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect(self, client, mock_ws):
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            await client.disconnect()
            assert client.is_connected is False
            mock_ws.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_when_not_connected(self, client):
        await client.disconnect()  # 不应抛出异常
        assert client.is_connected is False


class TestSendAudio:
    @pytest.mark.asyncio
    async def test_send_audio_sends_metadata_then_binary(self, client, mock_ws):
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            audio = b"\x00\x01\x02\x03"
            await client.send_audio(audio)

            assert mock_ws.send.await_count == 2
            # 第一次发送 JSON 元数据
            metadata = json.loads(mock_ws.send.call_args_list[0][0][0])
            assert metadata["type"] == "audio"
            assert metadata["format"] == "wav"
            assert metadata["sample_rate"] == 16000
            # 第二次发送二进制音频
            assert mock_ws.send.call_args_list[1][0][0] == audio

    @pytest.mark.asyncio
    async def test_send_audio_not_connected_raises(self, client):
        with pytest.raises(ConnectionError):
            await client.send_audio(b"\x00")


class TestSendInterrupt:
    @pytest.mark.asyncio
    async def test_send_interrupt(self, client, mock_ws):
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            await client.send_interrupt()

            msg = json.loads(mock_ws.send.call_args[0][0])
            assert msg["type"] == "interrupt"

    @pytest.mark.asyncio
    async def test_send_interrupt_not_connected_raises(self, client):
        with pytest.raises(ConnectionError):
            await client.send_interrupt()


class TestReceiveAudio:
    @pytest.mark.asyncio
    async def test_receive_audio_success(self, client, mock_ws):
        audio_bytes = b"\xff\xfb\x90\x00"  # fake MP3 data
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "audio_response", "format": "mp3"}),
            audio_bytes,
        ])
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            result = await client.receive_audio()
            assert result == audio_bytes

    @pytest.mark.asyncio
    async def test_receive_audio_stream_success(self, client, mock_ws):
        chunk1 = b"\xff\xfb\x90\x00" * 20
        chunk2 = b"\xff\xfb\x90\x00" * 10
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "audio_response", "format": "mp3", "stream": True}),
            json.dumps({"type": "audio_chunk", "seq": 1}),
            chunk1,
            json.dumps({"type": "audio_chunk", "seq": 2}),
            chunk2,
            json.dumps({"type": "audio_end", "format": "mp3", "chunks": 2}),
        ])
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            result = await client.receive_audio()
            assert result == chunk1 + chunk2

    @pytest.mark.asyncio
    async def test_receive_audio_stream_segment_batch_success(self, client, mock_ws):
        s1c1 = b"A" * 5
        s1c2 = b"B" * 3
        s2c1 = b"C" * 4
        mock_ws.recv = AsyncMock(side_effect=[
            json.dumps({"type": "audio_response", "format": "mp3", "stream": True, "segment_batch": True}),
            json.dumps({"type": "audio_segment_start", "segment_id": 1}),
            json.dumps({"type": "audio_chunk", "seq": 1, "segment_id": 1}),
            s1c1,
            json.dumps({"type": "audio_chunk", "seq": 2, "segment_id": 1}),
            s1c2,
            json.dumps({"type": "audio_segment_end", "segment_id": 1, "chunks": 2}),
            json.dumps({"type": "audio_segment_start", "segment_id": 2}),
            json.dumps({"type": "audio_chunk", "seq": 3, "segment_id": 2}),
            s2c1,
            json.dumps({"type": "audio_segment_end", "segment_id": 2, "chunks": 1}),
            json.dumps({"type": "audio_end", "format": "mp3", "chunks": 3}),
        ])
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            response = await client.receive_response()
            chunks = [chunk async for chunk in response["stream"]]
            # 每个 segment 应先聚合后再输出
            assert chunks == [s1c1 + s1c2, s2c1]

    @pytest.mark.asyncio
    async def test_receive_audio_server_error(self, client, mock_ws):
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "type": "error",
            "code": "recognition_failed",
            "message": "无法识别",
        }))
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
            await client.connect()
            with pytest.raises(RuntimeError, match="Server error"):
                await client.receive_audio()

    @pytest.mark.asyncio
    async def test_receive_audio_not_connected_raises(self, client):
        with pytest.raises(ConnectionError):
            await client.receive_audio()


class TestCallbacks:
    @pytest.mark.asyncio
    async def test_on_disconnect_callback(self, client, mock_ws):
        callback = MagicMock()
        client.on_disconnect(callback)

        # 模拟连接后发送失败触发断连
        mock_ws.send = AsyncMock(side_effect=OSError("broken pipe"))
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, return_value=mock_ws) as mock_connect:
            await client.connect()
            # 所有重连也失败
            mock_connect.side_effect = OSError("refused")
            with pytest.raises(ConnectionError):
                await client.send_audio(b"\x00")
            callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_reconnect_callback(self, client, mock_ws):
        callback = MagicMock()
        client.on_reconnect(callback)

        fresh_ws = AsyncMock()
        fresh_ws.close = AsyncMock()
        fresh_ws.send = AsyncMock()

        mock_ws.send = AsyncMock(side_effect=OSError("broken pipe"))
        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_ws
            await client.connect()

            # 重连时成功
            mock_connect.side_effect = None
            mock_connect.return_value = fresh_ws
            with pytest.raises(ConnectionError):
                await client.send_audio(b"\x00")
            callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_connection_failed_callback(self, client):
        callback = MagicMock()
        client.on_connection_failed(callback)

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=OSError("broken pipe"))

        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_ws
            await client.connect()

            # 所有重连都失败
            mock_connect.side_effect = OSError("refused")
            with pytest.raises(ConnectionError):
                await client.send_audio(b"\x00")
            callback.assert_called_once()


class TestAutoReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_retries_max_times(self, client):
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=OSError("broken"))

        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = mock_ws
            await client.connect()

            # 所有重连失败
            mock_connect.side_effect = OSError("refused")
            with pytest.raises(ConnectionError):
                await client.send_audio(b"\x00")

            # 初始连接 1 次 + 重连 3 次 = 4 次
            assert mock_connect.await_count == 4

    @pytest.mark.asyncio
    async def test_reconnect_succeeds_on_second_attempt(self, client):
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock(side_effect=OSError("broken"))

        fresh_ws = AsyncMock()
        fresh_ws.close = AsyncMock()

        attempt = 0

        async def connect_side_effect(*args, **kwargs):
            nonlocal attempt
            attempt += 1
            if attempt <= 2:  # 初始连接 + 第一次重连失败
                if attempt == 1:
                    return mock_ws
                raise OSError("refused")
            return fresh_ws  # 第二次重连成功

        with patch("client.ws_client.websockets.connect", new_callable=AsyncMock, side_effect=connect_side_effect):
            await client.connect()
            with pytest.raises(ConnectionError):
                await client.send_audio(b"\x00")
            # 重连成功后应恢复连接状态
            assert client.is_connected is True
