"""API-ключи и endpoint'ы из macOS keychain или переменных окружения."""

import os
import subprocess
import json


def _keychain_get(account: str) -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-w"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _env_or_keychain(env_var: str, keychain_account: str) -> str:
    value = os.environ.get(env_var)
    if value:
        return value
    value = _keychain_get(keychain_account)
    if value:
        return value
    raise RuntimeError(
        f"Не найден ключ: переменная {env_var} или keychain-запись '{keychain_account}'.\n"
        f"Сохраните ключ: security add-generic-password -a '{keychain_account}' -w '<API_KEY>' -T ''"
    )


DASHSCOPE_KEY = _env_or_keychain("DASHSCOPE_API_KEY", "dashscope-modelstudio")
DASHSCOPE_BASE = os.environ.get(
    "DASHSCOPE_BASE_URL",
    "https://ws-yrwako2ivay84n1p.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
)

OLLAMA_CLOUD_KEY = _env_or_keychain("OLLAMA_CLOUD_API_KEY", "ollama-cloud")
OLLAMA_CLOUD_BASE = "https://api.ollama.com"
OLLAMA_LOCAL_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Модели по умолчанию (переопределяются через env)
AGENT_VISION_MODEL = os.environ.get("MAS_AGENT_VISION", "qwen3-vl-plus")
REFLECTOR_MODEL = os.environ.get("MAS_REFLECTOR", "qwen3.6-35b-a3b")
EMBEDDING_MODEL = os.environ.get("MAS_EMBEDDING", "qwen3-embedding:8b")

CONFIDENCE_THRESHOLD = float(os.environ.get("MAS_CONFIDENCE_THRESHOLD", "0.85"))
MAX_REFLECTION_ITERATIONS = int(os.environ.get("MAS_MAX_ITERATIONS", "3"))