"""客户端配置数据模型。"""

from dataclasses import dataclass


@dataclass
class ClientConfig:
    """客户端配置。"""

    server_url: str
    wake_word_engine: str = "sherpa_onnx"  # "porcupine" | "sherpa_onnx"
    # Porcupine 配置
    wake_word_access_key: str = ""
    wake_word_keyword_path: str = ""
    # Sherpa-onnx 配置
    wake_word_keywords: str = "小艺小艺"   # 逗号分隔的唤醒词列表
    wake_word_model_path: str = ""         # sherpa-onnx 关键词检测模型路径（留空自动下载）
    auth_token: str = ""                   # 预共享认证 token
    wake_prompt_audio_path: str = "assets/wo_zai.mp3"
    wake_prompt_delay: float = 0.3
    silence_threshold: float = 1.5
    max_recording_duration: float = 10.0
    sample_rate: int = 16000
    energy_threshold: float = 500.0
    enable_gentle_trim: bool = True
    trim_frame_ms: int = 20
    trim_min_silence_sec: float = 0.35
    trim_padding_sec: float = 0.25
    trim_energy_ratio: float = 0.6
    use_webrtc_vad: bool = True
    webrtc_vad_mode: int = 2
    interrupt_grace_period: float = 0.8
    interrupt_min_voice_duration: float = 0.3
    reconnect_interval: float = 5.0
    max_reconnect_retries: int = 3
    ws_max_message_size: int = 8 * 1024 * 1024
    session_timeout: float = 5.0               # 连续对话超时（秒），超时后结束会话
    session_end_audio_path: str = "assets/end.wav"  # 会话结束提示音
    audio_player_command: str = ""            # 自定义播放器命令，支持 {file}
    audio_output_device: str = ""             # 播放设备名称（如 bluealsa）
