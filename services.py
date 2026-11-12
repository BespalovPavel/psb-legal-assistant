import asyncio
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

import controllers
from repository import AssistantRepository
from schemas import (
    AuditLogDTO,
    ChatMessageDTO,
    ChatRequestDTO,
    ChatResponseDTO,
    DocumentSummaryDTO,
    HealthResponseDTO,
    SourceDocumentDTO,
)


def get_rag_controller(request: Request) -> controllers.LegalAssistantController:
    """Достаёт инициализированный RAG-контроллер из app.state (без циклических импортов!)."""
    return request.app.state.controller


ControllerDep = Annotated[controllers.LegalAssistantController, Depends(get_rag_controller)]
RepoDep = Annotated[AssistantRepository, Depends()]


class AssistantService:
    """Бизнес-логика приложения: объединяет память/журнал в БД (Repository) и RAG-ядро (Controller)."""

    def __init__(self, repository: RepoDep, controller: ControllerDep) -> None:
        self.repository = repository
        self.controller = controller

    async def get_health(self) -> HealthResponseDTO:
        db_ok = await self.repository.ping_db()
        base_health = self.controller.get_health()
        return HealthResponseDTO(
            status="ok",
            db_connected=db_ok,
            documents_loaded=base_health.documents_loaded,
            chunks_indexed=base_health.chunks_indexed,
            llm_model=base_health.llm_model,
            emb_model=base_health.emb_model,
            reranker_model=base_health.reranker_model,
        )

    async def list_documents(self) -> list[DocumentSummaryDTO]:
        docs = self.controller.list_documents()
        return [DocumentSummaryDTO(**d.model_dump()) for d in docs]

    async def get_document(self, doc_id: str) -> SourceDocumentDTO:
        doc = self.controller.get_document_by_id(doc_id)
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Документ '{doc_id}' не найден в базе знаний",
            )
        return SourceDocumentDTO(**doc.model_dump())

    async def handle_chat(self, req: ChatRequestDTO) -> ChatResponseDTO:
        session_id = req.session_id or str(uuid.uuid4())
        last_user_msg = req.messages[-1].content

        # 1. Если клиент прислал только 1 новое сообщение, но указал session_id —
        # подтягиваем предыдущий контекст диалога из БД!
        full_messages: list[ChatMessageDTO] = list(req.messages)
        if req.session_id and len(req.messages) == 1:
            db_history = await self.repository.get_chat_history(req.session_id)
            if db_history:
                full_messages = db_history + full_messages

        # 2. Вызываем RAG-контроллер в отдельном потоке, чтобы не блокировать async event loop
        enriched_req = ChatRequestDTO(session_id=session_id, messages=full_messages)
        raw_res = await asyncio.to_thread(self.controller.process_interactive_chat, enriched_req)

        # 3. Сохраняем шаг диалога и запись в журнал отладки (Audit Log) в БД
        await self.repository.save_chat_turn(
            session_id=session_id,
            user_message=last_user_msg,
            assistant_answer=raw_res.answer,
        )
        await self.repository.write_audit_log(
            session_id=session_id,
            user_query=last_user_msg,
            assistant_answer=raw_res.answer,
            grounding_status=raw_res.telemetry.grounding_status,
            has_injection_attempt=raw_res.telemetry.has_injection_attempt,
            has_expired_docs=raw_res.telemetry.has_expired_docs_in_context,
            cited_clauses=raw_res.telemetry.cited_clauses,
            source_filenames=[s.filename for s in raw_res.sources],
            latency_ms=raw_res.telemetry.latency_ms,
        )

        return ChatResponseDTO(
            session_id=session_id,
            answer=raw_res.answer,
            sources=[SourceDocumentDTO(**s.model_dump()) for s in raw_res.sources],
            telemetry=raw_res.telemetry.model_dump(),
        )

    async def get_session_history(self, session_id: str) -> list[ChatMessageDTO]:
        return await self.repository.get_chat_history(session_id)

    async def get_audit_logs(self, limit: int = 50) -> list[AuditLogDTO]:
        logs = await self.repository.get_recent_audit_logs(limit=limit)
        return [
            AuditLogDTO(
                id=row.id,
                session_id=row.session_id,
                user_query=row.user_query,
                assistant_answer=row.assistant_answer,
                grounding_status=row.grounding_status,
                has_injection_attempt=row.has_injection_attempt,
                has_expired_docs=row.has_expired_docs,
                cited_clauses=row.cited_clauses or [],
                source_filenames=row.source_filenames or [],
                latency_ms=row.latency_ms,
                created_at=row.created_at,
            )
            for row in logs
        ]


ServiceDep = Annotated[AssistantService, Depends()]