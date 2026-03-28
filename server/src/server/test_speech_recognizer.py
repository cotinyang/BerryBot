"""SpeechRecognizer 单元测试。"""

import os
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from server.speech_recognizer import SpeechRecognizer


@dataclass
class FakeSegment:
    """模拟 pywhispercpp 返回的转录片段。"""
    text: str


class TestSpeechRecognizerInit:
    """初始化测试。"""

    def test_default_config(self):
        recognizer = SpeechRecognizer()
        assert recognizer._model_size == "base"
        assert recognizer._language == "zh"
        assert recognizer._model is None

    def test_custom_config(self):
        recognizer = SpeechRecognizer(model_size="large", language="en")
        assert recognizer._model_size == "large"
        assert recognizer._language == "en"


class TestEnsureModel:
    """模型加载测试。"""

    @patch("server.speech_recognizer.Model", create=True)
    def test_lazy_load_model(self, mock_model_cls):
        """模型应在首次调用时延迟加载。"""
        mock_instance = MagicMock()
        mock_model_cls.return_value = mock_instance

        recognizer = SpeechRecognizer(model_size="tiny")
        assert recognizer._model is None

        with patch.dict(
            "sys.modules",
            {"pywhispercpp": MagicMock(), "pywhispercpp.model": MagicMock(Model=mock_model_cls)},
        ):
            recognizer._ensure_model()

        assert recognizer._model is mock_instance
        mock_model_cls.assert_called_once_with("tiny")

    @patch.dict("sys.modules", {"pywhispercpp": None, "pywhispercpp.model": None})
    def test_import_error_when_not_installed(self):
        """pywhispercpp 未安装时应抛出 ImportError。"""
        recognizer = SpeechRecognizer()
        with pytest.raises(ImportError, match="pywhispercpp 未安装"):
            recognizer._ensure_model()

    def test_model_loaded_only_once(self):
        """模型只应加载一次。"""
        recognizer = SpeechRecognizer()
        mock_model = MagicMock()
        recognizer._model = mock_model

        # 再次调用不应重新加载
        recognizer._ensure_model()
        assert recognizer._model is mock_model


class TestRecognize:
    """recognize 方法测试。"""

    def _make_recognizer(self):
        """创建一个已注入 mock 模型的 recognizer。"""
        recognizer = SpeechRecognizer()
        recognizer._model = MagicMock()
        return recognizer

    def test_successful_recognition(self, tmp_path):
        """成功识别音频应返回文字。"""
        recognizer = self._make_recognizer()
        recognizer._model.transcribe.return_value = [
            FakeSegment(text="你好"),
            FakeSegment(text="世界"),
        ]

        result = recognizer.recognize(b"fake wav data")

        assert result == "你好世界"
        recognizer._model.transcribe.assert_called_once()
        # 验证临时文件已被清理
        call_args = recognizer._model.transcribe.call_args
        tmp_file = call_args[0][0]
        assert not os.path.exists(tmp_file)

    def test_empty_result_raises_value_error(self):
        """识别结果为空时应抛出 ValueError。"""
        recognizer = self._make_recognizer()
        recognizer._model.transcribe.return_value = []

        with pytest.raises(ValueError, match="语音识别结果为空"):
            recognizer.recognize(b"fake wav data")

    def test_whitespace_only_result_raises_value_error(self):
        """识别结果仅含空白时应抛出 ValueError。"""
        recognizer = self._make_recognizer()
        recognizer._model.transcribe.return_value = [FakeSegment(text="   ")]

        with pytest.raises(ValueError, match="语音识别结果为空"):
            recognizer.recognize(b"fake wav data")

    def test_transcribe_error_raises_runtime_error(self):
        """转录过程出错应抛出 RuntimeError。"""
        recognizer = self._make_recognizer()
        recognizer._model.transcribe.side_effect = Exception("模型崩溃")

        with pytest.raises(RuntimeError, match="语音识别处理错误"):
            recognizer.recognize(b"fake wav data")

    def test_temp_file_cleaned_on_success(self):
        """成功时临时文件应被清理。"""
        recognizer = self._make_recognizer()
        created_paths = []

        original_transcribe = recognizer._model.transcribe

        def capture_path(path, **kwargs):
            created_paths.append(path)
            return [FakeSegment(text="测试")]

        recognizer._model.transcribe.side_effect = capture_path

        recognizer.recognize(b"fake wav data")

        assert len(created_paths) == 1
        assert not os.path.exists(created_paths[0])

    def test_temp_file_cleaned_on_error(self):
        """出错时临时文件也应被清理。"""
        recognizer = self._make_recognizer()
        created_paths = []

        def capture_and_fail(path, **kwargs):
            created_paths.append(path)
            raise Exception("boom")

        recognizer._model.transcribe.side_effect = capture_and_fail

        with pytest.raises(RuntimeError):
            recognizer.recognize(b"fake wav data")

        assert len(created_paths) == 1
        assert not os.path.exists(created_paths[0])

    def test_language_passed_to_transcribe(self):
        """应将配置的语言传递给 transcribe。"""
        recognizer = SpeechRecognizer(language="en")
        recognizer._model = MagicMock()
        recognizer._model.transcribe.return_value = [FakeSegment(text="hello")]

        recognizer.recognize(b"fake wav data")

        call_kwargs = recognizer._model.transcribe.call_args[1]
        assert call_kwargs["language"] == "en"

    def test_chinese_language_default(self):
        """默认语言应为中文。"""
        recognizer = self._make_recognizer()
        recognizer._model.transcribe.return_value = [FakeSegment(text="你好")]

        recognizer.recognize(b"fake wav data")

        call_kwargs = recognizer._model.transcribe.call_args[1]
        assert call_kwargs["language"] == "zh"
