"""Слой 1 (Configuration): чтение переменных окружения, лимиты и регулярные выражения."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные из файла .env в os.environ ДО чтения os.getenv()!
ENV_FILE_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_FILE_PATH, override=False)

GLOBAL_START_TIME = time.monotonic()
HARD_TIME_BUDGET_SEC = 19 * 60 + 10  # Гарантированный запас до 20-минутного таймаута


def env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    return default if not value or value == name else value


def env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(env(name))))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return max(0.0, min(2.0, float(env(name))))
    except ValueError:
        return default


DATA_DIR = Path(env("DATA_DIR", "data"))
API_BASE = (env("LLM_BASE_URL") or env("BASE_URL") or env("OPENAI_BASE_URL")).rstrip("/")
LLM_KEY = env("LLM_API_KEY") or env("OPENAI_API_KEY")
EMBED_KEY = env("EMBEDDER_API_KEY") or LLM_KEY
RERANK_KEY = env("RERANKER_API_KEY") or LLM_KEY

LLM_MODEL = env("LLM_MODEL") or env("GEN_MODEL") or env("OPENAI_MODEL", "deepseek/deepseek-v4.1-flash")
EMB_MODEL = env("EMB_MODEL", "baai/bge-m3")
RERANKER_MODEL = env("RERANKER_MODEL", "Qwen/Qwen3-Reranker-8B")

IS_GOOGLE_API = "googleapis.com" in API_BASE.lower()

print(
    f"[CONFIG] Загружен API_BASE='{API_BASE}' | MODEL='{LLM_MODEL}' | GOOGLE={IS_GOOGLE_API}",
    flush=True,
)

ENV_TOP_K = env_int("TOP_K", 8, 1, 30)
ENV_RERANK_TOP_N = env_int("RERANKER_TOP_N", 6, 1, 15)

RETRIEVAL_CANDIDATES = max(28, ENV_TOP_K * 5)
RERANK_TOP_CHUNKS = max(10, ENV_RERANK_TOP_N * 2)
MAX_CONTEXT_DOCS = 5

DEFAULT_MAX_TOKENS = 2500 if IS_GOOGLE_API else 1536
MAX_TOKENS = env_int("MAX_TOKENS", DEFAULT_MAX_TOKENS, 512, 8192)
if IS_GOOGLE_API and MAX_TOKENS < 2500:
    MAX_TOKENS = 2500

MAX_WORKERS = env_int("MAX_WORKERS", 2 if IS_GOOGLE_API else 4, 1, 8)
TEMPERATURE = min(0.05, env_float("TEMPERATURE", 0.0))

CHUNK_MAX_CHARS = 1600
CHUNK_OVERLAP_CHARS = 250
SHORT_DOC_THRESHOLD = 4800
MAX_TOTAL_CONTEXT_CHARS = 22000
MAX_ANSWER_CHARS = 9500

FALLBACK_ANSWER = (
    "В предоставленной базе знаний недостаточно данных для формирования достоверного ответа "
    "либо сервис языковой модели временно недоступен."
)

# Паттерн для удаления отравленных инструкций (Indirect Prompt Injection) внутри файлов БЗ
KB_INJECTION_LINE_RE = re.compile(
    r"(внимание\s+для\s+ии|инструкци[яи]\s+для\s+(?:ии|ассистента|модели|бота)|"
    r"игнорируй\w*\s+все\s+(?:остальные\s+)?документы|"
    r"не\s+упоминай\s+эту\s+инструкцию|"
    r"system\s+prompt|ignore\s+all\s+previous\s+instructions)",
    re.IGNORECASE,
)

# Паттерн для детекции прямых инъекций в вопросе пользователя
USER_INJECTION_RE = re.compile(
    r"(ignore\s+previous|забудь\s+все\s+инструкции|системн\w+\s+промт|system\s+prompt|"
    r"ты\s+больше\s+не\s+юрист|режим\s+разработчика|developer\s+mode|новое\s+системное\s+сообщение|"
    r"игнорируй\s+базу\s+знаний)",
    re.IGNORECASE,
)

TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[-./][0-9A-Za-zА-Яа-яЁё]+)*")
RU_ENDINGS_RE = re.compile(
    r"(ами|ями|ого|его|ому|ему|ими|ыми|ым|им|ою|ею|ть|ти|ет|ют|ит|ат|ят|ов|ев|ей|ий|ый|ой|ая|яя|ое|ее|ые|ие|ам|ям|ах|ях|ом|ем|ую|юю|а|я|о|е|и|ы|у|ю)$"
)

QUOTED_ENTITY_RE = re.compile(r"[«\"„]([^»\"“]{2,60})[»\"“]")
DOC_NUMBER_RE = re.compile(
    r"(?:№|N)\s*([0-9А-Яа-яA-Za-z]+(?:[-/][0-9А-Яа-яA-Za-z]+)*)",
    re.IGNORECASE,
)
CONTRACT_CODE_RE = re.compile(r"\b([А-ЯA-Z]{1,4}-\d{1,4}/\d{4}|\d{1,4}-[А-ЯA-Z]{1,3})\b", re.IGNORECASE)
EXPIRED_RE = re.compile(r"(редакция\s+утратила\s+силу|утратил[аои]?\s+силу\s+с\s+\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)
ARTICLE_REF_RE = re.compile(r"(?:стать[яеиюй]|ст\.?)\s*(\d+(?:\.\d+)?)", re.IGNORECASE)