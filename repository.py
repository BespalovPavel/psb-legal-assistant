import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select, text, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database_models import AuditLogORM, ChatMessageORM, ChatSessionORM
from database import get_session
from schemas import ChatMessageDTO

logger = logging.getLogger(__name__)

DBDep = Annotated[AsyncSession, Depends(get_session)]


class AssistantRepository:
    """Слой доступа к данным (БД): управление памятью диалогов и журналом отладки."""

    def __init__(self, session: DBDep) -> None:
        self.session = session

    async def ping_db(self) -> bool:
        try:
            await self.session.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.warning("БД недоступна при проверке health: %s", exc)
            return False

    async def get_chat_history(self, session_id: str) -> list[ChatMessageDTO]:
        """Возвращает сохранённую историю сообщений для указанной сессии."""
        try:
            stmt = (
                select(ChatMessageORM)
                .where(ChatMessageORM.session_id == session_id)
                .order_by(ChatMessageORM.id.asc())
            )
            result = await self.session.execute(stmt)
            rows = result.scalars().all()
            return [ChatMessageDTO(role=r.role, content=r.content) for r in rows]
        except Exception as exc:
            logger.warning("Не удалось прочитать историю чата из БД (session_id=%s): %s", session_id, exc)
            return []

    async def save_chat_turn(
        self,
        session_id: str,
        user_message: str,
        assistant_answer: str,
    ) -> None:
        """Сохраняет пару (вопрос пользователя + ответ ассистента) в память БД."""
        try:
            chat_sess = await self.session.get(ChatSessionORM, session_id)
            if chat_sess is None:
                chat_sess = ChatSessionORM(id=session_id)
                self.session.add(chat_sess)

            self.session.add(ChatMessageORM(session_id=session_id, role="user", content=user_message))
            self.session.add(ChatMessageORM(session_id=session_id, role="assistant", content=assistant_answer))
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            logger.warning("Не удалось сохранить сообщения в БД: %s", exc)

    async def write_audit_log(
        self,
        *,
        session_id: str | None,
        user_query: str,
        assistant_answer: str,
        grounding_status: str,
        has_injection_attempt: bool,
        has_expired_docs: bool,
        cited_clauses: list[str],
        source_filenames: list[str],
        latency_ms: int,
    ) -> None:
        """Записывает событие в журнал отладки и контроля достоверности."""
        try:
            log_entry = AuditLogORM(
                session_id=session_id,
                user_query=user_query,
                assistant_answer=assistant_answer,
                grounding_status=grounding_status,
                has_injection_attempt=has_injection_attempt,
                has_expired_docs=has_expired_docs,
                cited_clauses=cited_clauses,
                source_filenames=source_filenames,
                latency_ms=latency_ms,
            )
            self.session.add(log_entry)
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            logger.warning("Не удалось записать журнал аудита в БД: %s", exc)

    async def get_recent_audit_logs(self, limit: int = 50) -> list[AuditLogORM]:
        """Возвращает последние записи журнала отладки."""
        try:
            stmt = select(AuditLogORM).order_by(desc(AuditLogORM.id)).limit(limit)
            result = await self.session.execute(stmt)
            return list(result.scalars().all())
        except Exception as exc:
            logger.warning("Не удалось получить журнал аудита из БД: %s", exc)
            return []