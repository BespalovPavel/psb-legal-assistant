from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class CreateChatRequest(BaseModel):
    title: str | None = None


class ChatCreatedResponse(BaseModel):
    chat_id: str
    title: str


class ChatListItemResponse(BaseModel):
    chat_id: str
    title: str
    updated_at: str
    last_message: str | None = None


class MessageSourceDetail(BaseModel):
    doc_id: str | None = None
    chunk_id: str | None = None
    doc_title: str | None = None
    path: str | None = None
    snippet: str | None = None


class ChatMessageDetail(BaseModel):
    id: int
    role: str
    content: str
    created_at: str
    sources: list[MessageSourceDetail] = []


class ChatDetailResponse(BaseModel):
    chat_id: str
    title: str
    messages: list[ChatMessageDetail]


class DeleteChatResponse(BaseModel):
    status: str = "deleted"


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


class SendMessageResponse(BaseModel):
    user_message_id: int
    assistant_message_id: int
    answer: str
    sources: list[MessageSourceDetail]


class DocumentListItemResponse(BaseModel):
    doc_id: str
    title: str
    doc_type: str | None = None
    status: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    n_chunks: int = 0


class ChunkSummaryDetail(BaseModel):
    chunk_id: str
    ord: int
    path: str | None = None
    text: str
    is_heading: bool = False


class DocumentDetailResponse(BaseModel):
    document: dict[str, Any]
    chunks: list[ChunkSummaryDetail]


class ChunkWithDocResponse(BaseModel):
    chunk: dict[str, Any]
    document: dict[str, Any] | None = None
