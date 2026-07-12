"""Тест конфигурации: проверяет доступность ключей."""

import os
import pytest
from src.utils.config import DASHSCOPE_KEY, OLLAMA_CLOUD_KEY


def test_dashscope_key_available():
    key = str(DASHSCOPE_KEY)
    assert key, "DashScope API key not found"
    assert key.startswith("sk-"), "DashScope key should start with sk-"


@pytest.mark.skipif(
    not os.environ.get("OLLAMA_CLOUD_API_KEY"),
    reason="OLLAMA_CLOUD_API_KEY not set in env; keychain test skipped"
)
def test_ollama_cloud_key_available():
    key = str(OLLAMA_CLOUD_KEY)
    assert key, "Ollama Cloud API key not found"