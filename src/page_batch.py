"""Page Batch Pipeline: постраничная параллельная обработка.

Ключевой принцип: документ = набор страниц. Каждая страница — независимая задача.
24-страничный документ = 24 задачи в batch, а не 1 задача на 24 страницы.
"""

from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.compute_resource import ComputeBudget, ComputeResourceManager
from src.normalizer.pdf_normalizer import normalize


def _jitter_sleep(budget: ComputeBudget) -> None:
    """Jitter для rate-limiting между API-вызовами."""
    delay = random.uniform(*budget.jitter_ms) / 1000.0
    time.sleep(delay)


def _retry_with_backoff(
    fn, budget: ComputeBudget, resource_mgr: ComputeResourceManager, resource_kind: str
):
    """Выполняет функцию с retry и экспоненциальным backoff."""
    last_error = None
    for attempt in range(budget.retry_max):
        try:
            if not resource_mgr.acquire(resource_kind):
                _jitter_sleep(budget)
                continue

            t0 = time.time()
            result = fn()
            elapsed_ms = (time.time() - t0) * 1000
            resource_mgr.release(resource_kind, latency_ms=elapsed_ms)
            return result
        except Exception as e:
            last_error = e
            resource_mgr.release(resource_kind, error=True)
            backoff = budget.backoff_base_s * (2 ** attempt)
            time.sleep(backoff)

    raise last_error or RuntimeError("max retries exceeded")


def process_pages_batch(
    pdf_paths: list[str],
    max_workers: int | None = None,
    resource_mgr: ComputeResourceManager | None = None,
) -> list[dict]:
    """Пакетная обработка: каждая страница каждого документа — отдельная задача.

    Args:
        pdf_paths: список путей к PDF-файлам
        max_workers: максимальное число параллельных workers (None = авто)
        resource_mgr: менеджер ресурсов (None = создать новый)

    Returns:
        список результатов по страницам: [{pdf, page_id, page_type, elements, ...}]
    """
    if resource_mgr is None:
        resource_mgr = ComputeResourceManager()

    budget = resource_mgr.budget_for_stage("normalization")
    if max_workers is None:
        max_workers = budget.local_workers

    # 1. Собираем все страницы из всех документов
    all_pages: list[dict] = []  # [{pdf_path, page_num, page}]
    for pdf_path in pdf_paths:
        universal = normalize(pdf_path)
        for page in universal["pages"]:
            all_pages.append({
                "pdf_path": pdf_path,
                "page_id": page["page_id"],
                "page_type": page["page_type"],
                "elements": page["elements"],
                "width": page["width"],
                "height": page["height"],
                "image_content": page.get("image_content"),
            })

    # 2. Параллельная обработка страниц
    results: list[dict] = []

    def process_page(page_info: dict) -> dict:
        """Обрабатывает одну страницу."""
        _jitter_sleep(budget)
        return {
            **page_info,
            "processed_at": time.time(),
            "element_count": len(page_info["elements"]),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_page, p): p for p in all_pages}

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                # Retry
                page = futures[future]
                _jitter_sleep(budget)
                try:
                    result = process_page(page)
                    if result:
                        results.append(result)
                except Exception:
                    results.append({**page, "error": str(e)})

    return results


def aggregate_pages_to_documents(page_results: list[dict]) -> dict[str, dict]:
    """Агрегирует постраничные результаты в документы.

    Returns:
        {pdf_path: {total_pages, page_types, elements_total, errors}}
    """
    docs: dict[str, dict] = {}
    for pr in page_results:
        pdf = pr["pdf_path"]
        if pdf not in docs:
            docs[pdf] = {
                "pdf_path": pdf,
                "pages": [],
                "total_pages": 0,
                "page_types": {},
                "elements_total": 0,
                "errors": 0,
            }
        doc = docs[pdf]
        doc["pages"].append(pr)
        doc["total_pages"] += 1
        pt = pr.get("page_type", "unknown")
        doc["page_types"][pt] = doc["page_types"].get(pt, 0) + 1
        doc["elements_total"] += pr.get("element_count", 0)
        if "error" in pr:
            doc["errors"] += 1

    return docs