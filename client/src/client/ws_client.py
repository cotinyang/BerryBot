"""WebSocket 通信客户端：管理与服务端的 WebSocket 连接。"""

import asyncio
from collections.abc import AsyncIterator
import json
import logging
import ssl
from typing import Callable

import websockets
from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket 通信客户端。

    通过 WebSocket 协议与服务端进行实时双向通信，
    支持发送音频数据、打断通知，以及接收语音回复。
    具备自动重连机制。
    """

    def __init__(
        self,
        server_url: str,
        max_retries: int = 3,
        retry_interval: float = 5.0,
        auth_token: str = "",
        receive_timeout: float = 30.0,
    ) -> None:
        self._server_url = server_url
        self._max_retries = max_retries
        self._retry_interval = retry_interval
        self._auth_token = auth_token
        self._receive_timeout = receive_timeout
        self._ws: ClientConnection | None = None
        self._connected = False
        self._disconnect_callbacks: list[Callable[[], None]] = []
        self._reconnect_callbacks: list[Callable[[], None]] = []
        self._connection_failed_callbacks: list[Callable[[], None]] = []

    @property
    def is_connected(self) -> bool:
        """当前是否已连接。"""
        return self._connected and self._ws is not None

    @property
    def _connect_url(self) -> str:
        """构建带 token 的连接 URL。"""
        if self._auth_token:
            sep = "&" if "?" in self._server_url else "?"
            return f"{self._server_url}{sep}token={self._auth_token}"
        return self._server_url

    def _get_ssl_context(self) -> ssl.SSLContext | None:
        """为 wss:// 连接创建 SSL 上下文。"""
        if not self._server_url.startswith("wss"):
            return None
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        return ctx

    async def connect(self) -> None:
        """连接到 WebSocket 服务端。

        Raises:
            ConnectionError: 连接失败时抛出。
        """
        try:
            ssl_ctx = self._get_ssl_context()
            self._ws = await websockets.connect(self._connect_url, ssl=ssl_ctx)
            self._connected = True
            logger.info("Connected to server: %s", self._server_url)
        except Exception as exc:
            self._connected = False
            self._ws = None
            logger.error("Failed to connect to server: %s", exc)
            raise ConnectionError(f"Failed to connect: {exc}") from exc

    async def disconnect(self) -> None:
        """断开 WebSocket 连接。"""
        self._connected = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception as exc:
                logger.warning("Error closing WebSocket: %s", exc)
            finally:
                self._ws = None

    async def send_audio(self, audio_data: bytes) -> None:
        """发送音频数据到服务端。

        先发送 JSON 元数据消息，再发送二进制音频帧。

        Args:
            audio_data: WAV 格式的音频字节数据。

        Raises:
            ConnectionError: 未连接时抛出。
        """
        if not self.is_connected or self._ws is None:
            raise ConnectionError("Not connected to server")

        metadata = json.dumps({
            "type": "audio",
            "format": "wav",
            "sample_rate": 16000,
        })
        try:
            await self._ws.send(metadata)
            await self._ws.send(audio_data)
        except Exception as exc:
            logger.error("Failed to send audio: %s", exc)
            await self._handle_disconnect()
            raise ConnectionError(f"Failed to send audio: {exc}") from exc

    async def send_interrupt(self) -> None:
        """发送语音打断通知给服务端。

        Raises:
            ConnectionError: 未连接时抛出。
        """
        if not self.is_connected or self._ws is None:
            raise ConnectionError("Not connected to server")

        message = json.dumps({"type": "interrupt"})
        try:
            await self._ws.send(message)
        except Exception as exc:
            logger.error("Failed to send interrupt: %s", exc)
            await self._handle_disconnect()
            raise ConnectionError(f"Failed to send interrupt: {exc}") from exc

    async def receive_response(self) -> dict:
        """接收服务端返回的响应（语音或指令）。

        Returns:
            dict with keys:
            - type: "audio" | "audio_stream" | "command" | "status"
            - data: bytes (for audio) or None
            - stream: AsyncIterator[bytes] (for audio_stream) or None
            - action: str (for command, e.g. "end_session")

        Raises:
            ConnectionError: 未连接或接收失败时抛出。
            RuntimeError: 服务端返回错误时抛出。
        """
        if not self.is_connected or self._ws is None:
            raise ConnectionError("Not connected to server")

        try:
            # 跳过 status 消息，等待实际响应
            while True:
                raw = await self._recv_frame()
                metadata = json.loads(raw)
                msg_type = metadata.get("type")

                if msg_type == "status":
                    logger.debug("Server status: %s", metadata.get("status"))
                    continue

                if msg_type == "error":
                    code = metadata.get("code", "unknown")
                    msg = metadata.get("message", "Unknown error")
                    raise RuntimeError(f"Server error [{code}]: {msg}")

                if msg_type == "command":
                    action = metadata.get("action", "")
                    logger.info("Received command from server: %s", action)
                    return {
                        "type": "command",
                        "action": action,
                        "data": None,
                        "stream": None,
                    }

                if msg_type == "audio_response":
                    if metadata.get("stream"):
                        audio_format = metadata.get("format", "mp3")
                        return {
                            "type": "audio_stream",
                            "action": "",
                            "data": None,
                            "stream": self._iter_audio_chunks(),
                            "format": audio_format,
                        }

                    audio_data = await self._recv_frame()
                    if not isinstance(audio_data, bytes):
                        raise RuntimeError("Expected binary audio frame")
                    return {
                        "type": "audio",
                        "action": "",
                        "data": audio_data,
                        "stream": None,
                        "format": metadata.get("format", "mp3"),
                    }

                logger.warning("Unknown response type: %s", msg_type)
                continue

        except RuntimeError:
            raise
        except ConnectionError:
            raise
        except Exception as exc:
            logger.error("Failed to receive response: %s", exc)
            await self._handle_disconnect()
            raise ConnectionError(f"Failed to receive response: {exc}") from exc

    async def receive_audio(self) -> bytes:
        """接收服务端返回的语音数据（向后兼容）。

        Returns:
            MP3 格式的音频字节数据。

        Raises:
            ConnectionError: 未连接或接收失败时抛出。
        """
        response = await self.receive_response()
        if response["type"] == "command":
            raise RuntimeError(f"Unexpected command: {response['action']}")
        if response["type"] == "audio_stream":
            chunks = [chunk async for chunk in response["stream"]]
            return b"".join(chunks)
        return response["data"]

    async def _iter_audio_chunks(self) -> AsyncIterator[bytes]:
        """读取流式音频 chunk，直到收到 audio_end。"""
        if not self.is_connected or self._ws is None:
            raise ConnectionError("Not connected to server")

        while True:
            raw = await self._recv_frame()
            if isinstance(raw, bytes):
                raise RuntimeError("Unexpected binary frame without chunk metadata")

            metadata = json.loads(raw)
            msg_type = metadata.get("type")

            if msg_type == "audio_chunk":
                audio_data = await self._recv_frame()
                if not isinstance(audio_data, bytes):
                    raise RuntimeError("Expected binary audio chunk")
                yield audio_data
                continue

            if msg_type == "audio_end":
                return

            if msg_type == "status":
                logger.debug("Server status during stream: %s", metadata.get("status"))
                continue

            if msg_type == "error":
                code = metadata.get("code", "unknown")
                msg = metadata.get("message", "Unknown error")
                raise RuntimeError(f"Server error [{code}]: {msg}")

            raise RuntimeError(f"Unexpected stream message type: {msg_type}")

    async def _recv_frame(self) -> str | bytes:
        """带超时地读取一帧消息，避免无限等待。"""
        if not self.is_connected or self._ws is None:
            raise ConnectionError("Not connected to server")

        try:
            return await asyncio.wait_for(
                self._ws.recv(),
                timeout=self._receive_timeout,
            )
        except asyncio.TimeoutError as exc:
            logger.error(
                "Timed out waiting for server frame after %.1fs",
                self._receive_timeout,
            )
            await self._handle_disconnect()
            raise ConnectionError("Timed out waiting for server response") from exc

    def on_disconnect(self, callback: Callable[[], None]) -> None:
        """注册断开连接回调。

        Args:
            callback: 连接断开时调用的回调函数。
        """
        self._disconnect_callbacks.append(callback)

    def on_reconnect(self, callback: Callable[[], None]) -> None:
        """注册重连成功回调。

        Args:
            callback: 重连成功时调用的回调函数。
        """
        self._reconnect_callbacks.append(callback)

    def on_connection_failed(self, callback: Callable[[], None]) -> None:
        """注册连接失败回调（重连耗尽后触发）。

        Args:
            callback: 所有重连尝试失败后调用的回调函数。
        """
        self._connection_failed_callbacks.append(callback)

    async def _handle_disconnect(self) -> None:
        """处理连接断开：触发回调并尝试自动重连。"""
        self._connected = False
        self._ws = None

        for cb in self._disconnect_callbacks:
            try:
                cb()
            except Exception as exc:
                logger.warning("Disconnect callback error: %s", exc)

        await self._auto_reconnect()

    async def _auto_reconnect(self) -> None:
        """自动重连逻辑：每隔 retry_interval 秒重试，最多 max_retries 次。"""
        for attempt in range(1, self._max_retries + 1):
            logger.info(
                "Reconnect attempt %d/%d in %.1fs...",
                attempt,
                self._max_retries,
                self._retry_interval,
            )
            await asyncio.sleep(self._retry_interval)

            try:
                ssl_ctx = self._get_ssl_context()
                self._ws = await websockets.connect(self._connect_url, ssl=ssl_ctx)
                self._connected = True
                logger.info("Reconnected to server on attempt %d", attempt)

                for cb in self._reconnect_callbacks:
                    try:
                        cb()
                    except Exception as exc:
                        logger.warning("Reconnect callback error: %s", exc)
                return
            except Exception as exc:
                logger.warning("Reconnect attempt %d failed: %s", attempt, exc)

        # 所有重连尝试失败
        logger.error(
            "All %d reconnect attempts failed", self._max_retries
        )
        for cb in self._connection_failed_callbacks:
            try:
                cb()
            except Exception as exc:
                logger.warning("Connection failed callback error: %s", exc)
