"""客户端状态机：管理所有状态转换。"""

import logging
from enum import Enum
from typing import Callable

logger = logging.getLogger(__name__)


class ClientState(Enum):
    """客户端状态枚举。"""

    STANDBY = "standby"  # 待机，监听唤醒词
    RECORDING = "recording"  # 录音中
    WAITING_RESPONSE = "waiting"  # 等待服务端响应
    PLAYING = "playing"  # 播放语音回复
    OFFLINE_STANDBY = "offline"  # 离线待机


# 合法状态转换表
_VALID_TRANSITIONS: dict[ClientState, set[ClientState]] = {
    ClientState.STANDBY: {ClientState.RECORDING, ClientState.OFFLINE_STANDBY},
    ClientState.RECORDING: {ClientState.WAITING_RESPONSE, ClientState.STANDBY},
    ClientState.WAITING_RESPONSE: {ClientState.PLAYING, ClientState.STANDBY},
    ClientState.PLAYING: {ClientState.STANDBY, ClientState.RECORDING},
    ClientState.OFFLINE_STANDBY: {ClientState.STANDBY},
}


class StateMachine:
    """客户端核心控制器，管理所有状态转换。"""

    def __init__(self) -> None:
        self._state = ClientState.STANDBY
        self._callbacks: list[Callable[[ClientState, ClientState], None]] = []

    @property
    def state(self) -> ClientState:
        """当前状态。"""
        return self._state

    def transition(self, new_state: ClientState) -> None:
        """执行状态转换。

        Args:
            new_state: 目标状态。

        Raises:
            ValueError: 当前状态不允许转换到目标状态时抛出。
        """
        allowed = _VALID_TRANSITIONS.get(self._state, set())
        if new_state not in allowed:
            raise ValueError(
                f"Invalid transition: {self._state.value} → {new_state.value}"
            )

        old_state = self._state
        self._state = new_state
        logger.info("状态转换: %s → %s", old_state.value, new_state.value)

        for callback in self._callbacks:
            callback(old_state, new_state)

    def on_state_change(
        self, callback: Callable[[ClientState, ClientState], None]
    ) -> None:
        """注册状态变更回调。

        Args:
            callback: 回调函数，接收 (旧状态, 新状态) 两个参数。
        """
        self._callbacks.append(callback)
