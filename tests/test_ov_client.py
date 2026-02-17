"""Tests for src.infra.ov_client module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest


class TestEnsureOvConf:
    @patch("src.infra.ov_client._OV_CONF_PATH")
    @patch("src.infra.ov_client._OV_CONF_DIR")
    def test_skips_if_exists(self, mock_dir, mock_path):
        mock_path.exists.return_value = True

        from src.infra.ov_client import _ensure_ov_conf
        _ensure_ov_conf()

        # Should not try to write
        mock_path.write_text.assert_not_called()

    @patch("src.infra.ov_client.cfg")
    @patch("src.infra.ov_client._OV_CONF_PATH")
    @patch("src.infra.ov_client._OV_CONF_DIR")
    def test_skips_if_no_api_key(self, mock_dir, mock_path, mock_cfg):
        mock_path.exists.return_value = False
        mock_cfg.embedding_api_key = ""

        from src.infra.ov_client import _ensure_ov_conf
        _ensure_ov_conf()

        mock_path.write_text.assert_not_called()

    def test_generates_conf_file(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / ".openviking"
        conf_path = conf_dir / "ov.conf"

        monkeypatch.setattr("src.infra.ov_client._OV_CONF_DIR", conf_dir)
        monkeypatch.setattr("src.infra.ov_client._OV_CONF_PATH", conf_path)

        mock_cfg = MagicMock()
        mock_cfg.embedding_api_key = "test-key"
        mock_cfg.embedding_api_base = "http://api.test"
        mock_cfg.embedding_model = "embed-model"
        mock_cfg.embedding_dim = 1024
        mock_cfg.vlm_model = ""
        monkeypatch.setattr("src.infra.ov_client.cfg", mock_cfg)

        from src.infra.ov_client import _ensure_ov_conf
        _ensure_ov_conf()

        assert conf_path.exists()
        data = json.loads(conf_path.read_text())
        assert data["embedding"]["dense"]["api_key"] == "test-key"
        assert data["embedding"]["dense"]["dimension"] == 1024
        assert "vlm" not in data

    def test_generates_conf_with_vlm(self, tmp_path, monkeypatch):
        conf_dir = tmp_path / ".openviking"
        conf_path = conf_dir / "ov.conf"

        monkeypatch.setattr("src.infra.ov_client._OV_CONF_DIR", conf_dir)
        monkeypatch.setattr("src.infra.ov_client._OV_CONF_PATH", conf_path)

        mock_cfg = MagicMock()
        mock_cfg.embedding_api_key = "key"
        mock_cfg.embedding_api_base = "http://api"
        mock_cfg.embedding_model = "em"
        mock_cfg.embedding_dim = 2048
        mock_cfg.vlm_model = "vlm-model"
        monkeypatch.setattr("src.infra.ov_client.cfg", mock_cfg)

        from src.infra.ov_client import _ensure_ov_conf
        _ensure_ov_conf()

        data = json.loads(conf_path.read_text())
        assert "vlm" in data
        assert data["vlm"]["model"] == "vlm-model"


class TestOVClient:
    @patch("src.infra.ov_client._ensure_ov_conf")
    @patch("src.infra.ov_client.ov.SyncOpenViking")
    def test_init_creates_client(self, mock_ov_cls, mock_conf):
        from src.infra.ov_client import OVClient

        client = OVClient("/tmp/data")
        mock_ov_cls.assert_called_once_with(path="/tmp/data")

    @patch("src.infra.ov_client._ensure_ov_conf")
    @patch("src.infra.ov_client.ov.SyncOpenViking")
    def test_add_writes_temp_file_and_calls_add_resource(self, mock_ov_cls, mock_conf):
        mock_instance = MagicMock()
        mock_ov_cls.return_value = mock_instance

        from src.infra.ov_client import OVClient

        client = OVClient("/data")
        client.add("print('hello')", "viking://code/test")

        mock_instance.add_resource.assert_called_once()
        call_kwargs = mock_instance.add_resource.call_args
        assert call_kwargs[1]["target"] == "viking://code/test"
        mock_instance.wait_processed.assert_called_once_with(timeout=60)

    @patch("src.infra.ov_client._ensure_ov_conf")
    @patch("src.infra.ov_client.ov.SyncOpenViking")
    def test_retrieve_returns_overview(self, mock_ov_cls, mock_conf):
        mock_instance = MagicMock()
        mock_ov_cls.return_value = mock_instance

        # Set up find result
        mock_resource = MagicMock()
        mock_resource.uri = "viking://code/test"
        mock_results = MagicMock()
        mock_results.resources = [mock_resource]
        mock_instance.find.return_value = mock_results
        mock_instance.overview.return_value = "This code does X"

        from src.infra.ov_client import OVClient

        client = OVClient("/data")
        result = client.retrieve("test query")

        assert result == "This code does X"
        mock_instance.find.assert_called_once_with("test query", limit=3)
        mock_instance.overview.assert_called_once_with("viking://code/test")

    @patch("src.infra.ov_client._ensure_ov_conf")
    @patch("src.infra.ov_client.ov.SyncOpenViking")
    def test_retrieve_returns_empty_on_no_results(self, mock_ov_cls, mock_conf):
        mock_instance = MagicMock()
        mock_ov_cls.return_value = mock_instance

        mock_results = MagicMock()
        mock_results.resources = []
        mock_instance.find.return_value = mock_results

        from src.infra.ov_client import OVClient

        client = OVClient("/data")
        result = client.retrieve("nonexistent")

        assert result == ""

    @patch("src.infra.ov_client._ensure_ov_conf")
    @patch("src.infra.ov_client.ov.SyncOpenViking")
    def test_retrieve_returns_empty_when_overview_is_none(self, mock_ov_cls, mock_conf):
        mock_instance = MagicMock()
        mock_ov_cls.return_value = mock_instance

        mock_resource = MagicMock()
        mock_resource.uri = "test"
        mock_results = MagicMock()
        mock_results.resources = [mock_resource]
        mock_instance.find.return_value = mock_results
        mock_instance.overview.return_value = None

        from src.infra.ov_client import OVClient

        client = OVClient("/data")
        assert client.retrieve("q") == ""

    @patch("src.infra.ov_client._ensure_ov_conf")
    @patch("src.infra.ov_client.ov.SyncOpenViking")
    def test_close_calls_client_close(self, mock_ov_cls, mock_conf):
        mock_instance = MagicMock()
        mock_ov_cls.return_value = mock_instance

        from src.infra.ov_client import OVClient

        client = OVClient("/data")
        client.close()
        mock_instance.close.assert_called_once()
