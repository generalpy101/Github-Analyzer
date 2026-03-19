"""Tests for server/config.py."""

import json
from unittest.mock import patch

import server.config as config_module
from server.config import load_config, save_config, get_redacted_config, DEFAULTS


def test_defaults():
    assert "provider" in DEFAULTS
    assert "model" in DEFAULTS
    assert "extended_thinking" in DEFAULTS
    assert "batch_size" in DEFAULTS


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_path):
        fake_path = str(tmp_path / "nonexistent" / "config.json")
        with patch.object(config_module, "CONFIG_PATH", fake_path):
            with patch.object(config_module, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json")):
                config = load_config()
                assert config["provider"] == DEFAULTS["provider"]
                assert config["extended_thinking"] == DEFAULTS["extended_thinking"]

    def test_merges_with_stored(self, tmp_path):
        cfg_path = str(tmp_path / "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"provider": "openai", "model": "gpt-4o"}, f)
        with patch.object(config_module, "CONFIG_PATH", cfg_path):
            with patch.object(config_module, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json")):
                config = load_config()
                assert config["provider"] == "openai"
                assert config["model"] == "gpt-4o"
                assert config["top_repos"] == DEFAULTS["top_repos"]


class TestSaveConfig:
    def test_save_and_reload(self, tmp_path):
        cfg_path = str(tmp_path / "config.json")
        with patch.object(config_module, "CONFIG_PATH", cfg_path):
            with patch.object(config_module, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json")):
                save_config({"provider": "ollama", "model": "llama3.1"})
                config = load_config()
                assert config["provider"] == "ollama"
                assert config["model"] == "llama3.1"


class TestRedactedConfig:
    def test_long_key_redacted(self, tmp_path):
        cfg_path = str(tmp_path / "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"api_key": "sk-1234567890abcdef"}, f)
        with patch.object(config_module, "CONFIG_PATH", cfg_path):
            with patch.object(config_module, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json")):
                config = get_redacted_config()
                assert config["api_key_display"] == "sk-1...cdef"
                assert "1234567890" not in config["api_key_display"]

    def test_empty_key(self, tmp_path):
        cfg_path = str(tmp_path / "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"api_key": ""}, f)
        with patch.object(config_module, "CONFIG_PATH", cfg_path):
            with patch.object(config_module, "LEGACY_CONFIG_PATH", str(tmp_path / "legacy.json")):
                config = get_redacted_config()
                assert config["api_key_display"] == ""
