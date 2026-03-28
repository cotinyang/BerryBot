"""StateMachine 单元测试。"""

import pytest

from client.state_machine import ClientState, StateMachine


class TestClientState:
    """ClientState 枚举测试。"""

    def test_all_states_exist(self) -> None:
        assert ClientState.STANDBY.value == "standby"
        assert ClientState.RECORDING.value == "recording"
        assert ClientState.WAITING_RESPONSE.value == "waiting"
        assert ClientState.PLAYING.value == "playing"
        assert ClientState.OFFLINE_STANDBY.value == "offline"


class TestStateMachineInit:
    """StateMachine 初始化测试。"""

    def test_initial_state_is_standby(self) -> None:
        sm = StateMachine()
        assert sm.state is ClientState.STANDBY


class TestStateMachineTransitions:
    """合法状态转换测试。"""

    @pytest.mark.parametrize(
        "from_state, to_state",
        [
            (ClientState.STANDBY, ClientState.RECORDING),
            (ClientState.RECORDING, ClientState.WAITING_RESPONSE),
            (ClientState.WAITING_RESPONSE, ClientState.PLAYING),
            (ClientState.PLAYING, ClientState.STANDBY),
            (ClientState.PLAYING, ClientState.RECORDING),
            (ClientState.STANDBY, ClientState.OFFLINE_STANDBY),
            (ClientState.OFFLINE_STANDBY, ClientState.STANDBY),
            (ClientState.RECORDING, ClientState.STANDBY),
            (ClientState.WAITING_RESPONSE, ClientState.STANDBY),
        ],
    )
    def test_valid_transition(
        self, from_state: ClientState, to_state: ClientState
    ) -> None:
        sm = StateMachine()
        # Navigate to from_state first
        _navigate_to(sm, from_state)
        sm.transition(to_state)
        assert sm.state is to_state

    @pytest.mark.parametrize(
        "from_state, to_state",
        [
            (ClientState.STANDBY, ClientState.WAITING_RESPONSE),
            (ClientState.STANDBY, ClientState.PLAYING),
            (ClientState.STANDBY, ClientState.STANDBY),
            (ClientState.RECORDING, ClientState.PLAYING),
            (ClientState.RECORDING, ClientState.RECORDING),
            (ClientState.RECORDING, ClientState.OFFLINE_STANDBY),
            (ClientState.WAITING_RESPONSE, ClientState.RECORDING),
            (ClientState.WAITING_RESPONSE, ClientState.WAITING_RESPONSE),
            (ClientState.WAITING_RESPONSE, ClientState.OFFLINE_STANDBY),
            (ClientState.PLAYING, ClientState.WAITING_RESPONSE),
            (ClientState.PLAYING, ClientState.PLAYING),
            (ClientState.PLAYING, ClientState.OFFLINE_STANDBY),
            (ClientState.OFFLINE_STANDBY, ClientState.RECORDING),
            (ClientState.OFFLINE_STANDBY, ClientState.OFFLINE_STANDBY),
            (ClientState.OFFLINE_STANDBY, ClientState.PLAYING),
            (ClientState.OFFLINE_STANDBY, ClientState.WAITING_RESPONSE),
        ],
    )
    def test_invalid_transition_raises(
        self, from_state: ClientState, to_state: ClientState
    ) -> None:
        sm = StateMachine()
        _navigate_to(sm, from_state)
        with pytest.raises(ValueError, match="Invalid transition"):
            sm.transition(to_state)
        # State should remain unchanged
        assert sm.state is from_state


class TestStateMachineCallbacks:
    """状态变更回调测试。"""

    def test_callback_receives_old_and_new_state(self) -> None:
        sm = StateMachine()
        calls: list[tuple[ClientState, ClientState]] = []
        sm.on_state_change(lambda old, new: calls.append((old, new)))

        sm.transition(ClientState.RECORDING)
        assert calls == [(ClientState.STANDBY, ClientState.RECORDING)]

    def test_multiple_callbacks(self) -> None:
        sm = StateMachine()
        calls_a: list[ClientState] = []
        calls_b: list[ClientState] = []
        sm.on_state_change(lambda _old, new: calls_a.append(new))
        sm.on_state_change(lambda _old, new: calls_b.append(new))

        sm.transition(ClientState.RECORDING)
        assert calls_a == [ClientState.RECORDING]
        assert calls_b == [ClientState.RECORDING]

    def test_no_callback_on_invalid_transition(self) -> None:
        sm = StateMachine()
        called = False

        def cb(_old: ClientState, _new: ClientState) -> None:
            nonlocal called
            called = True

        sm.on_state_change(cb)
        with pytest.raises(ValueError):
            sm.transition(ClientState.PLAYING)
        assert not called


# ── helpers ──────────────────────────────────────────────────────────

# Shortest paths from STANDBY to each state for test setup.
_ROUTES: dict[ClientState, list[ClientState]] = {
    ClientState.STANDBY: [],
    ClientState.RECORDING: [ClientState.RECORDING],
    ClientState.WAITING_RESPONSE: [
        ClientState.RECORDING,
        ClientState.WAITING_RESPONSE,
    ],
    ClientState.PLAYING: [
        ClientState.RECORDING,
        ClientState.WAITING_RESPONSE,
        ClientState.PLAYING,
    ],
    ClientState.OFFLINE_STANDBY: [ClientState.OFFLINE_STANDBY],
}


def _navigate_to(sm: StateMachine, target: ClientState) -> None:
    """Navigate the state machine from STANDBY to *target* via valid transitions."""
    for step in _ROUTES[target]:
        sm.transition(step)
