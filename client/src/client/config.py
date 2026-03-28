"""客户端配置数据模型。"""

from dataclasses import dataclass


@dataclass
class ClientConfig:
    """客户端配置。"""

    server_url: str
    wake_word_access_key: str
    wake_word_keyword_path: str
    auth_token: str = ""                   # 预共享认证 token
    wake_prompt_audio_path: str = "assets/wo_zai.wav"
    wake_prompt_delay: float = 0.3
    silence_threshold: float = 1.5
    sample_rate: int = 16000
    energy_threshold: float = 500.0
    reconnect_interval: float = 5.0
    max_reconnect_retries: int = 3
