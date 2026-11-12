from datetime import datetime
from pydantic import BaseModel, Field


class ChatMessageDTO(BaseModel):
    role: str = Field(..., description="Роль: 'user' или 'assistant'")
    content: str = Field(..., description="Текст сообщения")


class ChatRequestDTO(BaseModel):
    session_id: str | None = Field(
        default=None,
        description="ID сессии чата в БД (если передан, история автоматически подтянется из БД)",
    )
    messages: list[ChatMessageDTO] = Field(..., min_length=1, description="Сообщения диалога")


class SourceDocumentDTO(BaseModel):
    doc_id: str
    filename: str
    title: str
    is_expired: bool
    is_contract: bool
    entities: list[str]
    codes: list[str]
    snippet: str
    full_text: str


class DocumentSummaryDTO(BaseModel):
    doc_id: str
    filename: str
    title: str
    is_expired: bool
    is_contract: bool
    entities: list[str]
    codes: list[str]
    char_length: int


class TrustTelemetryDTO(BaseModel):
    grounding_status: str
    status_label: str
    has_injection_attempt: bool
    has_expired_docs_in_context: bool
    counterparty_filter: list[str]
    cited_clauses: list[str]
    latency_ms: int


class ChatResponseDTO(BaseModel):
    session_id: str | None = None
    answer: str
    sources: list[SourceDocumentDTO]
    telemetry: TrustTelemetryDTO


class AuditLogDTO(BaseModel):
    id: int
    session_id: str | None
    user_query: str
    assistant_answer: str
    grounding_status: str
    has_injection_attempt: bool
    has_expired_docs: bool
    cited_clauses: list[str]
    source_filenames: list[str]
    latency_ms: int
    created_at: datetime


class HealthResponseDTO(BaseModel):
    status: str
    db_connected: bool
    documents_loaded: int
    chunks_indexed: int
    llm_model: str
    emb_model: str
    reranker_model: str