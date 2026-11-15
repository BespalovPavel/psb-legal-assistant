# Руководство для бэкенд-разработчиков (PSB Legal Assistant)

Документ описывает архитектуру связки **Next.js Frontend / BFF (`frontend/`) ↔ FastAPI (корень репозитория)**, фактический контракт REST API (с учётом логики UI), схему PostgreSQL/Alembic, переменные окружения и чек-лист проверки изменений.

Дополнительно:
- [README.md](../README.md) — общий обзор, Docker Compose и локальный запуск;
- [WEB_INTEGRATION.md](../WEB_INTEGRATION.md) — базовая спецификация веб-протокола.

---

## 1. Архитектура: как фронтенд общается с бэкендом

```text
Браузер (http://localhost:3000)
   │  fetch("/api/...")
   ▼
Next.js Route Handler: frontend/app/api/[...path]/route.ts  (BFF-прокси)
   │  ${PSB_API_URL}/api/...  (cache: "no-store", timeout = PSB_PROXY_TIMEOUT_MS)
   ▼
FastAPI: main.py + routers.py (порт 8000)
   │  SQLAlchemy 2.0 + HybridLegalRetriever + LLMClient
   ▼
PostgreSQL 14+ (порт 5432) + внешние LLM / Embedding / Reranker API
```

### Важные свойства BFF-прокси (`frontend/app/api/[...path]/route.ts`)
1. **Единый origin без браузерного CORS:** браузер обращается только к `/api/*` на адресе Next.js (`localhost:3000`). По умолчанию прокси использует `PSB_API_URL=http://127.0.0.1:8000` (в `compose.yaml` для контейнера `frontend` задано `http://backend:8000`).
2. **Таймауты:** по умолчанию `PSB_PROXY_TIMEOUT_MS=200000` (200 секунд), что перекрывает внутренний `httpx.Client(timeout=90.0)` в `main.py` и время генерации RAG. При таймауте прокси возвращает **`504`** (`{"detail": "Превышено время ожидания ответа от сервера"}`), при недоступности порта FastAPI — **`502`** (`{"detail": "Бэкенд ПСБ Юридического ассистента недоступен"}`).
3. **Кодирование URL и безопасность пути:** каждый сегмент пути кодируется через `encodeURIComponent`. Например, `chunk_id` вида `dogovor:p-6-3` передаётся как `/api/chunks/dogovor%3Ap-6-3` — FastAPI автоматически декодирует `%3A` обратно в `:`. Сегменты `.` / `..` и управляющие символы отклоняются прокси со статусом `400`.
4. **Пересылаемые заголовки и методы:** проксирует `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`. В upstream передаётся `accept` и (для `POST`/`PUT`/`PATCH` с непустым телом) `content-type`; клиенту возвращаются только `content-type` и `cache-control`. Заголовок `Authorization` и cookie сейчас не пересылаются — при добавлении аутентификации потребуется расширить `forwardHeaders` в `frontend/app/api/[...path]/route.ts`.

---

## 2. Контракт REST API и фактические ожидания UI

Маршруты описаны в [`routers.py`](../routers.py) (роутер с префиксом `/api`) и валидируются схемами в [`schemas.py`](../schemas.py). На фронтенде контракт закреплён в [`frontend/types/legal.ts`](../frontend/types/legal.ts) и [`frontend/lib/legal-api.ts`](../frontend/lib/legal-api.ts).

### Обработка ошибок (что ожидает UI)
Фронтенд извлекает текст ошибки из JSON-ответа FastAPI (`extractDetailFromPayload` в `frontend/lib/legal-api.ts`) в следующем приоритете:
1. `{"detail": "Текст ошибки"}` — стандартный `HTTPException` FastAPI;
2. `{"detail": [{"msg": "..."}]}` — ошибка валидации Pydantic (`422`);
3. fallback-сообщения по коду состояния (`400`, `404`, `422`, `502`, `503`, `504`).

Ошибки выводятся во всплывающем уведомлении (`ToastRegion`; при открытом модальном окне тост откладывается до закрытия модалки).

---

### Эндпоинты чатов

| Метод и путь | Тело запроса | Успешный ответ | Примечания |
|---|---|---|---|
| `GET /api/chats` | — | `200 OK`: `ChatListItemResponse[]` | Сортировка по `updated_at DESC`. Поля: `chat_id`, `title`, `updated_at` (ISO 8601), `last_message` (`string \| null`). |
| `POST /api/chats` | `{ "title"?: string }` (опционально) | `201 Created`: `{ "chat_id": string, "title": string }` | Если `title` не передан, БД ставит `'Новый чат'`. UI формирует заголовок (до 72 символов) из первого вопроса. |
| `GET /api/chats/{chat_id}` | — | `200 OK`: `ChatDetailResponse` | Поля: `chat_id`, `title`, `messages[]` (`id`, `role`, `content`, `created_at`, `sources[]`). Несуществующий или невалидный UUID → `404`. |
| `DELETE /api/chats/{chat_id}` | — | `200 OK`: `{ "status": "deleted" }` | Несуществующий `chat_id` → `404`. |
| `POST /api/chats/{chat_id}/messages` | `{ "content": string }` (`min_length=1`) | `200 OK`: `SendMessageResponse` | Поля ответа: `user_message_id`, `assistant_message_id`, `answer`, `sources[]`. Если не инициализированы `app.state.client`, `llm` или `index` → `503`. |

