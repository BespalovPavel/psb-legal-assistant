from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import uvicorn

from database import Base, SessionLocal, engine
import database_models  # noqa: F401 - registers models on Base.metadata
import repository
from retriever import HybridLegalRetriever
from routers import router
from services import LLMClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Синхронное создание таблиц, если они не существуют
    Base.metadata.create_all(engine, checkfirst=True)

    # 2. Инджест базы знаний при пустой таблице документов
    with SessionLocal() as db:
        if repository.count_documents(db) == 0:
            repository.ingest_knowledge_base(db, folder="data/knowledge-base")

    # 3. HTTP-клиент с таймаутом 90 секунд
    app.state.client = httpx.Client(timeout=90.0)

    # 4. Инициализация индекса гибридного ретривера из БД
    with SessionLocal() as db:
        app.state.index = HybridLegalRetriever.from_db(db)

    # 5. Инициализация клиента LLM
    app.state.llm = LLMClient()

    yield

    # Shutdown: закрытие HTTP-клиента
    if hasattr(app.state, "client") and app.state.client is not None:
        app.state.client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ПСБ Юридический ИИ-ассистент",
        description="Веб-контур юридического ИИ-ассистента на базе PostgreSQL и RAG",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
