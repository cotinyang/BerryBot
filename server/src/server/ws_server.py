"""WebSocket 通信服务端：接收客户端音频数据并处理消息协议。"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import websockets
from websockets.asyncio.server import Server, ServerConnection

if TYPE_CHECKING:
    from server.ai_agent import AIAgent
    from server.speech_recognizer import SpeechRecognizer
    from server.speech_synthesizer import SpeechSynthesizer

logger = logging.getLogger(__name__)


def _text_preview(text: str, max_len: int = 200) -> str:
    """生成适合日志展示的文本预览，避免超长日志。"""
    normalized = " ".join(text.split())
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[:max_len]}..."


class WebSocketServer:
    """WebSocket 通信服务端。

    接收客户端发送的 JSON 元数据和二进制音频帧，
    通过语音识别→AI Agent→语音合成流水线处理音频，
    并将合成语音返回给客户端。支持打断取消。
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        speech_recognizer: SpeechRecognizer | None = None,
        ai_agent: AIAgent | None = None,
        speech_synthesizer: SpeechSynthesizer | None = None,
        auth_token: str = "",
        tls_cert_path: str = "",
        tls_key_path: str = "",
        debug_bypass_agent: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._server: Server | None = None
        self._speech_recognizer = speech_recognizer
        self._ai_agent = ai_agent
        self._speech_synthesizer = speech_synthesizer
        self._auth_token = auth_token
        self._tls_cert_path = tls_cert_path
        self._tls_key_path = tls_key_path
        self._debug_bypass_agent = debug_bypass_agent
        # Track per-client processing tasks for cancellation on interrupt
        self._client_tasks: dict[ServerConnection, asyncio.Task[None]] = {}

    async def start(self) -> None:
        """启动 WebSocket 服务端并开始监听连接。"""
        ssl_context = None
        if self._tls_cert_path and self._tls_key_path:
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ssl_context.load_cert_chain(self._tls_cert_path, self._tls_key_path)
            logger.info("TLS enabled with cert: %s", self._tls_cert_path)

        self._server = await websockets.serve(
            self.handle_client,
            self._host,
            self._port,
            ssl=ssl_context,
        )
        protocol = "wss" if ssl_context else "ws"
        logger.info("WebSocket server started on %s://%s:%d", protocol, self._host, self._port)

    async def stop(self) -> None:
        """停止 WebSocket 服务端并清理资源。"""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("WebSocket server stopped")

    async def handle_client(self, websocket: ServerConnection) -> None:
        """处理单个客户端连接的消息循环。

        按照消息协议解析 JSON 消息和二进制帧：
        - "audio" 类型：后续跟随一个二进制帧（WAV 音频数据）
        - "interrupt" 类型：取消当前正在进行的处理任务

        Args:
            websocket: 客户端 WebSocket 连接。
        """
        remote = websocket.remote_address
        logger.info("Client connected: %s", remote)

        # Token 认证
        if self._auth_token:
            params = parse_qs(urlparse(websocket.request.path).query)
            client_token = params.get("token", [""])[0]
            if client_token != self._auth_token:
                logger.warning("Auth failed from %s: invalid token", remote)
                await websocket.close(4001, "Unauthorized")
                return

        try:
            async for raw_message in websocket:
                # Binary frames outside of an expected sequence are ignored
                if isinstance(raw_message, bytes):
                    logger.warning("Unexpected binary frame from %s, ignoring", remote)
                    continue

                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from %s: %s", remote, raw_message[:200])
                    await self._send_error(websocket, "invalid_message", "无法解析消息")
                    continue

                msg_type = message.get("type")

                if msg_type == "audio":
                    await self._handle_audio(websocket, message)
                elif msg_type == "interrupt":
                    await self.handle_interrupt(websocket)
                else:
                    logger.warning("Unknown message type from %s: %s", remote, msg_type)
                    await self._send_error(
                        websocket, "unknown_type", f"未知消息类型: {msg_type}"
                    )
        except websockets.ConnectionClosed:
            logger.info("Client disconnected: %s", remote)
        except Exception as exc:
            logger.error("Error handling client %s: %s", remote, exc)
        finally:
            # Cancel any in-flight processing task for this client
            task = self._client_tasks.pop(websocket, None)
            if task is not None and not task.done():
                task.cancel()
            logger.info("Client session cleaned up: %s", remote)

    async def handle_interrupt(self, websocket: ServerConnection) -> None:
        """处理客户端打断通知，取消当前处理任务。

        Args:
            websocket: 发送打断通知的客户端连接。
        """
        task = self._client_tasks.pop(websocket, None)
        if task is not None and not task.done():
            task.cancel()
            logger.info("Cancelled processing task for %s due to interrupt", websocket.remote_address)
        else:
            logger.debug("Interrupt received from %s but no active task", websocket.remote_address)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _handle_audio(
        self, websocket: ServerConnection, metadata: dict
    ) -> None:
        """处理音频消息：接收元数据后等待二进制音频帧。

        Args:
            websocket: 客户端连接。
            metadata: 已解析的 JSON 元数据（包含 format、sample_rate 等）。
        """
        remote = websocket.remote_address
        audio_format = metadata.get("format", "wav")
        sample_rate = metadata.get("sample_rate", 16000)

        try:
            audio_data = await asyncio.wait_for(websocket.recv(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for audio binary frame from %s", remote)
            await self._send_error(websocket, "timeout", "等待音频数据超时")
            return

        if not isinstance(audio_data, bytes):
            logger.warning("Expected binary audio frame from %s, got text", remote)
            await self._send_error(websocket, "invalid_message", "期望二进制音频帧")
            return

        logger.info(
            "Received audio from %s: format=%s, sample_rate=%d, size=%d bytes",
            remote,
            audio_format,
            sample_rate,
            len(audio_data),
        )

        # Cancel any previous processing task before starting a new one
        prev_task = self._client_tasks.pop(websocket, None)
        if prev_task is not None and not prev_task.done():
            prev_task.cancel()

        # Create a processing task that can be cancelled on interrupt.
        task = asyncio.create_task(
            self._process_audio(websocket, audio_data, audio_format, sample_rate)
        )
        self._client_tasks[websocket] = task

    async def _process_audio(
        self,
        websocket: ServerConnection,
        audio_data: bytes,
        audio_format: str,
        sample_rate: int,
    ) -> None:
        """处理接收到的音频数据：识别→AI Agent→合成→返回语音。

        Args:
            websocket: 客户端连接。
            audio_data: 二进制音频数据。
            audio_format: 音频格式（如 "wav"）。
            sample_rate: 采样率。
        """
        logger.info(
            "Processing audio: format=%s, sample_rate=%d, size=%d bytes",
            audio_format,
            sample_rate,
            len(audio_data),
        )

        try:
            # Step 1: Send "processing" status
            await self._send_status(websocket, "processing")

            # Step 2: Speech recognition
            if self._speech_recognizer is None:
                await self._send_error(websocket, "recognition_failed", "语音识别服务未配置")
                return
            try:
                text = self._speech_recognizer.recognize(audio_data)
                logger.info(
                    "ASR result from %s: len=%d text=\"%s\"",
                    websocket.remote_address,
                    len(text),
                    _text_preview(text),
                )
            except ValueError as e:
                logger.warning("语音识别结果为空: %s", e)
                await self._send_error(websocket, "recognition_failed", str(e))
                return
            except (RuntimeError, Exception) as e:
                logger.error("语音识别错误: %s", e)
                await self._send_error(websocket, "recognition_failed", f"语音识别错误: {e}")
                return

            # Step 3: AI Agent processing (or bypass in debug mode)
            if self._debug_bypass_agent:
                response_text = text
                logger.info(
                    "Debug bypass enabled for %s: echo ASR text to TTS, text=\"%s\"",
                    websocket.remote_address,
                    _text_preview(response_text),
                )
            else:
                if self._ai_agent is None:
                    await self._send_error(websocket, "agent_error", "AI Agent 服务未配置")
                    return
                try:
                    response_text = await self._ai_agent.process(text)
                    logger.info(
                        "Agent response for %s: len=%d text=\"%s\"",
                        websocket.remote_address,
                        len(response_text),
                        _text_preview(response_text),
                    )
                except (RuntimeError, Exception) as e:
                    logger.error("AI Agent 处理错误: %s", e)
                    await self._send_error(websocket, "agent_error", f"AI Agent 处理错误: {e}")
                    return

                # Step 3.5: Check if Agent returned a command instead of text
                from server.session_tools import is_command, parse_command
                if is_command(response_text):
                    action = parse_command(response_text)
                    logger.info("Agent 返回指令: %s", action)
                    await self._send_command(websocket, action)
                    return

            # Step 4: Send "synthesizing" status
            await self._send_status(websocket, "synthesizing")
            logger.info(
                "TTS input for %s: len=%d text=\"%s\"",
                websocket.remote_address,
                len(response_text),
                _text_preview(response_text),
            )

            # Step 5: Speech synthesis
            if self._speech_synthesizer is None:
                await self._send_error(websocket, "synthesis_error", "语音合成服务未配置")
                return
            try:
                # Step 6: Stream audio response metadata + chunks
                chunk_count = 0
                total_bytes = 0
                stream_started = False
                synth_type = type(self._speech_synthesizer)
                supports_segment_meta = (
                    callable(getattr(synth_type, "iter_segments", None))
                    and callable(getattr(synth_type, "synthesize_segment_stream", None))
                )

                if supports_segment_meta:
                    segments = self._speech_synthesizer.iter_segments(response_text)
                    for segment_id, segment_text in enumerate(segments, start=1):
                        segment_chunk_count = 0
                        if not stream_started:
                            await websocket.send(json.dumps({
                                "type": "audio_response",
                                "format": "mp3",
                                "stream": True,
                                "segment_batch": True,
                            }))
                            stream_started = True

                        await websocket.send(json.dumps({
                            "type": "audio_segment_start",
                            "segment_id": segment_id,
                            "text_len": len(segment_text),
                        }))

                        async for chunk in self._speech_synthesizer.synthesize_segment_stream(segment_text):
                            chunk_count += 1
                            segment_chunk_count += 1
                            total_bytes += len(chunk)
                            await websocket.send(json.dumps({
                                "type": "audio_chunk",
                                "seq": chunk_count,
                                "segment_id": segment_id,
                            }))
                            await websocket.send(chunk)

                        await websocket.send(json.dumps({
                            "type": "audio_segment_end",
                            "segment_id": segment_id,
                            "chunks": segment_chunk_count,
                        }))
                else:
                    async for chunk in self._speech_synthesizer.synthesize_stream(response_text):
                        if not stream_started:
                            await websocket.send(json.dumps({
                                "type": "audio_response",
                                "format": "mp3",
                                "stream": True,
                            }))
                            stream_started = True

                        chunk_count += 1
                        total_bytes += len(chunk)
                        await websocket.send(json.dumps({
                            "type": "audio_chunk",
                            "seq": chunk_count,
                        }))
                        await websocket.send(chunk)

                if chunk_count == 0:
                    raise RuntimeError("语音合成未产生音频数据")

                await websocket.send(json.dumps({
                    "type": "audio_end",
                    "format": "mp3",
                    "chunks": chunk_count,
                }))
            except (ValueError, RuntimeError, Exception) as e:
                logger.error("语音合成错误: %s", e)
                await self._send_error(websocket, "synthesis_error", f"语音合成错误: {e}")
                return
            logger.info(
                "Audio stream sent to %s: chunks=%d, size=%d bytes",
                websocket.remote_address,
                chunk_count,
                total_bytes,
            )

        except asyncio.CancelledError:
            logger.info("Processing cancelled (interrupt) for %s", websocket.remote_address)
            raise

    async def _send_status(
        self, websocket: ServerConnection, status: str
    ) -> None:
        """向客户端发送状态消息。

        Args:
            websocket: 客户端连接。
            status: 状态字符串（如 "processing"、"synthesizing"）。
        """
        status_msg = json.dumps({
            "type": "status",
            "status": status,
        })
        try:
            await websocket.send(status_msg)
        except Exception as exc:
            logger.warning("Failed to send status to client: %s", exc)

    async def _send_command(
        self, websocket: ServerConnection, action: str, **kwargs: str
    ) -> None:
        """向客户端发送控制指令。

        Args:
            websocket: 客户端连接。
            action: 指令名称（如 "end_session"）。
            **kwargs: 额外参数。
        """
        msg = {"type": "command", "action": action, **kwargs}
        try:
            await websocket.send(json.dumps(msg))
            logger.info("Command sent to %s: %s", websocket.remote_address, action)
        except Exception as exc:
            logger.warning("Failed to send command to client: %s", exc)

    async def _send_error(
        self, websocket: ServerConnection, code: str, message: str
    ) -> None:
        """向客户端发送错误消息。

        Args:
            websocket: 客户端连接。
            code: 错误代码。
            message: 人类可读的错误描述。
        """
        error_msg = json.dumps({
            "type": "error",
            "code": code,
            "message": message,
        })
        try:
            await websocket.send(error_msg)
        except Exception as exc:
            logger.warning("Failed to send error to client: %s", exc)
