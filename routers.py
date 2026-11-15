from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
import repository
from schemas import (
    ChatCreatedResponse,
    ChatDetailResponse,
    ChatListItemResponse,
    ChunkWithDocResponse,
    CreateChatRequest,
    DeleteChatResponse,
    DocumentDetailResponse,
    DocumentListItemResponse,
    SendMessageRequest,
    SendMessageResponse,
)
import services

router = APIRouter(prefix="/api", tags=["api"])


@router.post(
    "/chats",
    response_model=ChatCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_chat(
    req: CreateChatRequest | None = None,
    db: Session = Depends(get_db),
) -> ChatCreatedResponse:
    title = req.title if req and req.title else None
    chat_id = repository.create_chat(db, title=title)
    chat = repository.get_chat(db, chat_id)
    chat_title = chat["title"] if chat else (title or "Новый чат")
    return ChatCreatedResponse(chat_id=chat_id, title=chat_title)


@router.get(
    "/chats",
    response_model=list[ChatListItemResponse],
)
def list_chats(
    db: Session = Depends(get_db),
) -> list[ChatListItemResponse]:
    return [ChatListItemResponse(**c) for c in repository.list_chats(db)]


@router.get(
    "/chats/{chat_id}",
    response_model=ChatDetailResponse,
)
def get_chat(
    chat_id: str,
    db: Session = Depends(get_db),
) -> ChatDetailResponse:
    chat = repository.get_chat(db, chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Чат '{chat_id}' не найден",
        )
    return ChatDetailResponse(**chat)


@router.delete(
    "/chats/{chat_id}",
    response_model=DeleteChatResponse,
)
def delete_chat(
    chat_id: str,
    db: Session = Depends(get_db),
) -> DeleteChatResponse:
    success = repository.delete_chat(db, chat_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Чат '{chat_id}' не найден",
        )
    return DeleteChatResponse(status="deleted")


@router.post(
    "/chats/{chat_id}/messages",
    response_model=SendMessageResponse,
)
def send_message(
    chat_id: str,
    req: SendMessageRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> SendMessageResponse:
    chat = repository.get_chat(db, chat_id)
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Чат '{chat_id}' не найден",
        )

    client = getattr(request.app.state, "client", None)
    llm = getattr(request.app.state, "llm", None)
    index = getattr(request.app.state, "index", None)

    if client is None or llm is None or index is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Сервис не инициализирован",
        )

    result = services.ask(
        db=db,
        chat_id=chat_id,
        question=req.content,
        client=client,
        llm=llm,
        index=index,
    )
    return SendMessageResponse(**result)


@router.get(
    "/documents",
    response_model=list[DocumentListItemResponse],
)
def list_documents(
    db: Session = Depends(get_db),
) -> list[DocumentListItemResponse]:
    return [DocumentListItemResponse(**d) for d in repository.list_documents(db)]


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentDetailResponse,
)
def get_document(
    doc_id: str,
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    doc = repository.get_document(db, doc_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Документ '{doc_id}' не найден",
        )
    chunks = repository.get_document_chunks(db, doc_id)
    chunk_items = [
        {
            "chunk_id": c["chunk_id"],
            "ord": c["ord"],
            "path": c["path"],
            "text": c["text"],
            "is_heading": c["is_heading"],
        }
        for c in chunks
    ]
    return DocumentDetailResponse(document=doc, chunks=chunk_items)


@router.get(
    "/chunks/{chunk_id}",
    response_model=ChunkWithDocResponse,
)
def get_chunk(
    chunk_id: str,
    db: Session = Depends(get_db),
) -> ChunkWithDocResponse:
    res = repository.get_chunk(db, chunk_id)
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Чанк '{chunk_id}' не найден",
        )
    return ChunkWithDocResponse(**res)
