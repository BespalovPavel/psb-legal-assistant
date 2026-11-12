"""Слой 2 (Models & Data): структуры документов, санитизация БЗ, парсинг метаданных и загрузка файлов."""

from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

import config


@dataclass
class LegalDocument:
    doc_id: str
    filename: str
    title: str
    raw_text: str
    header_summary: str
    is_expired: bool = False
    is_contract: bool = False
    entities: set[str] = field(default_factory=set)
    codes: set[str] = field(default_factory=set)
    chunk_ids: list[int] = field(default_factory=list)


@dataclass
class LegalChunk:
    chunk_id: int
    doc_id: str
    filename: str
    text_with_header: str
    raw_chunk_text: str


def normalize_yo(text: str) -> str:
    return text.replace("ё", "е").replace("Ё", "Е")


def sanitize_kb_text(text: str, filename: str = "") -> str:
    """Вырезает враждебные ИИ-инструкции (Indirect Prompt Injection) из документов БЗ."""
    clean_lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if config.KB_INJECTION_LINE_RE.search(line):
            print(f"[SECURITY] Удалена враждебная ИИ-инструкция из '{filename}': {line[:80]}...", file=sys.stderr)
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()


def pseudo_stem_ru(word: str) -> str:
    w = normalize_yo(word.lower())
    if len(w) <= 4 or any(ch.isdigit() for ch in w):
        return w
    if w.endswith(("инг", "инга", "ингом", "ингу", "инге")):
        return re.sub(r"(а|ом|у|е)$", "", w)
    stemmed = config.RU_ENDINGS_RE.sub("", w)
    return stemmed if len(stemmed) >= 3 else w[:4]


def tokenize_for_bm25(text: str) -> list[str]:
    raw_tokens = config.TOKEN_RE.findall(normalize_yo(text.lower()))
    result: list[str] = []
    for tok in raw_tokens:
        if len(tok) < 2 and not tok.isdigit():
            continue
        result.append(tok)
        if "-" in tok or "/" in tok:
            for sub in re.split(r"[-/]", tok):
                if len(sub) >= 2:
                    result.append(sub)
                    result.append(pseudo_stem_ru(sub))
        stem = pseudo_stem_ru(tok)
        if stem != tok:
            result.append(stem)
    return result


def normalize_entity_name(raw_entity: str) -> str:
    """Приводит название компании к каноническому стемм-виду ('северным складом' -> 'северн склад')."""
    val = normalize_yo(raw_entity.lower().strip())
    val = re.sub(r"^(ооо|ао|пао|зао|ип)\s+", "", val).strip()
    words = [pseudo_stem_ru(w) for w in re.findall(r"[а-яa-z0-9-]+", val) if len(w) >= 2]
    return " ".join(words)


def extract_entities_and_codes(text: str) -> tuple[set[str], set[str]]:
    norm = normalize_yo(text.lower())
    entities: set[str] = set()
    for m in config.QUOTED_ENTITY_RE.finditer(norm):
        canon = normalize_entity_name(m.group(1))
        if len(canon) >= 3:
            entities.add(canon)

    codes: set[str] = set()
    for m in config.DOC_NUMBER_RE.finditer(norm):
        codes.add(m.group(1).strip())
    for m in config.CONTRACT_CODE_RE.finditer(norm):
        codes.add(m.group(1).strip())

    return entities, codes


def parse_legal_document(doc_id: str, filename: str, raw_text: str) -> LegalDocument:
    sanitized_text = sanitize_kb_text(raw_text, filename)
    lines = [ln.strip() for ln in sanitized_text.split("\n") if ln.strip()]
    head_lines = lines[:6]
    head_block = "\n".join(head_lines)

    top_3_lines = "\n".join(lines[:3])
    is_expired = bool(config.EXPIRED_RE.search(top_3_lines)) and not bool(
        re.search(r"действует\s+с\s+\d{2}\.\d{2}\.\d{4}", top_3_lines, re.IGNORECASE)
    )

    title = filename
    for ln in head_lines:
        if ln.lower().startswith(("url:", "дата выгрузки:")):
            continue
        if ln.lower().startswith("источник:"):
            title = ln[len("источник:") :].strip()
            break
        if not config.EXPIRED_RE.search(ln):
            title = ln
            break

    entities, codes = extract_entities_and_codes(head_block + "\n" + filename)
    if not entities:
        entities, _ = extract_entities_and_codes(sanitized_text[:1000])

    is_contract = bool(
        re.search(r"\bдоговор\s+(?:поставки|аренды|возмездного|оказания|подряда|купли)", head_block, re.IGNORECASE)
        or (
            re.search(r"договор", filename, re.IGNORECASE)
            and not re.search(r"регламент|записка|положение|политика", filename, re.IGNORECASE)
        )
    )

    status_tag = "УТРАТИЛА СИЛУ" if is_expired else "ДЕЙСТВУЮЩАЯ (если не изменена более поздним актом/ДС)"
    header_summary = f"[Файл: {filename} | Документ: {title} | Статус: {status_tag}]"
    intro_context = " ; ".join(lines[:3])
    full_header = f"{header_summary}\n[Реквизиты: {intro_context}]"

    return LegalDocument(
        doc_id=doc_id,
        filename=filename,
        title=title,
        raw_text=sanitized_text,
        header_summary=full_header,
        is_expired=is_expired,
        is_contract=is_contract,
        entities=entities,
        codes=codes,
    )


