"""Tests for src.infra.llm module."""

from unittest.mock import MagicMock, patch

import pytest


class TestLLMClient:
    def _make_client(self, mock_anthropic_cls):
        """Create an LLMClient with a mocked Anthropic SDK."""
        from src.infra.llm import LLMClient

        client = LLMClient(
            base_url="http://test.llm",
            api_key="test-key",
            model="test-model",
        )
        return client

    @patch("src.infra.llm.Anthropic")
    def test_init_passes_params(self, mock_cls):
        from src.infra.llm import LLMClient

        LLMClient(base_url="http://x", api_key="key", model="m")
        mock_cls.assert_called_once_with(base_url="http://x", api_key="key")

    @patch("src.infra.llm.Anthropic")
    def test_chat_calls_messages_create(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        # Set up the response mock
        mock_content = MagicMock()
        mock_content.text = "generated code"
        mock_instance.messages.create.return_value = MagicMock(content=[mock_content])

        client = self._make_client(mock_cls)
        result = client.chat("system prompt", "user prompt")

        mock_instance.messages.create.assert_called_once_with(
            model="test-model",
            max_tokens=4096,
            system="system prompt",
            messages=[{"role": "user", "content": "user prompt"}],
        )
        assert result == "generated code"

    @patch("src.infra.llm.Anthropic")
    def test_chat_extracts_response_text(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance

        mock_content = MagicMock()
        mock_content.text = "Hello, World!"
        mock_instance.messages.create.return_value = MagicMock(content=[mock_content])

        client = self._make_client(mock_cls)
        assert client.chat("sys", "usr") == "Hello, World!"

    @patch("src.infra.llm.Anthropic")
    def test_chat_propagates_api_error(self, mock_cls):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.messages.create.side_effect = RuntimeError("API down")

        client = self._make_client(mock_cls)
        with pytest.raises(RuntimeError, match="API down"):
            client.chat("sys", "usr")

    @patch("src.infra.llm.Anthropic")
    def test_chat_model_stored(self, mock_cls):
        from src.infra.llm import LLMClient

        client = LLMClient(base_url="http://x", api_key="k", model="my-model")
        assert client._model == "my-model"
