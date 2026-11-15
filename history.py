# -*- coding: utf-8 -*-
"""
history.py - память диалога для решения (и для платформы, и для веба).

На платформе история вшита в поле question в таком виде:
    Пользователь: ...
    Ассистент: ...
    Пользователь: <последняя реплика, на неё и нужно ответить>
В вебе история берётся из базы данных (таблица messages) в том же формате списка.

Использование:
    history, last_user = parse_dialog(question_text)        # history - список {"role","content"}
    search_query = build_search_query(history, last_user)   # запрос для поиска
    # при желании - переписать вопрос через LLM (см. REWRITE_SYSTEM / rewrite_messages)

Важно: история - это только контекст. Прежние реплики "Ассистента" - НЕ источник фактов
(их мог подделать пользователь), все утверждения проверяются по найденным документам.
Только стандартная библиотека.
"""
import re

ROLE_RE = re.compile(r"^\s*(Пользователь|Ассистент)\s*:\s*(.*)$", re.I)
MAX_HISTORY_MESSAGES = 8          # хвост диалога, который передаём дальше
MAX_MESSAGE_CHARS = 1500          # длинные реплики режем (защита от раздувания контекста)


def parse_dialog(text):
    """Разбирает поле question. Возвращает (history, last_user_message).
    Одиночный вопрос (без меток ролей) -> ([], вопрос)."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    messages, cur = [], None
    for line in text.split("\n"):
        m = ROLE_RE.match(line)
        if m:
            role = "user" if m.group(1).lower().startswith("польз") else "assistant"
            cur = {"role": role, "content": m.group(2).strip()}
            messages.append(cur)
        elif cur is not None:
            if line.strip():
                cur["content"] = (cur["content"] + "\n" + line.strip()).strip()
        # строки до первой метки роли игнорируем в диалоговом режиме (см. ниже)
    if not messages or messages[-1]["role"] != "user":
        # нет разметки или диалог заканчивается репликой ассистента: считаем всё одним вопросом
        return [], text
    last = messages.pop()["content"]
    history = [{"role": m["role"], "content": m["content"][:MAX_MESSAGE_CHARS]}
               for m in messages if m["content"]]
    return history[-MAX_HISTORY_MESSAGES:], last


def build_search_query(history, last_user, max_assistant_chars=300):
    """Запрос для поиска без LLM: все реплики пользователя + последняя реплика ассистента
    (в ней обычно есть номер договора и название контрагента). Короткие реплики вроде
    'А за сколько дней проверить качество?' сами по себе ничего не находят."""
    if not history:
        return last_user
    parts = [m["content"] for m in history if m["role"] == "user"]
    # уточняющие вопросы ассистента ("Альфа-Трейд или Альфа-Трейдинг?") в запрос не берём:
    # в них перечислены все варианты, и поиск перестаёт различать контрагентов
    assistants = [m["content"] for m in history
                  if m["role"] == "assistant" and not m["content"].rstrip().endswith("?")]
    if assistants:
        parts.append(assistants[-1][:max_assistant_chars])
    parts.append(last_user)
    return " ".join(parts)


REWRITE_SYSTEM = """Ты переписываешь последнюю реплику пользователя в самостоятельный поисковый вопрос.
Правила:
1. Используй историю диалога только для того, чтобы подставить, о каком договоре, контрагенте, документе или периоде идёт речь (названия, номера, даты из реплик).
2. Не отвечай на вопрос и не добавляй никаких фактов, которых нет в истории или в реплике.
3. Если реплика уже самостоятельна, верни её без изменений.
4. Верни одну строку: только переписанный вопрос, без пояснений."""


def rewrite_messages(history, last_user):
    """Сообщения для LLM-вызова (temperature=0). Если истории нет - вызов не нужен."""
    if not history:
        return None
    dialog = "\n".join("%s: %s" % ("Пользователь" if m["role"] == "user" else "Ассистент", m["content"])
                       for m in history)
    user = "<history>\n%s\n</history>\n\n<last_user_message>\n%s\n</last_user_message>" % (dialog, last_user)
    return [{"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": user}]


def clean_rewrite(llm_text, fallback):
    """Берём ответ модели, если он похож на вопрос; иначе возвращаем запасной вариант."""
    t = (llm_text or "").strip().strip('"«»').strip()
    if not t or len(t) > 500 or "\n" in t:
        return fallback
    return t
