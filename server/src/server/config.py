"""服务端配置数据模型。"""

from dataclasses import dataclass


@dataclass
class ServerConfig:
    """服务端配置。"""

    host: str = "0.0.0.0"
    port: int = 8765
    whisper_model_size: str = "base"
    whisper_language: str = "zh"
    tts_voice: str = "zh-CN-XiaoxiaoNeural"
    tts_sentence_stream: bool = True        # 按句分段 TTS，降低长段中途卡顿
    tts_sentence_max_chars: int = 80        # 单句过长时的最大切分长度
    soul_path: str = "SOUL.md"
    memory_path: str = "MEMORY.md"
    auth_token: str = ""                   # 预共享认证 token
    tls_cert_path: str = ""               # TLS 证书文件路径 (fullchain.pem)
    tls_key_path: str = ""                # TLS 私钥文件路径 (privkey.pem)
    debug_bypass_agent: bool = False       # 调试开关: 跳过 Agent，识别文本直接 TTS
