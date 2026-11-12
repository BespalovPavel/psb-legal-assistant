"""Слой CONTROLLER: управление RAG-пайплайном для сервиса FastAPI и пакетного запуска solution.py."""

from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx

import config
import llm_client
import models
import prompts
import retriever
from schemas import (
    ChatRequestDTO,
    ChatResponseDTO,
    DocumentSummaryDTO,
    HealthResponseDTO,
    SourceDocumentDTO,
    TrustTelemetryDTO,
)

REFUSAL_MARKER_RE = re.compile(
    r"(в базе знаний нет документов|ответить по документам я не могу|в предоставленной базе отсутствуют|недостаточно данных)",
    re.IGNORECASE,
)


class LegalAssistantController:
    def __init__(self) -> None:
        self.documents = models.load_knowledge_base()
        self.chunks = models.build_chunks(self.documents)
        with httpx.Client(timeout=90.0) as init_client:
            self.index = retriever.HybridLegalIndex(self.documents, self.chunks, init_client)

    def get_health(self) -> HealthResponseDTO:
        return HealthResponseDTO(
            status="ok",
            db_connected=False,
            documents_loaded=len(self.documents),
            chunks_indexed=len(self.chunks),
            llm_model=config.LLM_MODEL,
            emb_model=config.EMB_MODEL,
            reranker_model=config.RERANKER_MODEL,
        )

    def list_documents(self) -> list[DocumentSummaryDTO]:
        return [
            DocumentSummaryDTO(
                doc_id=doc.doc_id,
                filename=doc.filename,
                title=doc.title,
                is_expired=doc.is_expired,
                is_contract=doc.is_contract,
                entities=sorted(doc.entities),
                codes=sorted(doc.codes),
                char_length=len(doc.raw_text),
            )
            for doc in self.documents
        ]

    def get_document_by_id(self, doc_id: str) -> SourceDocumentDTO | None:
        doc = self.index.doc_by_id.get(doc_id)
        if doc is None:
            return None
        return SourceDocumentDTO(
            doc_id=doc.doc_id,
            filename=doc.filename,
            title=doc.title,
            is_expired=doc.is_expired,
            is_contract=doc.is_contract,
            entities=sorted(doc.entities),
            codes=sorted(doc.codes),
            snippet=doc.raw_text[:800],
            full_text=doc.raw_text,
        )

    def get_all_kb_documents(self) -> list[SourceDocumentDTO]:
        return [self.get_document_by_id(doc.doc_id) for doc in self.documents]  # type: ignore[misc]

    def process_interactive_chat(self, req: ChatRequestDTO) -> ChatResponseDTO:
        t0 = time.monotonic()

        dialogue_lines: list[str] = []
        for m in req.messages:
            prefix = "Пользователь" if m.role == "user" else "Ассистент"
            dialogue_lines.append(f"{prefix}: {m.content.strip()}")
        raw_input = "\n".join(dialogue_lines) if len(dialogue_lines) > 1 else req.messages[-1].content.strip()

        search_query, has_inj = prompts.extract_search_query_from_input(raw_input)
        matched_cp, _ = self.index.detect_query_counterparties(search_query)

        with httpx.Client(timeout=85.0) as client:
            q_emb = None
            if self.index.chunk_embeddings is not None:
                embs = llm_client.fetch_embeddings_batched(client, [search_query], batch_size=1)
                if embs is not None:
                    q_emb = embs[0]

            context_str, raw_sources = self.index.retrieve_and_assemble_context(client, search_query, q_emb)
            answer = llm_client.generate_answer(client, raw_input, context_str, has_inj)

        latency_ms = int((time.monotonic() - t0) * 1000)
        has_expired = any(s["is_expired"] for s in raw_sources)
        is_refusal = bool(REFUSAL_MARKER_RE.search(answer))

        if has_inj:
            grounding_status = "INJECTION_BLOCKED"
            status_label = "Защита: манипуляция промптом заблокирована"
        elif is_refusal:
            grounding_status = "REFUSAL_NO_DATA"
            status_label = "Обоснованный отказ / Указание на нехватку данных в БЗ"
        else:
            grounding_status = "VERIFIED"
            status_label = "Подтверждено нормативной базой ПСБ"

        sources_dto: list[SourceDocumentDTO] = []
        for s in raw_sources:
            doc_obj = self.index.doc_by_id[s["doc_id"]]
            sources_dto.append(
                SourceDocumentDTO(
                    doc_id=doc_obj.doc_id,
                    filename=doc_obj.filename,
                    title=doc_obj.title,
                    is_expired=doc_obj.is_expired,
                    is_contract=doc_obj.is_contract,
                    entities=sorted(doc_obj.entities),
                    codes=sorted(doc_obj.codes),
                    snippet=s["snippet"],
                    full_text=doc_obj.raw_text,
                )
            )

        telemetry_dto = TrustTelemetryDTO(
            grounding_status=grounding_status,
            status_label=status_label,
            has_injection_attempt=has_inj,
            has_expired_docs_in_context=has_expired,
            counterparty_filter=sorted(matched_cp),
            cited_clauses=prompts.extract_cited_clauses(answer),
            latency_ms=latency_ms,
        )

        return ChatResponseDTO(
            session_id=req.session_id,
            answer=answer,
            sources=sources_dto,
            telemetry=telemetry_dto,
        )

    handle_chat = process_interactive_chat

    def run_batch_evaluation(self, questions: list[tuple[str, str]]) -> list[str]:
        parsed_queries = [prompts.extract_search_query_from_input(q_text) for _, q_text in questions]
        search_strings = [pq[0] for pq in parsed_queries]

        with httpx.Client(timeout=90.0) as init_client:
            query_embeddings = (
                llm_client.fetch_embeddings_batched(init_client, search_strings, batch_size=32)
                if self.index.chunk_embeddings is not None
                else None
            )

        def work(pos: int) -> tuple[int, str]:
            if time.monotonic() - config.GLOBAL_START_TIME > config.HARD_TIME_BUDGET_SEC:
                return pos, config.FALLBACK_ANSWER

            _, raw_question = questions[pos]
            search_query, has_inj = parsed_queries[pos]
            q_emb = query_embeddings[pos] if query_embeddings is not None else None

            try:
                with httpx.Client(timeout=85.0) as worker_client:
                    context_str, _ = self.index.retrieve_and_assemble_context(worker_client, search_query, q_emb)
                    ans = llm_client.generate_answer(worker_client, raw_question, context_str, has_inj)
                    return pos, ans
            except Exception as exc:
                print(f"[ERROR] Ошибка на вопросе #{pos}: {type(exc).__name__}", file=sys.stderr)
                return pos, config.FALLBACK_ANSWER

        answers = [config.FALLBACK_ANSWER] * len(questions)
        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as pool:
            futures = [pool.submit(work, i) for i in range(len(questions))]
            for finished, future in enumerate(as_completed(futures), 1):
                idx, answer = future.result()
                answers[idx] = answer if (answer and answer.strip()) else config.FALLBACK_ANSWER
                if finished % 10 == 0 or finished == len(questions):
                    elapsed = time.monotonic() - config.GLOBAL_START_TIME
                    print(f"[PROGRESS] Обработано {finished}/{len(questions)} ({elapsed:.1f} с)", flush=True)

        return answers