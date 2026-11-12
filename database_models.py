from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass


class ChatSessionORM(Base):
    """Таблица сессий диалогов (память контекста)."""
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    messages: Mapped[list["ChatMessageORM"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessageORM.id"
    )


class ChatMessageORM(Base):
    """Таблица сообщений внутри сессии диалога."""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32))  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session: Mapped["ChatSessionORM"] = relationship(back_populates="messages")


class AuditLogORM(Base):
    """Журнал аудита и отладки RAG (для контроля достоверности и разбора полётов)."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_query: Mapped[str] = mapped_column(Text)
    assistant_answer: Mapped[str] = mapped_column(Text)
    grounding_status: Mapped[str] = mapped_column(String(64))
    has_injection_attempt: Mapped[bool] = mapped_column(Boolean, default=False)
    has_expired_docs: Mapped[bool] = mapped_column(Boolean, default=False)
    cited_clauses: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_filenames: Mapped[list[str]] = mapped_column(JSON, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )