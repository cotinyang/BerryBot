"""客户端数据模型：音频数据与 WebSocket 消息。"""

from dataclasses import dataclass, field


@dataclass
class AudioData:
    """音频数据。"""

    raw_bytes: bytes
    format: str  # "wav" | "mp3"
    sample_rate: int
    channels: int = 1
    sample_width: int = 2  # 16-bit


@dataclass
class WSMessage:
    """WebSocket 基础消息。"""

    type: str
    payload: dict = field(default_factory=dict)


@dataclass
class WSAudioMessage(WSMessage):
    """WebSocket 音频消息。"""

    format: str = "wav"
    sample_rate: int = 16000


@dataclass
class WSErrorMessage(WSMessage):
    """WebSocket 错误消息。"""

    code: str = ""
    message: str = ""


@dataclass
class WSStatusMessage(WSMessage):
    """WebSocket 状态消息。"""

    status: str = ""
