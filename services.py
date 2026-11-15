from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from sqlalchemy.orm import Session

import config
import history
import llm_client
import prompts
import repository
from retriever import HybridLegalRetriever

logger = logging.getLogger(__name__)

FALLBACK_ANSWER = (
    "В предоставленной базе знаний нет документов, достаточных для достоверного ответа "
    "по поставленному вопросу. По памяти отвечать не буду, так как нормы могли измениться. "
    "Уточните вопрос или обратитесь к юристу."
)


class LLMClient:
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        client: httpx.Client | None = None,
    ) -> str:
        if client is None:
            with httpx.Client(timeout=90.0) as default_client:
                return self._call(default_client, system_prompt, user_prompt)
        return self._call(client, system_prompt, user_prompt)

    def _call(
        self,
        client: httpx.Client,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        payload = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.TEMPERATURE,
            "max_tokens": config.MAX_TOKENS,
        }
        res = llm_client.api_post(
            client, "/chat/completions", config.LLM_KEY, payload, retries=2
        )
        choice = res.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        if not content:
            return ""
        return prompts.clean_model_output(content)


def ask(
    db: Session,
    chat_id: str | uuid.UUID,
    question: str,
    client: httpx.Client,
    llm: LLMClient | Any,
    index: HybridLegalRetriever | Any,
) -> dict:
    chat_data = repository.get_chat(db, chat_id)
    if chat_data is None:
        raise ValueError(f"Чат {chat_id} не найден")

    dialog_lines: list[str] = []
    for m in chat_data.get("messages", []):
        prefix = "Пользователь" if m["role"] == "user" else "Ассистент"
        dialog_lines.append(f"{prefix}: {m['content'].strip()}")
    dialog_lines.append(f"Пользователь: {question.strip()}")
    dialog = "\n".join(dialog_lines)

    hist, last_user = history.parse_dialog(dialog)
    search_query = history.build_search_query(hist, last_user)

    context, retrieved_sources = index.retrieve(client, search_query)

    user_prompt = (
        "ДОКУМЕНТЫ ИЗ БАЗЫ ЗНАНИЙ:\n"
        + context
        + "\n\n---\nВОПРОС (ИЛИ ДИАЛОГ) ПОЛЬЗОВАТЕЛЯ:\n"
        + dialog
        + "\n\nОтвет:"
    )

    try:
        answer = llm.generate(prompts.SYSTEM_PROMPT, user_prompt, client=client)
        if not answer or not answer.strip():
            answer = FALLBACK_ANSWER
    except Exception as exc:
        logger.warning("Ошибка генерации ответа LLM: %s", exc)
        answer = FALLBACK_ANSWER

    user_msg_id = repository.add_message(db, chat_id, "user", question)
    asst_msg_id = repository.add_message(
        db, chat_id, "assistant", answer, search_query=search_query
    )

    formatted_sources = []
    sources_to_save = []
    for s in retrieved_sources:
        doc_title = s.get("title") or s.get("doc_title")
        src_item = {
            "doc_id": s.get("doc_id"),
            "chunk_id": s.get("chunk_id"),
            "doc_title": doc_title,
            "path": s.get("path"),
            "snippet": s.get("snippet"),
        }
        formatted_sources.append(src_item)
        sources_to_save.append(
            {
                "doc_id": s.get("doc_id"),
                "chunk_id": s.get("chunk_id"),
                "snippet": s.get("snippet"),
            }
        )

    repository.add_message_sources(db, asst_msg_id, sources_to_save)

    return {
        "user_message_id": user_msg_id,
        "assistant_message_id": asst_msg_id,
        "answer": answer,
        "sources": formatted_sources,
    }
