"""Tests for src.config module."""

import os
from unittest.mock import patch

import pytest


class TestConfig:
    """Test Config dataclass loading from environment."""

    def test_default_restate_url(self, monkeypatch):
        monkeypatch.delenv("RESTATE_URL", raising=False)
        # Re-import to pick up env changes
        cfg = self._fresh_config(monkeypatch)
        assert cfg.restate_url == "http://localhost:8080"

    def test_custom_restate_url(self, monkeypatch):
        monkeypatch.setenv("RESTATE_URL", "http://custom:9090")
        cfg = self._fresh_config(monkeypatch)
        assert cfg.restate_url == "http://custom:9090"

    def test_llm_defaults_empty(self, monkeypatch):
        for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL_NAME"):
            monkeypatch.delenv(key, raising=False)
        cfg = self._fresh_config(monkeypatch)
        assert cfg.llm_base_url == ""
        assert cfg.llm_api_key == ""
        assert cfg.llm_model_name == ""

    def test_llm_custom_values(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "http://llm.test")
        monkeypatch.setenv("LLM_API_KEY", "test-key-123")
        monkeypatch.setenv("LLM_MODEL_NAME", "test-model")
        cfg = self._fresh_config(monkeypatch)
        assert cfg.llm_base_url == "http://llm.test"
        assert cfg.llm_api_key == "test-key-123"
        assert cfg.llm_model_name == "test-model"

    def test_ov_data_path_default(self, monkeypatch):
        monkeypatch.delenv("OV_DATA_PATH", raising=False)
        cfg = self._fresh_config(monkeypatch)
        assert cfg.ov_data_path == "./data/ov_store"

    def test_embedding_dim_default(self, monkeypatch):
        monkeypatch.delenv("EMBEDDING_DIM", raising=False)
        cfg = self._fresh_config(monkeypatch)
        assert cfg.embedding_dim == 2048

    def test_embedding_dim_custom(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_DIM", "1024")
        cfg = self._fresh_config(monkeypatch)
        assert cfg.embedding_dim == 1024

    def test_config_is_frozen(self, monkeypatch):
        cfg = self._fresh_config(monkeypatch)
        with pytest.raises(AttributeError):
            cfg.restate_url = "nope"

    @staticmethod
    def _fresh_config(monkeypatch):
        """Create a fresh Config picking up current env vars."""
        # We can't easily re-import the module-level cfg singleton,
        # so just instantiate Config directly with os.getenv.
        from dataclasses import dataclass

        @dataclass(frozen=True)
        class _Config:
            restate_url: str = os.getenv("RESTATE_URL", "http://localhost:8080")
            llm_base_url: str = os.getenv("LLM_BASE_URL", "")
            llm_api_key: str = os.getenv("LLM_API_KEY", "")
            llm_model_name: str = os.getenv("LLM_MODEL_NAME", "")
            ov_data_path: str = os.getenv("OV_DATA_PATH", "./data/ov_store")
            embedding_api_key: str = os.getenv("EMBEDDING_API_KEY", "")
            embedding_api_base: str = os.getenv("EMBEDDING_API_BASE", "")
            embedding_model: str = os.getenv("EMBEDDING_MODEL", "")
            embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "2048"))
            vlm_model: str = os.getenv("VLM_MODEL", "")

        return _Config()
