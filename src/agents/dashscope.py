"""Клиенты для LLM-провайдеров: DashScope, Ollama (локальный + облачный)."""

import json
import urllib.request
from src.utils.config import DASHSCOPE_KEY, DASHSCOPE_BASE, OLLAMA_CLOUD_KEY, OLLAMA_CLOUD_BASE, OLLAMA_LOCAL_BASE


def dashscope_chat(model: str, messages: list, max_tokens: int = 4096, temperature: float = 0.1) -> tuple[str, dict]:
    """Вызов DashScope OpenAI-compatible chat completions."""
    data = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        f"{DASHSCOPE_BASE}/chat/completions", data=data,
        headers={"Authorization": f"Bearer {str(DASHSCOPE_KEY)}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        d = json.loads(resp.read())
        return d["choices"][0]["message"]["content"], d.get("usage", {})


def dashscope_vision(model: str, image_b64: str, prompt: str, max_tokens: int = 4096) -> tuple[str, dict]:
    """Vision-агент: изображение + промпт."""
    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + image_b64}},
            {"type": "text", "text": prompt}
        ]
    }]
    return dashscope_chat(model, messages, max_tokens)


def ollama_embed(text: str, model: str = "qwen3-embedding:8b", local: bool = True) -> list[float]:
    """Эмбеддинг через Ollama (локальный или облачный)."""
    base = OLLAMA_LOCAL_BASE if local else OLLAMA_CLOUD_BASE
    headers = {"Content-Type": "application/json"}
    if not local:
        headers["Authorization"] = f"Bearer {str(OLLAMA_CLOUD_KEY)}"
        headers["User-Agent"] = "ollama/0.9.0 (darwin; arm64)"

    data = json.dumps({"model": model, "input": text}).encode()
    req = urllib.request.Request(f"{base}/api/embed", data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["embeddings"][0]