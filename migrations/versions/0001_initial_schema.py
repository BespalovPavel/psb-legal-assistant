"""initial_schema

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-11-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chats",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "title",
            sa.String(length=200),
            server_default=sa.text("'Новый чат'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("chat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role in ('user', 'assistant')", name="check_message_role"
        ),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_messages_chat_id"), "messages", ["chat_id"], unique=False
    )

    op.create_table(
        "documents",
        sa.Column("doc_id", sa.String(length=120), nullable=False),
        sa.Column("file", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=True),
        sa.Column("doc_type", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=True),
        sa.Column("doc_date", sa.String(length=10), nullable=True),
        sa.Column("valid_from", sa.String(length=10), nullable=True),
        sa.Column("valid_to", sa.String(length=10), nullable=True),
        sa.Column("number", sa.String(length=60), nullable=True),
        sa.Column("related_ref", sa.String(length=200), nullable=True),
        sa.Column(
            "parties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "n_chunks",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("doc_id"),
        sa.UniqueConstraint("file"),
    )
    op.create_index(
        op.f("ix_documents_content_hash"),
        "documents",
        ["content_hash"],
        unique=True,
    )

    op.create_table(
        "chunks",
        sa.Column("chunk_id", sa.String(length=200), nullable=False),
        sa.Column("doc_id", sa.String(length=120), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=True),
        sa.Column("section", sa.String(length=300), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "is_heading",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=60), nullable=True),
        sa.Column("valid_from", sa.String(length=10), nullable=True),
        sa.Column("valid_to", sa.String(length=10), nullable=True),
        sa.Column("prev_id", sa.String(length=200), nullable=True),
        sa.Column("next_id", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(
            ["doc_id"], ["documents.doc_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["next_id"], ["chunks.chunk_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["prev_id"], ["chunks.chunk_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("chunk_id"),
    )
    op.create_index(
        op.f("ix_chunks_doc_id"), "chunks", ["doc_id"], unique=False
    )

    op.create_table(
        "message_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("doc_id", sa.String(length=120), nullable=True),
        sa.Column("chunk_id", sa.String(length=200), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column(
            "position",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["chunks.chunk_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"], ["documents.doc_id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_message_sources_message_id"),
        "message_sources",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_message_sources_message_id"), table_name="message_sources"
    )
    op.drop_table("message_sources")
    op.drop_index(op.f("ix_chunks_doc_id"), table_name="chunks")
    op.drop_table("chunks")
    op.drop_index(op.f("ix_documents_content_hash"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_messages_chat_id"), table_name="messages")
    op.drop_table("messages")
    op.drop_table("chats")
