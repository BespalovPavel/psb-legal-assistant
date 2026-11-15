from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship

from database import Base


class Chat(Base):
    __tablename__ = "chats"

    id = Column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    title = Column(
        String(200),
        nullable=False,
        server_default=text("'Новый чат'"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.created_at, Message.id",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role in ('user', 'assistant')", name="check_message_role"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)
    search_query = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    chat = relationship("Chat", back_populates="messages")
    sources = relationship(
        "MessageSource",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MessageSource.position, MessageSource.id",
    )


class Document(Base):
    __tablename__ = "documents"

    doc_id = Column(String(120), primary_key=True)
    file = Column(String(300), unique=True, nullable=False)
    title = Column(String(300), nullable=False)
    kind = Column(String(20), nullable=True)
    doc_type = Column(String(30), nullable=True)
    status = Column(String(60), nullable=True)
    doc_date = Column(String(10), nullable=True)
    valid_from = Column(String(10), nullable=True)
    valid_to = Column(String(10), nullable=True)
    number = Column(String(60), nullable=True)
    related_ref = Column(String(200), nullable=True)
    parties = Column(
        postgresql.JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    extra = Column(
        postgresql.JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    raw_text = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=False, unique=True, index=True)
    n_chunks = Column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Chunk.ord",
    )


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id = Column(String(200), primary_key=True)
    doc_id = Column(
        String(120),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ord = Column(Integer, nullable=False)
    path = Column(String(300), nullable=True)
    section = Column(String(300), nullable=True)
    text = Column(Text, nullable=False)
    note = Column(Text, nullable=True)
    is_heading = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    status = Column(String(60), nullable=True)
    valid_from = Column(String(10), nullable=True)
    valid_to = Column(String(10), nullable=True)
    prev_id = Column(
        String(200),
        ForeignKey("chunks.chunk_id", ondelete="SET NULL"),
        nullable=True,
    )
    next_id = Column(
        String(200),
        ForeignKey("chunks.chunk_id", ondelete="SET NULL"),
        nullable=True,
    )

    document = relationship("Document", back_populates="chunks")


class MessageSource(Base):
    __tablename__ = "message_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_id = Column(
        String(120),
        ForeignKey("documents.doc_id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_id = Column(
        String(200),
        ForeignKey("chunks.chunk_id", ondelete="SET NULL"),
        nullable=True,
    )
    snippet = Column(Text, nullable=True)
    position = Column(
        Integer,
        nullable=False,
        server_default=text("0"),
    )

    message = relationship("Message", back_populates="sources")
    document = relationship("Document")
    chunk = relationship("Chunk")
