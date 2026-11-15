import hashlib
import uuid
from pathlib import Path

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from database_models import Chat, Chunk, Document, Message, MessageSource
import ingest


def _to_uuid(val: str | uuid.UUID) -> uuid.UUID:
    if isinstance(val, uuid.UUID):
        return val
    return uuid.UUID(str(val))


def create_chat(db: Session, title: str | None = None) -> str:
    chat = Chat(title=title) if title else Chat()
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return str(chat.id)


def add_message(
    db: Session,
    chat_id: str | uuid.UUID,
    role: str,
    content: str,
    search_query: str | None = None,
) -> int:
    uid = _to_uuid(chat_id)
    msg = Message(
        chat_id=uid,
        role=role,
        content=content,
        search_query=search_query,
    )
    db.add(msg)
    db.query(Chat).filter(Chat.id == uid).update({"updated_at": func.now()})
    db.commit()
    db.refresh(msg)
    return int(msg.id)


def list_chats(db: Session) -> list[dict]:
    chats = db.query(Chat).order_by(desc(Chat.updated_at)).all()
    result = []
    for c in chats:
        last_msg = (
            db.query(Message.content)
            .filter(Message.chat_id == c.id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .first()
        )
        last_msg_content = last_msg[0] if last_msg else None
        result.append(
            {
                "chat_id": str(c.id),
                "title": c.title,
                "updated_at": c.updated_at.isoformat() if c.updated_at else "",
                "last_message": last_msg_content,
            }
        )
    return result


def get_chat(db: Session, chat_id: str | uuid.UUID) -> dict | None:
    try:
        uid = _to_uuid(chat_id)
    except (ValueError, TypeError):
        return None

    chat = db.query(Chat).filter(Chat.id == uid).first()
    if not chat:
        return None

    messages = (
        db.query(Message)
        .filter(Message.chat_id == uid)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )

    msg_list = []
    for m in messages:
        sources = (
            db.query(MessageSource)
            .filter(MessageSource.message_id == m.id)
            .order_by(MessageSource.position.asc(), MessageSource.id.asc())
            .all()
        )
        src_list = []
        for s in sources:
            doc_title = None
            chunk_path = None
            if s.doc_id:
                doc_row = (
                    db.query(Document.title).filter(Document.doc_id == s.doc_id).first()
                )
                if doc_row:
                    doc_title = doc_row[0]
            if s.chunk_id:
                chunk_row = (
                    db.query(Chunk.path).filter(Chunk.chunk_id == s.chunk_id).first()
                )
                if chunk_row:
                    chunk_path = chunk_row[0]
            src_list.append(
                {
                    "doc_id": s.doc_id,
                    "chunk_id": s.chunk_id,
                    "doc_title": doc_title,
                    "path": chunk_path,
                    "snippet": s.snippet,
                }
            )
        msg_list.append(
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else "",
                "sources": src_list,
            }
        )

    return {
        "chat_id": str(chat.id),
        "title": chat.title,
        "messages": msg_list,
    }


def delete_chat(db: Session, chat_id: str | uuid.UUID) -> bool:
    try:
        uid = _to_uuid(chat_id)
    except (ValueError, TypeError):
        return False

    chat = db.query(Chat).filter(Chat.id == uid).first()
    if not chat:
        return False

    db.delete(chat)
    db.commit()
    return True


def add_message_sources(db: Session, message_id: int, sources: list[dict]) -> None:
    for idx, s in enumerate(sources):
        src = MessageSource(
            message_id=message_id,
            doc_id=s.get("doc_id"),
            chunk_id=s.get("chunk_id"),
            snippet=s.get("snippet"),
            position=idx,
        )
        db.add(src)
    db.commit()


def list_documents(db: Session) -> list[dict]:
    docs = db.query(Document).order_by(Document.doc_id.asc()).all()
    return [
        {
            "doc_id": d.doc_id,
            "title": d.title,
            "doc_type": d.doc_type,
            "status": d.status,
            "valid_from": d.valid_from,
            "valid_to": d.valid_to,
            "n_chunks": d.n_chunks,
        }
        for d in docs
    ]


def get_document(db: Session, doc_id: str) -> dict | None:
    d = db.query(Document).filter(Document.doc_id == doc_id).first()
    if not d:
        return None
    return {
        "doc_id": d.doc_id,
        "file": d.file,
        "title": d.title,
        "kind": d.kind,
        "doc_type": d.doc_type,
        "status": d.status,
        "doc_date": d.doc_date,
        "valid_from": d.valid_from,
        "valid_to": d.valid_to,
        "number": d.number,
        "related_ref": d.related_ref,
        "parties": d.parties,
        "extra": d.extra,
        "raw_text": d.raw_text,
        "content_hash": d.content_hash,
        "n_chunks": d.n_chunks,
        "created_at": d.created_at.isoformat() if d.created_at else "",
    }


