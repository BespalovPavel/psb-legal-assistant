from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import httpx

import solution as core

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    docs = core.load_knowledge_base()
    chunks = core.build_chunks(docs)
    with httpx.Client(timeout=60.0) as client:
        STATE["index"] = core.HybridLegalIndex(docs, chunks, client)
    STATE["docs"] = docs
    yield


app = FastAPI(title="ПСБ Юридический ИИ-ассистент", lifespan=lifespan)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/chat")
def chat_endpoint(req: ChatRequest):
    # Собираем диалог в формат, идентичный тестовым кейсам
    dialogue_lines = []
    for m in req.messages:
        prefix = "Пользователь" if m.role == "user" else "Ассистент"
        dialogue_lines.append(f"{prefix}: {m.content}")
    raw_input = "\n".join(dialogue_lines) if len(dialogue_lines) > 1 else req.messages[-1].content

    search_query, has_inj = core.extract_search_query_from_input(raw_input)
    index: core.HybridLegalIndex = STATE["index"]

    with httpx.Client(timeout=85.0) as client:
        q_emb = None
        if index.chunk_embeddings is not None:
            embs = core.fetch_embeddings_batched(client, [search_query], batch_size=1)
            if embs is not None:
                q_emb = embs[0]
        context_str, sources = index.retrieve_and_assemble_context(client, search_query, q_emb)
        answer = core.generate_answer(client, raw_input, context_str, has_inj)

    return {
        "answer": answer,
        "has_injection_warning": has_inj,
        "sources": sources,
    }


@app.get("/", response_class=HTMLResponse)
def index_page():
    return """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>ПСБ — Юридический ИИ-ассистент</title>
<style>
  body { margin:0; font-family: system-ui, -apple-system, sans-serif; background:#f4f6fb; color:#1a2138; display:flex; height:100vh; }
  .chat-col { flex: 1; display:flex; flex-direction:column; border-right:1px solid #dce1ef; }
  .doc-col { width: 45%; display:flex; flex-direction:column; background:#fff; }
  header { background:#002882; color:#fff; padding:14px 20px; font-weight:700; display:flex; justify-content:space-between; align-items:center; }
  header span.badge { background:#ff5a1f; padding:4px 10px; border-radius:12px; font-size:12px; }
  #messages { flex:1; overflow-y:auto; padding:20px; display:flex; flex-direction:column; gap:12px; }
  .msg { max-width:82%; padding:12px 16px; border-radius:12px; line-height:1.5; font-size:14px; }
  .msg.user { align-self:flex-end; background:#002882; color:#fff; }
  .msg.assistant { align-self:flex-start; background:#fff; border:1px solid #dce1ef; }
  .input-bar { display:flex; gap:10px; padding:14px 20px; background:#fff; border-top:1px solid #dce1ef; }
  input { flex:1; padding:12px; border:1px solid #cbd2e6; border-radius:8px; font-size:14px; }
  button { background:#ff5a1f; color:#fff; border:none; padding:12px 20px; border-radius:8px; font-weight:600; cursor:pointer; }
  .sources-pane { padding:16px; overflow-y:auto; flex:1; }
  .src-card { border:1px solid #dce1ef; border-radius:8px; padding:12px; margin-bottom:10px; cursor:pointer; background:#f9fafe; }
  .src-card:hover { border-color:#002882; }
  .tag-ok { color:#0b7a3e; font-size:11px; font-weight:700; }
  .tag-exp { color:#c92a2a; font-size:11px; font-weight:700; }
  pre { white-space:pre-wrap; font-size:12.5px; background:#f1f3f9; padding:12px; border-radius:6px; max-height:380px; overflow-y:auto; }
</style>
</head>
<body>
  <div class="chat-col">
    <header>ПСБ | Юридический ИИ-ассистент <span class="badge">RAG + Контроль достоверности</span></header>
    <div id="messages">
      <div class="msg assistant">Здравствуйте! Задайте вопрос по договорам, внутренним регламентам или нормативным актам из базы знаний.</div>
    </div>
    <div class="input-bar">
      <input id="q" placeholder="Например: Какая арендная плата по договору с ООО «Северный Склад»?" onkeydown="if(event.key==='Enter')sendMsg()"/>
      <button onclick="sendMsg()">Отправить</button>
    </div>
  </div>
  <div class="doc-col">
    <header style="background:#162040;">Подтверждающие документы и фрагменты БЗ</header>
    <div class="sources-pane" id="sources">Нажмите на сообщение или задайте вопрос, чтобы увидеть проверенные источники и редакции документов.</div>
  </div>
<script>
let history = [];
let currentSources = [];
async function sendMsg() {
  const inp = document.getElementById('q');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  history.push({role:'user', content:text});
  renderMsg('user', text);
  const res = await fetch('/api/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({messages:history})});
  const data = await res.json();
  history.push({role:'assistant', content:data.answer});
  renderMsg('assistant', data.answer);
  currentSources = data.sources || [];
  renderSources(0);
}
function renderMsg(role, text) {
  const box = document.getElementById('messages');
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.textContent = text;
  box.appendChild(d);
  box.scrollTop = box.scrollHeight;
}
function renderSources(activeIdx) {
  const pane = document.getElementById('sources');
  if (!currentSources.length) { pane.innerHTML = 'Источники не найдены.'; return; }
  pane.innerHTML = currentSources.map((s, idx) => `
    <div class="src-card" onclick="renderSources(${idx})">
      <div class="${s.is_expired ? 'tag-exp' : 'tag-ok'}">${s.is_expired ? '⚠ РЕДАКЦИЯ УТРАТИЛА СИЛУ' : '✔ ДЕЙСТВУЮЩАЯ РЕДАКЦИЯ'}</div>
      <strong>${s.title}</strong> <small>(${s.filename})</small>
      ${idx === activeIdx ? `<pre>${s.full_text}</pre>` : `<div style="font-size:12px;color:#555;margin-top:6px;">${s.snippet.slice(0,220)}...</div>`}
    </div>
  `).join('');
}
</script>
</body>
</html>"""