def build_chunks(documents: list[LegalDocument]) -> list[LegalChunk]:
    chunks: list[LegalChunk] = []
    chunk_id = 0

    for doc in documents:
        text = doc.raw_text
        if len(text) <= config.CHUNK_MAX_CHARS:
            chunks.append(
                LegalChunk(
                    chunk_id=chunk_id,
                    doc_id=doc.doc_id,
                    filename=doc.filename,
                    text_with_header=f"{doc.header_summary}\n{text}",
                    raw_chunk_text=text,
                )
            )
            doc.chunk_ids.append(chunk_id)
            chunk_id += 1
            continue

        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        current_lines: list[str] = []
        current_len = 0

        for line in paragraphs:
            line_len = len(line) + 1
            if current_lines and current_len + line_len > config.CHUNK_MAX_CHARS:
                body = "\n".join(current_lines)
                chunks.append(
                    LegalChunk(
                        chunk_id=chunk_id,
                        doc_id=doc.doc_id,
                        filename=doc.filename,
                        text_with_header=f"{doc.header_summary}\n{body}",
                        raw_chunk_text=body,
                    )
                )
                doc.chunk_ids.append(chunk_id)
                chunk_id += 1

                overlap: list[str] = []
                ov_len = 0
                for prev in reversed(current_lines):
                    if ov_len + len(prev) > config.CHUNK_OVERLAP_CHARS:
                        break
                    overlap.insert(0, prev)
                    ov_len += len(prev) + 1
                current_lines = overlap
                current_len = ov_len

            current_lines.append(line)
            current_len += line_len

        if current_lines:
            body = "\n".join(current_lines)
            chunks.append(
                LegalChunk(
                    chunk_id=chunk_id,
                    doc_id=doc.doc_id,
                    filename=doc.filename,
                    text_with_header=f"{doc.header_summary}\n{body}",
                    raw_chunk_text=body,
                )
            )
            doc.chunk_ids.append(chunk_id)
            chunk_id += 1

    return chunks


def read_docx_bytes(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as doc:
        xml = doc.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join(
        "".join(x.text or "" for x in paragraph.iter(ns + "t"))
        for paragraph in root.iter(ns + "p")
    )


def decode_bytes_safe(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def find_questions_file() -> Path:
    roots = [config.DATA_DIR, Path(__file__).resolve().parent / config.DATA_DIR, Path.cwd(), Path(__file__).resolve().parent]
    for root in roots:
        for name in ("questions.csv", "demo_questions.csv"):
            cand = root / name
            if cand.is_file():
                return cand
    raise FileNotFoundError("Не найден файл questions.csv")


def load_questions(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not {"id", "question"}.issubset(reader.fieldnames):
            raise ValueError("В questions.csv нужны колонки id и question")
        rows = [(str(r["id"]).strip(), str(r["question"]).strip()) for r in reader]
    if not rows or any(not qid for qid, _ in rows):
        raise ValueError("В questions.csv отсутствуют вопросы или id")
    return rows


def load_knowledge_base() -> list[LegalDocument]:
    roots = [config.DATA_DIR, Path(__file__).resolve().parent / config.DATA_DIR, Path.cwd(), Path(__file__).resolve().parent]
    zip_names = ("knowledge-base.zip", "kb.zip", "knowledge_base.zip")
    dir_names = ("knowledge-base", "knowledge_base", "kb")

    raw_items: list[tuple[str, str]] = []

    zip_path: Path | None = None
    for root in roots:
        for zname in zip_names:
            cand = root / zname
            if cand.is_file():
                zip_path = cand
                break
        if zip_path:
            break

    if zip_path is not None:
        with zipfile.ZipFile(zip_path) as archive:
            for name in sorted(archive.namelist()):
                if name.endswith("/") or name.startswith("__MACOSX/") or "/." in name or Path(name).name.startswith("."):
                    continue
                suffix = Path(name).suffix.lower()
                if suffix not in {".txt", ".md", ".docx"}:
                    continue
                raw = archive.read(name)
                try:
                    text = read_docx_bytes(raw) if suffix == ".docx" else decode_bytes_safe(raw)
                except Exception as exc:
                    print(f"Пропущен документ {name}: {type(exc).__name__}", file=sys.stderr)
                    continue
                if text.strip():
                    raw_items.append((Path(name).name, text.strip()))

    if not raw_items:
        kb_dir: Path | None = None
        for root in roots:
            for dname in dir_names:
                cand = root / dname
                if cand.is_dir():
                    kb_dir = cand
                    break
            if kb_dir:
                break
        if kb_dir is None and config.DATA_DIR.is_dir():
            kb_dir = config.DATA_DIR

        if kb_dir is not None:
            for file_path in sorted(kb_dir.rglob("*")):
                if not file_path.is_file() or file_path.name.startswith("."):
                    continue
                suffix = file_path.suffix.lower()
                if suffix not in {".txt", ".md", ".docx"}:
                    continue
                try:
                    raw = file_path.read_bytes()
                    text = read_docx_bytes(raw) if suffix == ".docx" else decode_bytes_safe(raw)
                except Exception as exc:
                    print(f"Пропущен документ {file_path}: {type(exc).__name__}", file=sys.stderr)
                    continue
                if text.strip():
                    raw_items.append((file_path.name, text.strip()))

    if not raw_items:
        raise ValueError("В базе знаний нет читаемых документов")

    return [
        parse_legal_document(f"doc_{idx:04d}", fname, text)
        for idx, (fname, text) in enumerate(raw_items)
    ]
    
    