def get_document_chunks(db: Session, doc_id: str) -> list[dict]:
    chunks = (
        db.query(Chunk)
        .filter(Chunk.doc_id == doc_id)
        .order_by(Chunk.ord.asc())
        .all()
    )
    return [
        {
            "chunk_id": c.chunk_id,
            "ord": c.ord,
            "path": c.path,
            "text": c.text,
            "is_heading": c.is_heading,
            "section": c.section,
            "note": c.note,
            "status": c.status,
            "valid_from": c.valid_from,
            "valid_to": c.valid_to,
            "prev_id": c.prev_id,
            "next_id": c.next_id,
        }
        for c in chunks
    ]


def get_chunk(db: Session, chunk_id: str) -> dict | None:
    chunk = db.query(Chunk).filter(Chunk.chunk_id == chunk_id).first()
    if not chunk:
        return None
    doc_dict = get_document(db, chunk.doc_id)
    chunk_dict = {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "ord": chunk.ord,
        "path": chunk.path,
        "section": chunk.section,
        "text": chunk.text,
        "note": chunk.note,
        "is_heading": chunk.is_heading,
        "status": chunk.status,
        "valid_from": chunk.valid_from,
        "valid_to": chunk.valid_to,
        "prev_id": chunk.prev_id,
        "next_id": chunk.next_id,
    }
    return {
        "chunk": chunk_dict,
        "document": doc_dict,
    }


def count_documents(db: Session) -> int:
    return db.query(func.count(Document.doc_id)).scalar() or 0


def ingest_knowledge_base(
    db: Session, folder: str = "data/knowledge-base"
) -> dict:
    folder_path = Path(folder)
    if not folder_path.is_dir():
        alt = Path(__file__).resolve().parent / folder
        if alt.is_dir():
            folder_path = alt

    files = sorted(folder_path.rglob("*.txt"))
    files = [f for f in files if not f.name.startswith(".")]

    stats = {"load": 0, "skip": 0, "update": 0}

    existing_docs = {d.file: d for d in db.query(Document).all()}
    used_ids = {d.doc_id for d in existing_docs.values()}

    extra_keys = {
        "edition_notes",
        "amendment_dates",
        "amends_points",
        "dates_mentioned",
        "source",
        "url",
        "export_date",
        "ref",
        "chars",
    }

    for f in files:
        raw_text = ingest.read(f)
        content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        kind, title = ingest.classify(f.name)

        existing = existing_docs.get(f.name)
        action = "load"
        if existing:
            if existing.content_hash == content_hash:
                stats["skip"] += 1
                continue
            else:
                db.query(Chunk).filter(Chunk.doc_id == existing.doc_id).delete()
                db.query(Document).filter(Document.doc_id == existing.doc_id).delete()
                db.flush()
                used_ids.discard(existing.doc_id)
                action = "update"

        base_slug = ingest.slug(title)
        doc_id = base_slug
        k = 1
        while doc_id in used_ids:
            k += 1
            doc_id = f"{base_slug}-{k}"
        used_ids.add(doc_id)

        quarantine = []
        parse_fn = ingest.parse_law if kind == "law" else ingest.parse_company
        parsed_doc, parsed_chunks = parse_fn(raw_text, title, f.name, doc_id, quarantine)

        extra_data = {k: parsed_doc[k] for k in extra_keys if k in parsed_doc}

        doc_record = Document(
            doc_id=doc_id,
            file=f.name,
            title=parsed_doc.get("title", title),
            kind=parsed_doc.get("kind", kind),
            doc_type=parsed_doc.get("doc_type"),
            status=parsed_doc.get("status"),
            doc_date=parsed_doc.get("doc_date"),
            valid_from=parsed_doc.get("valid_from"),
            valid_to=parsed_doc.get("valid_to"),
            number=parsed_doc.get("number"),
            related_ref=parsed_doc.get("related_ref"),
            parties=parsed_doc.get("parties", []),
            extra=extra_data,
            raw_text=raw_text,
            content_hash=content_hash,
            n_chunks=len(parsed_chunks),
        )
        db.add(doc_record)
        db.flush()

        # Pass 1: Insert all chunks with prev_id=None, next_id=None
        chunk_records = []
        for idx, c in enumerate(parsed_chunks):
            rec = Chunk(
                chunk_id=c["chunk_id"],
                doc_id=doc_id,
                ord=idx,
                path=c.get("path"),
                section=c.get("section"),
                text=c["text"],
                note=c.get("note"),
                is_heading=bool(c.get("is_heading", False)),
                status=c.get("status"),
                valid_from=c.get("valid_from"),
                valid_to=c.get("valid_to"),
                prev_id=None,
                next_id=None,
            )
            db.add(rec)
            chunk_records.append(rec)
        db.flush()

        # Pass 2: UPDATE prev_id and next_id
        for idx, c in enumerate(parsed_chunks):
            p_id = c.get("prev_id")
            n_id = c.get("next_id")
            if p_id or n_id:
                rec = chunk_records[idx]
                rec.prev_id = p_id
                rec.next_id = n_id

        db.commit()
        stats[action] += 1
        existing_docs[f.name] = doc_record

    db.commit()
    return stats