#### Критичные инварианты отправки сообщения (UI)
- **Двухшаговый старт диалога без дублей:** если активного `chat_id` ещё нет, фронтенд сначала вызывает `POST /api/chats`, сохраняет полученный `chat_id`, затем отправляет `POST /api/chats/{chat_id}/messages`. При ошибке отправки вопроса (`500`/`503`/`504`) **вопрос остаётся в поле ввода**, `chat_id` сохраняется, а повторный клик уходит в тот же `chat_id` без дубля `POST /api/chats`.
- **Чистый текст ответа (`answer`):** интерфейс намеренно рендерит `answer` как plain text (`whitespace-pre-wrap`), без Markdown-парсера и HTML. Структуру ответа рекомендуется задавать переносами строк `\n`, а не Markdown-разметкой.
- **Источники (`sources`):** элемент массива:
  ```json
  {
    "doc_id": "dogovor-arendy-a-08-2024",
    "chunk_id": "dogovor-arendy-a-08-2024:p-6-3",
    "doc_title": "Договор аренды А-08-2024 Северный Склад",
    "path": "п. 6.3",
    "snippet": "6.3. При прекращении настоящего Договора..."
  }
  ```
  На клиенте `sanitizeSourceText` (`frontend/lib/legal-format.ts`) удаляет внутренние маркеры `ДОКУМЕНТ #1`, `=== ДОКУМЕНТ #1 ... ===`, `документ №2`, но бэкенду лучше изначально отдавать чистые `doc_title` и `path`. Если и `chunk_id`, и `doc_id` равны `null`, строка источника некликабельна.

---

### Эндпоинты базы знаний и просмотра фрагментов

| Метод и путь | Успешный ответ | Как данные используются на фронтенде |
|---|---|---|
| `GET /api/documents` | `200 OK`: `DocumentListItemResponse[]` | Список в модалке «База знаний ПСБ» (`KnowledgeBaseModal.tsx`). Ожидаются: `doc_id`, `title`, `doc_type`, `status`, `valid_from`, `valid_to`, `n_chunks`. |
| `GET /api/documents/{doc_id}` | `200 OK`: `DocumentDetailResponse` | Полный документ и его чанки (`document` + `chunks[]` с `chunk_id`, `ord`, `path`, `text`, `is_heading`). Если `document.raw_text` пуст/`null`, клиент собирает текст из отсортированных по `ord` чанков. Отсутствующий `doc_id` → `404`. |
| `GET /api/chunks/{chunk_id}` | `200 OK`: `ChunkWithDocResponse` | Карточка фрагмента (`chunk` + `document`). Поля `chunk.prev_id` и `chunk.next_id` управляют кнопками «Предыдущий фрагмент» и «Следующий фрагмент». Также выводятся `chunk.section` и `chunk.note`. Не найден → `404`. |

#### Специальные правила на стороне UI
1. **Классификация и фильтры БЗ (`frontend/lib/legal-format.ts`, `KnowledgeBaseModal.tsx`):**
   - `doc_type === "law"` → вкладка **«Законы»**;
   - любое другое значение (`contract`, `addendum`, `regulation`, `letter`, `memo`, `other` и т. д.) → вкладка **«Документы компании»** (`doc_type !== "law"`);
   - в `status` подстрока `"утратил"` (без учёта регистра) задаёт оранжевый статус и попадание во вкладку **«Утратили силу»**; подстрока `"действ"` — действующий документ;
   - даты `valid_from` / `valid_to` форматируются в `DD.MM.YYYY`.
2. **Синтетический идентификатор `:whole` и fallback при `404` (`SourceViewerModal.tsx`):**
   - если `chunk_id` отсутствует или оканчивается на `:whole` (например `doc-memo:whole`), клиент **не вызывает** `GET /api/chunks/{chunk_id}`, а сразу запрашивает `GET /api/documents/{doc_id}`;
   - если `GET /api/chunks/{chunk_id}` вернул `404`, но у источника указан `doc_id`, UI автоматически переключается на `GET /api/documents/{doc_id}`.

---

## 3. База данных PostgreSQL, Alembic и загрузка базы знаний

