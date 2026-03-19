"""Configuration management for GitHub Review."""

from __future__ import annotations

import json
import os
import sys

# In frozen (PyInstaller) mode, store config next to the executable
if getattr(sys, "frozen", False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(_base, "runtime", "config", "config.json")
LEGACY_CONFIG_PATH = os.path.join(_base, "config.json")

DEFAULTS = {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "api_key": "",
    "ollama_url": "http://localhost:11434",
    "top_repos": 15,
    "batch_size": 5,
    "extended_thinking": False,
}


def load_config():
    """Load config from config.json, merged with defaults."""
    _ensure_config_location()
    config = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                stored = json.load(f)
            config.update(stored)
        except (json.JSONDecodeError, IOError):
            pass
    return config


def save_config(data):
    """Save config to config.json."""
    _ensure_config_location()
    config = load_config()
    config.update(data)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    return config


def get_redacted_config():
    """Return config with API key partially redacted for display."""
    config = load_config()
    key = config.get("api_key", "")
    if key and len(key) > 8:
        config["api_key_display"] = key[:4] + "..." + key[-4:]
    elif key:
        config["api_key_display"] = "****"
    else:
        config["api_key_display"] = ""
    return config


def _ensure_config_location():
    """Create runtime config directory and migrate legacy config if present."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH) and os.path.exists(LEGACY_CONFIG_PATH):
        try:
            os.replace(LEGACY_CONFIG_PATH, CONFIG_PATH)
        except OSError:
            # Non-fatal; loading will continue from whichever path is available.
            pass
