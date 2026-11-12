"""Слой 4 (API Client): взаимодействие с эндпоинтами /embeddings, /rerank и /chat/completions."""

from __future__ import annotations

import math
import sys
import time
import httpx
import numpy as np

import config
import prompts

_RERANKER_AVAILABLE = not config.IS_GOOGLE_API


def api_post(client: httpx.Client, path: str, key: str, payload: dict, retries: int = 3) -> dict:
    if not key:
        raise ValueError("Отсутствует API-ключ")
    url = config.API_BASE + path
    headers = {"Authorization": f"Bearer {key}"}

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.post(url, headers=headers, json=payload)
            if response.status_code == 404:
                response.raise_for_status()
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                wait_s = 4.0 * (attempt + 1) if response.status_code == 429 else 1.5 * (2 ** attempt)
                time.sleep(wait_s)
                continue
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_exc = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                break
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))

    status_info = (
        f"HTTP {last_exc.response.status_code}"
        if isinstance(last_exc, httpx.HTTPStatusError)
        else type(last_exc).__name__
    )
    raise RuntimeError(f"Ошибка API {path} ({status_info})") from last_exc


def fetch_embeddings_batched(client: httpx.Client, texts: list[str], batch_size: int = 32) -> np.ndarray | None:
    if not texts:
        return None

    active_emb_model = config.EMB_MODEL
    if config.IS_GOOGLE_API and active_emb_model in {"baai/bge-m3", "text-embedding-004"}:
        active_emb_model = "gemini-embedding-001"
        batch_size = 64

    all_vecs: list[list[float]] = []
    try:
        for start in range(0, len(texts), batch_size):
            batch = [t[:3500] for t in texts[start : start + batch_size]]
            payload: dict = {"model": active_emb_model, "input": batch}
            if not config.IS_GOOGLE_API:
                payload["encoding_format"] = "float"

            result = api_post(client, "/embeddings", config.EMBED_KEY, payload, retries=3)
            batch_vecs: list[list[float] | None] = [None] * len(batch)
            for pos, item in enumerate(result.get("data", [])):
                idx = int(item.get("index", pos))
                if 0 <= idx < len(batch):
                    vec = item["embedding"]
                    norm = math.sqrt(sum(float(x) ** 2 for x in vec)) or 1.0
                    batch_vecs[idx] = [float(x) / norm for x in vec]
            if any(v is None for v in batch_vecs):
                return None
            all_vecs.extend(batch_vecs)  # type: ignore[arg-type]
            if config.IS_GOOGLE_API and start + batch_size < len(texts):
                time.sleep(0.4)
        return np.asarray(all_vecs, dtype=np.float32)
    except Exception as exc:
        print(f"[WARN] Embeddings API недоступен ({exc}), используем BM25 + TF-IDF", file=sys.stderr)
        return None


def call_reranker(client: httpx.Client, query: str, candidate_texts: list[str], top_n: int) -> list[int] | None:
    global _RERANKER_AVAILABLE
    if not candidate_texts or not _RERANKER_AVAILABLE:
        return None
    try:
        result = api_post(
            client,
            "/rerank",
            config.RERANK_KEY,
            {
                "model": config.RERANKER_MODEL,
                "query": query[:2000],
                "documents": [t[:3200] for t in candidate_texts],
                "top_n": min(top_n, len(candidate_texts)),
            },
            retries=2,
        )
        items = result.get("results", result.get("data", []))
        indices = [int(item["index"]) for item in items if "index" in item]
        valid = [i for i in indices if 0 <= i < len(candidate_texts)]
        return valid if valid else None
    except Exception as exc:
        _RERANKER_AVAILABLE = False
        print(f"[WARN] Reranker API отключён ({exc}), используем гибридный RRF-ранг", file=sys.stderr)
        return None


def generate_answer(
    client: httpx.Client,
    raw_question: str,
    context_str: str,
    has_injection_warning: bool,
) -> str:
    user_prompt = prompts.build_user_prompt(raw_question, context_str, has_injection_warning)

    for attempt in range(3):
        current_max_tokens = config.MAX_TOKENS if attempt == 0 else min(8192, config.MAX_TOKENS * (attempt + 1))
        payload: dict = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": prompts.SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.TEMPERATURE,
            "max_tokens": current_max_tokens,
        }
        try:
            result = api_post(client, "/chat/completions", config.LLM_KEY, payload, retries=2)
            choice = result["choices"][0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"Пустой ответ (finish_reason={choice.get('finish_reason')})")

            cleaned = prompts.clean_model_output(content)
            if cleaned:
                return cleaned
        except Exception as exc:
            print(f"[WARN] Попытка генерации {attempt + 1}/3 ({type(exc).__name__}: {exc})", file=sys.stderr)
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))

    return config.FALLBACK_ANSWER