### Таблицы БД (`database_models.py`, миграция `migrations/versions/0001_initial_schema.py`)
- **`chats`**: `id` (`UUID`, PK, `gen_random_uuid()`), `title`, `created_at`, `updated_at`.
- **`messages`**: `id` (`Integer` PK), `chat_id` (FK `chats.id` CASCADE), `role` (`'user' | 'assistant'`), `content`, `search_query`, `created_at`.
- **`message_sources`**: `id` (`Integer` PK), `message_id` (FK `messages.id` CASCADE), `doc_id` (FK `documents.doc_id` SET NULL), `chunk_id` (FK `chunks.chunk_id` SET NULL), `snippet`, `position`.
- **`documents`**: `doc_id` (`String(120)` PK), `file` (UNIQUE), `title`, `kind`, `doc_type`, `status`, `doc_date`, `valid_from`, `valid_to`, `number`, `related_ref`, `parties` (`JSONB`), `extra` (`JSONB`), `raw_text`, `content_hash` (UNIQUE), `n_chunks`, `created_at`.
- **`chunks`**: `chunk_id` (`String(200)` PK), `doc_id` (FK `documents.doc_id` CASCADE), `ord`, `path`, `section`, `text`, `note`, `is_heading`, `status`, `valid_from`, `valid_to`, `prev_id` / `next_id` (self-FK SET NULL).

### Особенность авто-инджеста (`main.py`)
При запуске FastAPI (`lifespan`):
1. Вызывается `Base.metadata.create_all(engine, checkfirst=True)`.
2. Инджест из `data/knowledge-base` запускается **только если таблица `documents` пуста** (`repository.count_documents(db) == 0`).
3. Инициализируются `app.state.client`, `app.state.index` и `app.state.llm`.

> **Важно при обновлении `.txt`-файлов БЗ:** если в таблице `documents` уже есть записи, перезапуск сервиса не переиндексирует изменённые файлы. Чтобы пересоздать схему и переинджестировать БЗ:
> ```bash
> psql -U assistant -d legal_assistant -f scripts/reset_db.sql
> alembic upgrade head
> uvicorn main:app --host 0.0.0.0 --port 8000
> ```

---

## 4. Переменные окружения

Шаблон: [`.env.example`](../.env.example).

| Переменная | Где используется | Значение по умолчанию | Назначение |
|---|---|---|---|
| `PSB_API_URL` | `frontend/` (Next.js BFF) | `http://127.0.0.1:8000` (Docker: `http://backend:8000`) | Базовый URL FastAPI-бэкенда |
| `PSB_PROXY_TIMEOUT_MS` | `frontend/` (Next.js BFF) | `200000` | Таймаут BFF-прокси в мс |
| `DATABASE_URL` | Backend (SQLAlchemy + Alembic) | `postgresql+psycopg2://assistant:assistant@localhost:5432/legal_assistant` | Строка подключения PostgreSQL |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Docker Compose / Postgres | `legal_assistant` / `assistant` / `assistant` | Реквизиты БД |
| `LLM_BASE_URL` | Backend (`config.py`) | — | URL OpenAI-совместимого API (`BASE_URL` / `OPENAI_BASE_URL`) |
| `LLM_API_KEY` | Backend (`config.py`) | — | Ключ API (также `OPENAI_API_KEY`, `EMBEDDER_API_KEY`, `RERANKER_API_KEY`) |
| `LLM_MODEL`, `EMB_MODEL`, `RERANKER_MODEL` | Backend (`config.py`) | `deepseek/deepseek-v4.1-flash`, `baai/bge-m3`, `Qwen/Qwen3-Reranker-8B` | Модели генерации, эмбеддинга и реранкинга |
| `TOP_K`, `RERANKER_TOP_N`, `MAX_TOKENS`, `MAX_WORKERS`, `TEMPERATURE`, `DATA_DIR` | Backend (`config.py`) | `8`, `6`, `1536` (`2500` для Google API), `4`, `0.0`, `data` | Опциональные параметры RAG |

---

## 5. Локальная разработка и проверка совместимости

### Разработка бэкенда с живым UI
1. Поднимите локальный PostgreSQL и примените миграции:
   ```bash
   pip install -r requirements-web.txt
   cp .env.example .env
   alembic upgrade head
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
   Swagger OpenAPI доступен на `http://127.0.0.1:8000/docs`.
2. В другом терминале запустите фронтенд:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```
   Интерфейс откроется на `http://localhost:3000`. Если FastAPI слушает другой порт, задайте `PSB_API_URL` (например в `frontend/.env.local` или перед запуском `npm run dev`).

### Чек-лист перед пушем
```bash
# Проверка Python-модулей бэкенда (из корня репозитория)
python -c "import glob, py_compile; [py_compile.compile(p, doraise=True) for p in glob.glob('*.py')]; import main, routers, database_models; print('BACKEND_IMPORTS_OK')"

# Валидация docker-compose
docker compose config --quiet

# Контрактные тесты прокси, форматтеров и UI + типы + линт + сборка
cd frontend
npm test
npm run typecheck
npm run lint
npm run build
```

При добавлении новых полей в эндпоинты обновите [`schemas.py`](../schemas.py), [`frontend/types/legal.ts`](../frontend/types/legal.ts) и тестовые моки в [`frontend/__tests__/legal-workspace.test.tsx`](../frontend/__tests__/legal-workspace.test.tsx).
