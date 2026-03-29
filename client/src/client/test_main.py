"""客户端主控流程 (main.py) 单元测试。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from client.config import ClientConfig
from client.main import VoiceAssistantClient, parse_args
from client.state_machine import ClientState


def _make_config(**overrides) -> ClientConfig:
    """创建测试用 ClientConfig。"""
    defaults = {
        "server_url": "ws://localhost:8765",
        "wake_word_engine": "sherpa_onnx",
        "wake_word_keywords": "小艺小艺",
    }
    defaults.update(overrides)
    return ClientConfig(**defaults)


class TestParseArgs:
    def test_required_args(self):
        config = parse_args([
            "--server-url", "ws://host:8765",
        ])
        assert config.server_url == "ws://host:8765"
        assert config.wake_word_engine == "sherpa_onnx"
        assert config.wake_word_keywords == "小艺小艺"

    def test_default_values(self):
        config = parse_args([
            "--server-url", "ws://host:8765",
        ])
        assert config.wake_prompt_audio_path == "assets/wo_zai.mp3"
        assert config.wake_prompt_delay == 0.3
        assert config.silence_threshold == 1.5
        assert config.max_recording_duration == 10.0
        assert config.sample_rate == 16000
        assert config.energy_threshold == 500.0
        assert config.enable_gentle_trim is True
        assert config.trim_frame_ms == 20
        assert config.trim_min_silence_sec == 0.35
        assert config.trim_padding_sec == 0.25
        assert config.trim_energy_ratio == 0.6
        assert config.use_webrtc_vad is True
        assert config.webrtc_vad_mode == 2
        assert config.interrupt_grace_period == 0.8
        assert config.interrupt_min_voice_duration == 0.3
        assert config.reconnect_interval == 5.0
        assert config.max_reconnect_retries == 3
        assert config.ws_max_message_size == 8 * 1024 * 1024

    def test_custom_values(self):
        config = parse_args([
            "--server-url", "ws://host:9999",
            "--wake-word-engine", "porcupine",
            "--wake-word-access-key", "key123",
            "--wake-word-keyword-path", "/kw.ppn",
            "--silence-threshold", "2.0",
            "--max-recording-duration", "8.0",
            "--energy-threshold", "800.0",
            "--no-enable-gentle-trim",
            "--trim-frame-ms", "30",
            "--trim-min-silence-sec", "0.5",
            "--trim-padding-sec", "0.4",
            "--trim-energy-ratio", "0.7",
            "--webrtc-vad-mode", "3",
            "--no-use-webrtc-vad",
            "--interrupt-grace-period", "1.0",
            "--interrupt-min-voice-duration", "0.5",
            "--reconnect-interval", "10.0",
            "--max-reconnect-retries", "5",
            "--ws-max-message-size", "16777216",
        ])
        assert config.silence_threshold == 2.0
        assert config.max_recording_duration == 8.0
        assert config.energy_threshold == 800.0
        assert config.enable_gentle_trim is False
        assert config.trim_frame_ms == 30
        assert config.trim_min_silence_sec == 0.5
        assert config.trim_padding_sec == 0.4
        assert config.trim_energy_ratio == 0.7
        assert config.use_webrtc_vad is False
        assert config.webrtc_vad_mode == 3
        assert config.interrupt_grace_period == 1.0
        assert config.interrupt_min_voice_duration == 0.5
        assert config.reconnect_interval == 10.0
        assert config.max_reconnect_retries == 5
        assert config.ws_max_message_size == 16777216

    def test_missing_required_args_exits(self):
        with pytest.raises(SystemExit):
            parse_args([])


class TestVoiceAssistantClientInit:
    def test_initializes_all_components(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        assert client.state_machine.state == ClientState.STANDBY
        assert client._ws_client is not None
        assert client._wake_word_detector is not None
        assert client._audio_recorder is not None
        assert client._audio_player is not None
        assert client._interrupt_handler is not None


class TestStartAndConnect:
    @pytest.mark.asyncio
    async def test_start_connects_to_server(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._ws_client.connect = AsyncMock()
        client._wake_word_detector.start_listening = AsyncMock()

        # start() blocks on _stop_event, so run it as a task and stop quickly
        task = asyncio.create_task(client.start())
        await asyncio.sleep(0.05)
        await client.stop()
        await task

        client._ws_client.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_connection_failure_goes_offline(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._ws_client.connect = AsyncMock(side_effect=ConnectionError("refused"))
        client._wake_word_detector.start_listening = AsyncMock()

        task = asyncio.create_task(client.start())
        await asyncio.sleep(0.05)
        await client.stop()
        await task

        assert client.state_machine.state == ClientState.OFFLINE_STANDBY


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_releases_all_resources(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._wake_word_detector.stop_listening = AsyncMock()
        client._audio_recorder.stop_recording = AsyncMock(return_value=b"")
        client._audio_player.stop = AsyncMock()
        client._interrupt_handler.stop_monitoring = AsyncMock()
        client._ws_client.disconnect = AsyncMock()

        await client.stop()

        client._wake_word_detector.stop_listening.assert_awaited_once()
        client._audio_player.stop.assert_awaited_once()
        client._interrupt_handler.stop_monitoring.assert_awaited_once()
        client._ws_client.disconnect.assert_awaited_once()


class TestCallbacks:
    @pytest.mark.asyncio
    async def test_on_playback_complete_transitions_to_listening(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        # Force state to PLAYING
        client._state_machine._state = ClientState.PLAYING
        client._handle_listening = AsyncMock()
        client._on_playback_complete()
        for task in list(client._background_tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        assert client.state_machine.state == ClientState.LISTENING

    def test_on_playback_complete_ignored_if_not_playing(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        # State is STANDBY, callback should be a no-op
        client._on_playback_complete()
        assert client.state_machine.state == ClientState.STANDBY

    def test_on_connection_failed_transitions_to_offline(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._on_connection_failed()
        assert client.state_machine.state == ClientState.OFFLINE_STANDBY

    def test_on_reconnect_transitions_to_standby(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._state_machine._state = ClientState.OFFLINE_STANDBY
        client._on_reconnect()
        assert client.state_machine.state == ClientState.STANDBY

    def test_on_reconnect_ignored_if_not_offline(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        # State is STANDBY, should remain STANDBY
        client._on_reconnect()
        assert client.state_machine.state == ClientState.STANDBY

    def test_on_wake_word_ignored_if_not_standby(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._state_machine._state = ClientState.RECORDING
        # Should not start interaction
        with patch.object(client, "_handle_interaction", new_callable=AsyncMock) as mock_handle:
            client._on_wake_word()
            # ensure_future not called since state != STANDBY
            # _handle_interaction should not be scheduled

    def test_on_interrupt_ignored_when_task_running(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._state_machine._state = ClientState.PLAYING

        running_task = MagicMock()
        running_task.done.return_value = False
        client._interrupt_task = running_task

        with patch("client.main.asyncio.ensure_future") as mock_ensure:
            client._on_interrupt()
            mock_ensure.assert_not_called()


class TestHandleInteraction:
    @pytest.mark.asyncio
    async def test_full_interaction_flow(self):
        """测试完整交互流程：唤醒 → 提示音 → 录音 → 发送 → 等待 → 播放。"""
        config = _make_config()
        client = VoiceAssistantClient(config)

        # Mock all components
        with patch("client.main.handle_wake_prompt", new_callable=AsyncMock, return_value=False) as mock_wake_prompt:
            client._wake_word_detector.stop_listening = AsyncMock()
            client._audio_recorder.start_recording = AsyncMock()
            client._audio_recorder.stop_recording = AsyncMock(return_value=b"wav-data")
            client._ws_client._connected = True
            client._ws_client._ws = MagicMock()
            client._ws_client.send_audio = AsyncMock()
            client._ws_client.receive_response = AsyncMock(
                return_value={"type": "audio", "action": "", "data": b"mp3-data"}
            )
            client._audio_player.play = AsyncMock()
            client._interrupt_handler.start_monitoring = AsyncMock()
            client._interrupt_handler.stop_monitoring = AsyncMock()

            await client._handle_interaction()

            mock_wake_prompt.assert_awaited_once_with(
                client._interrupt_handler,
                client._audio_player,
                config,
                wait_for_prompt_playback=False,
            )
            client._audio_recorder.start_recording.assert_awaited_once()
            client._ws_client.send_audio.assert_awaited_once_with(b"wav-data")
            client._ws_client.receive_response.assert_awaited_once()
            client._audio_player.play.assert_awaited_once_with(b"mp3-data")

    @pytest.mark.asyncio
    async def test_full_interaction_flow_streaming_audio(self):
        """测试流式响应时应调用 play_stream。"""
        config = _make_config()
        client = VoiceAssistantClient(config)

        async def fake_stream():
            yield b"chunk-1"
            yield b"chunk-2"

        with patch("client.main.handle_wake_prompt", new_callable=AsyncMock, return_value=False):
            client._wake_word_detector.stop_listening = AsyncMock()
            client._audio_recorder.start_recording = AsyncMock()
            client._audio_recorder.stop_recording = AsyncMock(return_value=b"wav-data")
            client._ws_client._connected = True
            client._ws_client._ws = MagicMock()
            client._ws_client.send_audio = AsyncMock()
            client._ws_client.receive_response = AsyncMock(
                return_value={
                    "type": "audio_stream",
                    "action": "",
                    "data": None,
                    "stream": fake_stream(),
                    "format": "mp3",
                }
            )
            client._audio_player.play_stream = AsyncMock()
            client._audio_player.play = AsyncMock()
            client._interrupt_handler.start_monitoring = AsyncMock()
            client._interrupt_handler.stop_monitoring = AsyncMock()

            await client._handle_interaction()

            client._audio_player.play_stream.assert_awaited_once()
            client._audio_player.play.assert_not_called()

    @pytest.mark.asyncio
    async def test_interaction_connection_error_returns_to_standby(self):
        """通信错误时应返回待机状态。"""
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._wake_word_detector.stop_listening = AsyncMock()
        client._wake_word_detector.start_listening = AsyncMock()

        with patch("client.main.handle_wake_prompt", new_callable=AsyncMock, return_value=False):
            client._audio_recorder.start_recording = AsyncMock()
            client._audio_recorder.stop_recording = AsyncMock(return_value=b"wav-data")
            client._ws_client._connected = False
            client._ws_client._ws = None
            client._audio_player.play = AsyncMock()

            await client._handle_interaction()

            assert client.state_machine.state == ClientState.STANDBY

            assert client.state_machine.state == ClientState.STANDBY

    @pytest.mark.asyncio
    async def test_interaction_server_error_returns_to_standby(self):
        """服务端错误时应返回待机状态。"""
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._wake_word_detector.stop_listening = AsyncMock()
        client._wake_word_detector.start_listening = AsyncMock()

        with patch("client.main.handle_wake_prompt", new_callable=AsyncMock, return_value=False):
            client._audio_recorder.start_recording = AsyncMock()
            client._audio_recorder.stop_recording = AsyncMock(return_value=b"wav-data")
            client._ws_client._connected = True
            client._ws_client._ws = MagicMock()
            client._ws_client.send_audio = AsyncMock()
            client._ws_client.receive_response = AsyncMock(
                side_effect=RuntimeError("Server error [agent_error]: 处理失败")
            )
            client._audio_player.play = AsyncMock()

            await client._handle_interaction()

            assert client.state_machine.state == ClientState.STANDBY

    @pytest.mark.asyncio
    async def test_do_record_send_play_drops_response_when_state_changed(self):
        """等待响应期间若状态已变化，应丢弃响应而不进入播放。"""
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._state_machine._state = ClientState.RECORDING

        client._audio_recorder.start_recording = AsyncMock()
        client._audio_recorder.stop_recording = AsyncMock(return_value=b"wav-data")
        client._ws_client._connected = True
        client._ws_client._ws = MagicMock()
        client._ws_client.send_audio = AsyncMock()

        async def _fake_receive_response():
            client._state_machine._state = ClientState.STANDBY
            return {"type": "audio", "action": "", "data": b"mp3-data"}

        client._ws_client.receive_response = AsyncMock(side_effect=_fake_receive_response)
        client._audio_player.play = AsyncMock()
        client._interrupt_handler.start_monitoring = AsyncMock()
        client._interrupt_handler.stop_monitoring = AsyncMock()

        await client._do_record_send_play()

        client._audio_player.play.assert_not_called()


class TestHandleInterrupt:
    @pytest.mark.asyncio
    async def test_interrupt_stops_playback_and_records(self):
        """打断应停止播放、发送 interrupt、开始录音。"""
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._state_machine._state = ClientState.PLAYING

        client._audio_player.stop = AsyncMock()
        client._interrupt_handler.stop_monitoring = AsyncMock()
        client._ws_client._connected = True
        client._ws_client._ws = MagicMock()
        client._ws_client.send_interrupt = AsyncMock()
        client._audio_recorder.start_recording = AsyncMock()
        client._audio_recorder.stop_recording = AsyncMock(return_value=b"new-wav")
        client._ws_client.send_audio = AsyncMock()
        client._ws_client.receive_response = AsyncMock(
            return_value={"type": "audio", "action": "", "data": b"new-mp3"}
        )
        client._audio_player.play = AsyncMock()
        client._interrupt_handler.start_monitoring = AsyncMock()

        await client._handle_interrupt()

        client._audio_player.stop.assert_awaited()
        client._ws_client.send_interrupt.assert_awaited_once()
        client._audio_recorder.start_recording.assert_awaited_once()
        client._ws_client.send_audio.assert_awaited_once_with(b"new-wav")

    @pytest.mark.asyncio
    async def test_interrupt_connection_error_returns_to_standby(self):
        """打断后通信错误应返回待机。"""
        config = _make_config()
        client = VoiceAssistantClient(config)
        client._state_machine._state = ClientState.PLAYING
        client._wake_word_detector.start_listening = AsyncMock()

        client._audio_player.stop = AsyncMock()
        client._audio_player.play = AsyncMock()
        client._interrupt_handler.stop_monitoring = AsyncMock()
        client._ws_client._connected = True
        client._ws_client._ws = MagicMock()
        client._ws_client.send_interrupt = AsyncMock(
            side_effect=ConnectionError("broken")
        )

        await client._handle_interrupt()

        assert client.state_machine.state == ClientState.STANDBY


class TestSafeTransition:
    def test_safe_transition_ignores_invalid(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        # STANDBY → PLAYING is invalid, should not raise
        client._safe_transition(ClientState.PLAYING)
        assert client.state_machine.state == ClientState.STANDBY

    def test_safe_transition_skips_same_state(self):
        config = _make_config()
        client = VoiceAssistantClient(config)
        # Already STANDBY, should be a no-op
        client._safe_transition(ClientState.STANDBY)
        assert client.state_machine.state == ClientState.STANDBY
