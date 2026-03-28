"""AIAgent 单元测试。"""

from unittest.mock import MagicMock, patch

import pytest

from server.ai_agent import AIAgent


class TestAIAgentInit:
    """初始化测试。"""

    def test_default_config(self):
        agent = AIAgent()
        assert str(agent._soul_path) == "SOUL.md"
        assert str(agent._memory_path) == "MEMORY.md"
        assert agent._tools == []
        assert agent._agent is None

    def test_custom_paths(self):
        agent = AIAgent(soul_path="/tmp/soul.md", memory_path="/tmp/mem.md")
        assert str(agent._soul_path) == "/tmp/soul.md"
        assert str(agent._memory_path) == "/tmp/mem.md"

    def test_custom_tools(self):
        tools = [MagicMock(), MagicMock()]
        agent = AIAgent(tools=tools)
        assert agent._tools is tools


class TestLoadSoul:
    """_load_soul 方法测试。"""

    def test_load_existing_soul(self, tmp_path):
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("你是一个温暖的助手。", encoding="utf-8")
        agent = AIAgent(soul_path=str(soul_file))
        assert agent._load_soul() == "你是一个温暖的助手。"

    def test_missing_soul_returns_default(self, tmp_path):
        agent = AIAgent(soul_path=str(tmp_path / "nonexistent.md"))
        result = agent._load_soul()
        assert "中文语音助手" in result

    def test_read_error_returns_default(self, tmp_path):
        """读取出错时返回默认提示。"""
        soul_dir = tmp_path / "SOUL.md"
        soul_dir.mkdir()  # 创建目录而非文件，触发 OSError
        agent = AIAgent(soul_path=str(soul_dir))
        result = agent._load_soul()
        assert "中文语音助手" in result


class TestLoadMemory:
    """_load_memory 方法测试。"""

    def test_load_existing_memory(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("# 记忆\n用户喜欢猫", encoding="utf-8")
        agent = AIAgent(memory_path=str(mem_file))
        assert "用户喜欢猫" in agent._load_memory()

    def test_missing_memory_returns_empty(self, tmp_path):
        agent = AIAgent(memory_path=str(tmp_path / "nonexistent.md"))
        assert agent._load_memory() == ""

    def test_read_error_returns_empty(self, tmp_path):
        mem_dir = tmp_path / "MEMORY.md"
        mem_dir.mkdir()
        agent = AIAgent(memory_path=str(mem_dir))
        assert agent._load_memory() == ""


class TestUpdateMemory:
    """_update_memory 方法测试。"""

    def test_write_memory(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        agent = AIAgent(memory_path=str(mem_file))
        agent._update_memory("# 记忆\n用户喜欢狗")
        assert mem_file.read_text(encoding="utf-8") == "# 记忆\n用户喜欢狗"

    def test_overwrite_memory(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("旧内容", encoding="utf-8")
        agent = AIAgent(memory_path=str(mem_file))
        agent._update_memory("新内容")
        assert mem_file.read_text(encoding="utf-8") == "新内容"

    def test_write_error_logged(self, tmp_path):
        """写入失败时不抛异常，仅记录日志。"""
        agent = AIAgent(memory_path="/nonexistent_dir/MEMORY.md")
        # 不应抛出异常
        agent._update_memory("内容")


class TestEnsureAgent:
    """_ensure_agent 方法测试。"""

    @patch("server.ai_agent.AIAgent._load_soul", return_value="你是助手")
    def test_lazy_init(self, mock_soul):
        agent = AIAgent()
        assert agent._agent is None

        mock_agent_cls = MagicMock()
        mock_agent_instance = MagicMock()
        mock_agent_cls.return_value = mock_agent_instance

        with patch.dict(
            "sys.modules",
            {"strands": MagicMock(Agent=mock_agent_cls)},
        ):
            agent._ensure_agent()

        assert agent._agent is mock_agent_instance
        mock_agent_cls.assert_called_once_with(
            system_prompt="你是助手",
            tools=[],
        )

    def test_agent_loaded_only_once(self):
        agent = AIAgent()
        mock_agent = MagicMock()
        agent._agent = mock_agent
        agent._ensure_agent()
        assert agent._agent is mock_agent

    @patch.dict("sys.modules", {"strands": None})
    def test_import_error_when_not_installed(self):
        agent = AIAgent()
        with pytest.raises(ImportError, match="strands-agents 未安装"):
            agent._ensure_agent()

    @patch("server.ai_agent.AIAgent._load_soul", return_value="你是助手")
    def test_tools_passed_to_agent(self, mock_soul):
        tools = [MagicMock()]
        agent = AIAgent(tools=tools)

        mock_agent_cls = MagicMock()
        with patch.dict(
            "sys.modules",
            {"strands": MagicMock(Agent=mock_agent_cls)},
        ):
            agent._ensure_agent()

        mock_agent_cls.assert_called_once_with(
            system_prompt="你是助手",
            tools=tools,
        )


class TestProcess:
    """process 方法测试。"""

    def _make_agent(self, tmp_path, soul_text="你是助手", memory_text=""):
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text(soul_text, encoding="utf-8")
        mem_file = tmp_path / "MEMORY.md"
        if memory_text:
            mem_file.write_text(memory_text, encoding="utf-8")
        agent = AIAgent(soul_path=str(soul_file), memory_path=str(mem_file))
        mock_strands_agent = MagicMock()
        agent._agent = mock_strands_agent
        return agent, mock_strands_agent

    @pytest.mark.asyncio
    async def test_process_without_memory(self, tmp_path):
        agent, mock_strands = self._make_agent(tmp_path)
        mock_strands.return_value = "你好！有什么可以帮你的？"

        result = await agent.process("你好")

        assert result == "你好！有什么可以帮你的？"
        mock_strands.assert_called_once_with("你好")

    @pytest.mark.asyncio
    async def test_process_with_memory(self, tmp_path):
        agent, mock_strands = self._make_agent(
            tmp_path, memory_text="# 记忆\n用户喜欢猫"
        )
        mock_strands.return_value = "好的，猫主人！"

        result = await agent.process("你好")

        assert result == "好的，猫主人！"
        call_arg = mock_strands.call_args[0][0]
        assert "[记忆上下文]" in call_arg
        assert "用户喜欢猫" in call_arg
        assert "[用户输入]" in call_arg
        assert "你好" in call_arg

    @pytest.mark.asyncio
    async def test_process_error_raises_runtime_error(self, tmp_path):
        agent, mock_strands = self._make_agent(tmp_path)
        mock_strands.side_effect = Exception("API 调用失败")

        with pytest.raises(RuntimeError, match="AI Agent 处理错误"):
            await agent.process("你好")

    @pytest.mark.asyncio
    async def test_process_returns_string(self, tmp_path):
        """即使 Agent 返回非字符串，process 也应返回字符串。"""
        agent, mock_strands = self._make_agent(tmp_path)
        mock_result = MagicMock()
        mock_result.__str__ = lambda self: "转换后的回复"
        mock_strands.return_value = mock_result

        result = await agent.process("测试")
        assert isinstance(result, str)
        assert result == "转换后的回复"

    @pytest.mark.asyncio
    async def test_import_error_propagated(self):
        agent = AIAgent()
        with patch.dict("sys.modules", {"strands": None}):
            with pytest.raises(ImportError, match="strands-agents 未安装"):
                await agent.process("你好")
