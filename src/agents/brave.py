"""Клиент для Brave Search API."""

import json
import urllib.request

from src.utils.config import BRAVE_SEARCH_BASE, BRAVE_SEARCH_KEY


def brave_search(query: str, count: int = 5) -> dict:
    """Поиск через Brave Search API."""
    params = {
        "q": query,
        "count": count,
        "text_decorations": True,
        "search_lang": "ru",
    }

    url = f"{BRAVE_SEARCH_BASE}/web?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {str(BRAVE_SEARCH_KEY)}",
            "User-Agent": "mas-doc-orchestrator/0.1.0",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def brave_knowledge(query: str) -> dict:
    """Получение знаний из Knowledge Graph через Brave Search API."""
    params = {
        "q": query,
        "result_filter": "kb",
    }

    url = f"{BRAVE_SEARCH_BASE}/search?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {str(BRAVE_SEARCH_KEY)}",
            "User-Agent": "mas-doc-orchestrator/0.1.0",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())
