"""Локальный Ollama клиент: qwen3-vl:30b (vision), qwen3.6:35b (reasoning)."""

import json
import urllib.request

from src.utils.config import OLLAMA_LOCAL_BASE


def ollama_chat(model: str, messages: list, max_tokens: int = 4096, temperature: float = 0.1) -> tuple[str, dict]:
    """Вызов локального Ollama chat completions."""
    data = json.dumps(
        {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(
        f"{OLLAMA_LOCAL_BASE}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8")
        # Ollama may return multiple JSON objects (stream-like format)
        if "}\n{" in raw:
            # Take first JSON object
            parts = raw.split("\n")
            for part in parts:
                if part.strip() and part.startswith("{"):
                    try:
                        d = json.loads(part)
                        usage = {"eval_count": d.get("eval_count", 0), "total_duration": d.get("total_duration", 0)}
                        return d["message"]["content"], usage
                    except (KeyError, json.JSONDecodeError):
                        continue
        else:
            d = json.loads(raw)
            usage = {"eval_count": d.get("eval_count", 0), "total_duration": d.get("total_duration", 0)}
            return d["message"]["content"], usage
    raise RuntimeError("No valid response from Ollama")


def ollama_vision(model: str, image_b64: str, prompt: str, max_tokens: int = 4096) -> tuple[str, dict]:
    """Vision-агент через локальный Ollama (qwen3-vl:30b)."""
    messages = [
        {"role": "user", "content": prompt},
        {"role": "user", "content": "", "images": [image_b64]},
    ]
    result, usage = ollama_chat(model, messages, max_tokens)
    return result, usage
