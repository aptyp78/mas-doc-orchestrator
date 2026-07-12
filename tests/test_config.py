"""Тест конфигурации: проверяет доступность ключей и моделей."""

import pytest
from src.utils.config import DASHSCOPE_KEY, OLLAMA_CLOUD_KEY


def test_dashscope_key_available():
    assert DASHSCOPE_KEY, "DashScope API key not found (set DASHSCOPE_API_KEY or keychain 'dashscope-modelstudio')"
    assert DASHSCOPE_KEY.startswith("sk-"), "DashScope key should start with sk-"


def test_ollama_cloud_key_available():
    assert OLLAMA_CLOUD_KEY, "Ollama Cloud API key not found (set OLLAMA_CLOUD_API_KEY or keychain 'ollama-cloud')