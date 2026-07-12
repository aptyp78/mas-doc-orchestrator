"""API-ключи и endpoint'ы — ленивая загрузка из macOS keychain или переменных окружения."""

import os
import subprocess
import json


def _keychain_get(account: str) -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", f"{account}-api", "-w"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


class _LazyKey:
    """Ленивый ключ: загружается при первом обращении, не падает при импорте."""

    def __init__(self, env_var: str, keychain_account: str):
        self._env_var = env_var
        self._keychain_account = keychain_account
        self._value: str | None = None
        self._loaded = False

    def _load(self) -> str:
        if self._loaded:
            return self._value  # type: ignore[return-value]
        self._loaded = True
        value = os.environ.get(self._env_var)
        if value:
            self._value = value
            return value
        value = _keychain_get(self._keychain_account)
        if value:
            self._value = value
            return value
        raise RuntimeError(
            f"Не найден ключ: переменная {self._env_var} или keychain-запись '{self._keychain_account}'.\n"
            f"Сохраните ключ: security add-generic-password -a '{self._keychain_account}' "
            f"-s '{self._keychain_account}-api' -w '<API_KEY>' -T ''"
        )

    def __str__(self) -> str:
        return self._load()

    def __repr__(self) -> str:
        try:
            return f"Key(***{self._load()[-4:]})"
        except RuntimeError:
            return "Key(<missing>)"


DASHSCOPE_KEY = _LazyKey("DASHSCOPE_API_KEY", "dashscope-modelstudio")
DASHSCOPE_BASE = os.environ.get(
    "DASHSCOPE_BASE_URL",
    "https://ws-yrwako2ivay84n1p.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
)

OLLAMA_CLOUD_KEY = _LazyKey("OLLAMA_CLOUD_API_KEY", "ollama-cloud")
OLLAMA_CLOUD_BASE = "https://api.ollama.com"
OLLAMA_LOCAL_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

AGENT_VISION_MODEL = os.environ.get("MAS_AGENT_VISION", "qwen3-vl-plus")
REFLECTOR_MODEL = os.environ.get("MAS_REFLECTOR", "qwen3.6-35b-a3b")
EMBEDDING_MODEL = os.environ.get("MAS_EMBEDDING", "qwen3-embedding:8b")

CONFIDENCE_THRESHOLD = float(os.environ.get("MAS_CONFIDENCE_THRESHOLD", "0.85"))
MAX_REFLECTION_ITERATIONS = int(os.environ.get("MAS_MAX_ITERATIONS", "3"))