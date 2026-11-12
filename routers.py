from fastapi import APIRouter

from schemas import (
    AuditLogDTO,
    ChatMessageDTO,
    ChatRequestDTO,
    ChatResponseDTO,
    DocumentSummaryDTO,
    HealthResponseDTO,
    SourceDocumentDTO,
)
from services import ServiceDep

router = APIRouter(prefix="", tags=["api"])


@router.get("/api/health", response_model=HealthResponseDTO, tags=["System"])
async def get_health(service: ServiceDep) -> HealthResponseDTO:
    """Проверка статуса API, БД, индекса и подключённых моделей."""
    return await service.get_health()


@router.get("/api/documents", response_model=list[DocumentSummaryDTO], tags=["Knowledge Base"])
async def list_documents(service: ServiceDep) -> list[DocumentSummaryDTO]:
    """Возвращает список всех документов базы знаний с метаданными и статусом редакции."""
    return await service.list_documents()


@router.get("/api/documents/{doc_id}", response_model=SourceDocumentDTO, tags=["Knowledge Base"])
async def get_document(doc_id: str, service: ServiceDep) -> SourceDocumentDTO:
    """Возвращает полный текст и метаданные конкретного документа БЗ по его doc_id."""
    return await service.get_document(doc_id)


@router.post("/api/chat", response_model=ChatResponseDTO, tags=["Assistant"])
async def chat(req: ChatRequestDTO, service: ServiceDep) -> ChatResponseDTO:
    """Основной эндпоинт чата: поиск в БЗ, генерация ответа, сохранение контекста и аудит-лога в БД."""
    return await service.handle_chat(req)


@router.get("/api/sessions/{session_id}/messages", response_model=list[ChatMessageDTO], tags=["Memory & Audit"])
async def get_session_messages(session_id: str, service: ServiceDep) -> list[ChatMessageDTO]:
    """Возвращает историю сообщений диалога из БД по session_id."""
    return await service.get_session_history(session_id)


@router.get("/api/audit-logs", response_model=list[AuditLogDTO], tags=["Memory & Audit"])
async def get_audit_logs(service: ServiceDep, limit: int = 50) -> list[AuditLogDTO]:
    """Возвращает журнал отладки и контроля достоверности ответов ИИ из БД."""
    return await service.get_audit_logs(limit=limit)