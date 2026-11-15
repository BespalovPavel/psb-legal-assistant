#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py - превращает папку с .txt-файлами базы знаний в "карточки" (чанки).

Запуск:
    python ingest.py <папка_с_txt> [папка_для_результата]

Пример:
    python ingest.py knowledge-base out

Результат (в папке out):
    chunks.jsonl    - по одной карточке на строку (пункт регламента, часть статьи закона)
    docs.json       - паспорт каждого документа (тип, даты, статус, номера, стороны)
    report.txt      - краткий отчёт
    quarantine.json - строки, вырезанные как подозрительные инструкции для ИИ
Используется только стандартная библиотека Python 3.8+.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

MAX_CHARS = 1800  # максимальный размер одной карточки

MONTHS = {"января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
          "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
DATE_NUM = r"(\d{1,2})\.(\d{1,2})\.(\d{4})"
DATE_WORD = r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})"

LAW_NAMES = {"НК": "НК РФ", "ТК": "ТК РФ", "КоАП": "КоАП РФ",
             "152ФЗ": "152-ФЗ", "МРОТ": "82-ФЗ (МРОТ)"}

# Строки, похожие на попытку управлять ИИ-ассистентом изнутри документа
INJECTION_RE = re.compile("|".join([
    r"для\s+ии", r"ии[- ]ассистент", r"игнорируй", r"игнорировать\s+(все|предыдущ)",
    r"не\s+упоминай", r"ignore\s+(all|previous|the)", r"system\s*prompt",
    r"на\s+любой\s+вопрос.*отвечай", r"отвечай\s+[«\"']",
]), re.I)

HEAD_RE = re.compile(r"^(\d+)\.\s+([А-ЯЁA-Z].*)$")          # "2. Порядок согласования"
POINT_RE = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(.*)$")         # "2.3. текст"
LAW_ART_RE = re.compile(r"^Статья\s+(\d+(?:\.\d+)?)\.\s*(.*)$")
LAW_PART_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+\S")          # "1. текст", "1.1. текст"
ITEM_RE = re.compile(r"^(\d+(?:\.\d+)?)\)")                   # "3) текст"

# Служебные примечания Гаранта: "Часть 1 изменена с 1 сентября 2025 г. - Федеральный закон ..."
NOTE_RE = re.compile(
    r"^(Часть|Части|Статья|Пункт|Пункты|Подпункт|Подпункты|Абзац|Абзацы|Глава|Раздел|Название|Примечани\w*|"
    r"Наименование|Приложение)\b.*(изменен|дополнен|изложен|утратил|введен|исключен|признан)"
    r".*(\d{4}\s*г|Федеральн)", re.I)
NOTE2_RE = re.compile(r"^(О\s+(конституционно|проверке)|См\.)", re.I)

TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
              ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
               "r", "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def slug(s, n=60):
    s = "".join(TR.get(c, c) for c in s.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:n].strip("-")


def iso(d, m, y):
    return "%04d-%02d-%02d" % (int(y), int(m), int(d))


def find_dates(s):
    out = []
    for m in re.finditer(DATE_NUM, s):
        out.append((m.start(), iso(m[1], m[2], m[3])))
    for m in re.finditer(DATE_WORD, s):
        out.append((m.start(), iso(m[1], MONTHS[m[2]], m[3])))
    return sorted(out)


def date_after(pattern, text):
    m = re.search(pattern, text, re.I)
    if not m:
        return None
    ds = find_dates(text[m.end(): m.end() + 40])
    return ds[0][1] if ds else None


def read(path):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return Path(path).read_text(encoding=enc)
        except UnicodeDecodeError:
            pass
    return Path(path).read_text(encoding="utf-8", errors="replace")


def classify(filename):
    stem = Path(filename).stem
    cat, title = stem.split("__", 1) if "__" in stem else ("", stem)
    kind = "law" if cat.replace("_", " ").lower().startswith("закон") else "company"
    return kind, re.sub(r"\s+", " ", title.replace("_", " ")).strip()


def company_type(title):
    t = title.lower()
    if "доп" in t and "соглаш" in t:
        return "addendum"
    if "регламент" in t:
        return "regulation"
    if "письмо" in t:
        return "letter"
    if "служебная записка" in t:
        return "memo"
    if "договор" in t:
        return "contract"
    return "other"


def pack(paragraphs, max_chars=MAX_CHARS):
    pieces, cur, n = [], [], 0
    for p in paragraphs:
        if cur and n + len(p) + 1 > max_chars:
            pieces.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += len(p) + 1
    if cur:
        pieces.append(cur)
    return pieces


def explode(lines, max_chars=MAX_CHARS):
    """Строки длиннее лимита режем по предложениям."""
    out = []
    for l in lines:
        if len(l) <= max_chars:
            out.append(l)
            continue
        cur = ""
        for sent in re.split(r"(?<=[.;])\s+", l):
            if cur and len(cur) + len(sent) + 1 > max_chars:
                out.append(cur)
                cur = ""
            cur = (cur + " " + sent).strip()
        if cur:
            out.append(cur)
    return out


def split_pieces(lines, max_chars=MAX_CHARS):
    """Режет длинную часть статьи на карточки по границам подпунктов 1), 2), 2.1).
    Возвращает список (строки, метка_подпунктов)."""
    units, cur = [], []
    for l in lines:
        if ITEM_RE.match(l) and cur:
            units.append(cur)
            cur = []
        cur.append(l)
    if cur:
        units.append(cur)

    def label_of(piece_lines):
        labels = [m.group(1) + ")" for m in (ITEM_RE.match(x) for x in piece_lines) if m]
        if not labels:
            return None
        return labels[0] if len(labels) == 1 else labels[0] + "-" + labels[-1]

    pieces, cur, n = [], [], 0
    for unit in units:
        usize = sum(len(x) + 1 for x in unit)
        if usize > max_chars:                       # одиночный подпункт больше лимита
            if cur:
                pieces.append((cur, label_of(cur)))
                cur, n = [], 0
            subs = pack(explode(unit, max_chars), max_chars)
            first = label_of(unit)
            for k, sub in enumerate(subs):
                lab = first if k == 0 else ("%s продолж. %d" % (first, k + 1) if first else None)
                pieces.append((sub, lab))
            continue
        if cur and n + usize > max_chars:
            pieces.append((cur, label_of(cur)))
            cur, n = [], 0
        cur += unit
        n += usize
    if cur:
        pieces.append((cur, label_of(cur)))
    return pieces


def strip_injections(lines, doc_id, quarantine):
    clean = []
    for l in lines:
        if INJECTION_RE.search(l):
            quarantine.append({"doc_id": doc_id, "line": l})
        else:
            clean.append(l)
    return clean


class Builder:
    """Собирает карточки одного документа и проставляет связи prev/next."""

    def __init__(self, doc, item_word="п."):
        self.doc, self.item_word, self.chunks = doc, item_word, []

    def add(self, path, text, section=None, note=None, is_heading=False):
        d = self.doc
        self.chunks.append({
            "chunk_id": None, "doc_id": d["doc_id"], "doc_title": d["title"], "ref": d["ref"],
            "doc_kind": d["kind"], "doc_type": d["doc_type"], "path": path, "section": section,
            "text": text, "note": note, "is_heading": is_heading, "status": d["status"],
            "doc_date": d["doc_date"], "valid_from": d["valid_from"], "valid_to": d["valid_to"],
            "file": d["file"], "prev_id": None, "next_id": None,
        })

    def add_long(self, base_path, lines, section=None, note=None):
        pieces = split_pieces(lines)
        for i, (piece, label) in enumerate(pieces):
            path = base_path
            if len(pieces) > 1:
                path += (", %s %s" % (self.item_word, label)) if label else (", фрагм. %d/%d" % (i + 1, len(pieces)))
            text = "\n".join(piece)
            if i > 0:
                text = "[продолжение: %s...]\n%s" % (lines[0][:110], text)
            self.add(path, text, section, note if i == 0 else None)

    def finish(self):
        seen = {}
        for c in self.chunks:
            cid = "%s:%s" % (c["doc_id"], slug(c["path"], 40) or "chunk")
            seen[cid] = seen.get(cid, 0) + 1
            if seen[cid] > 1:
                cid += "-%d" % seen[cid]
            c["chunk_id"] = cid
        for i, c in enumerate(self.chunks):
            c["prev_id"] = self.chunks[i - 1]["chunk_id"] if i > 0 else None
            c["next_id"] = self.chunks[i + 1]["chunk_id"] if i + 1 < len(self.chunks) else None
        return self.chunks


# ---------------------------------------------------------------- документы компании
def parse_company(text, title, fname, doc_id, quarantine):
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    lines = strip_injections(raw_lines, doc_id, quarantine)
    head = "\n".join(lines[:6])
    dtype = company_type(title)

    status = "утратил силу" if (re.search(r"утратил[аио]?\s+силу", head, re.I)
                                or "утратил" in title.lower()) else "действует"
    doc_date = None
    for l in lines[:6]:
        if re.match(r"^(к\s+договору|утвержд|редакция)", l, re.I):
            continue
        ds = find_dates(l)
        if ds:
            doc_date = ds[0][1]
            break
    valid_from = (date_after(r"действует\s+с", head) or date_after(r"редакция\s+от", head) or doc_date)
    valid_to = date_after(r"утратил[аио]?\s+силу\s+с", head)
    m = re.search(r"к\s+договору[^\n]*?№\s*([\w\-/]+)", head, re.I)

    number = None
    if dtype in ("contract", "addendum", "letter", "memo"):
        mn = re.search(r"№\s*([\w\-/]+)", "\n".join(lines[:4]))
        number = mn.group(1) if mn else None
    parties = []
    if dtype in ("contract", "addendum"):
        for p in re.findall(r"ООО\s+«([^»]+)»", "\n".join(lines[:5])):
            if p not in parties:
                parties.append(p)
    amends = re.findall(r"[Пп]ункт\s+(\d+(?:\.\d+)+)", text) if dtype == "addendum" else []

    # в именах файлов "/" и точки заменены на "-" и пробелы: возвращаем читаемый вид
    for r in (number, m.group(1) if m else None):
        if r and "/" in r:
            title = title.replace(r.replace("/", "-"), r)
    title = re.sub(r"\b(\d{1,2}) (\d{2}) (\d{4})\b", r"\1.\2.\3", title)

    doc = {"doc_id": doc_id, "file": fname, "title": title, "ref": title, "kind": "company",
           "doc_type": dtype, "status": status, "doc_date": doc_date, "valid_from": valid_from,
           "valid_to": valid_to, "number": number, "related_ref": m.group(1) if m else None,
           "parties": parties, "amends_points": amends,
           "dates_mentioned": sorted({d for _, d in find_dates("\n".join(lines))}),
           "chars": len(text)}

    b = Builder(doc)
    points = [l for l in lines if POINT_RE.match(l)]
    if len(points) >= 3:                       # документ с нумерацией пунктов
        header, section, cur = [], None, None

        def flush():
            if cur:
                b.add(cur["label"] if cur["label"].startswith("разд") else "п. " + cur["label"], "\n".join(cur["lines"]), cur["section"])

        for l in lines:
            mp, mh = POINT_RE.match(l), HEAD_RE.match(l)
            if mp:
                flush()
                cur = {"label": mp.group(1), "lines": [l], "section": section}
            elif mh and len(l) <= 80 and not l.rstrip().endswith((".", ";", ":")):
                flush()
                cur, section = None, l
            elif cur:
                cur["lines"].append(l)
            elif section is None:
                header.append(l)
            else:
                cur = {"label": "разд. " + section.split(".")[0], "lines": [l], "section": section}
        flush()
        if header:
            b.add("шапка документа", "\n".join(header))
            b.chunks.insert(0, b.chunks.pop())   # шапка идёт первой
    else:                                      # короткие документы без нумерации
        body = "\n".join(lines)
        if len(body) <= 3500:
            b.add("документ целиком", body)
        else:
            b.add_long("текст", lines)
    return doc, b.finish()


# ---------------------------------------------------------------- законы
def is_note(l):
    return len(l) < 600 and not LAW_ART_RE.match(l) and bool(NOTE_RE.match(l) or NOTE2_RE.match(l))


def parse_law(text, title, fname, doc_id, quarantine):
    meta, body = {}, []
    for l in (x.strip() for x in text.splitlines()):
        if l.startswith("Источник:"):
            meta["source"] = l[len("Источник:"):].strip()
        elif l.startswith("URL:"):
            meta["url"] = l[4:].strip()
        elif l.startswith("Дата выгрузки:"):
            ds = find_dates(l)
            meta["export_date"] = ds[0][1] if ds else None
        elif l:
            body.append(l)
    body = strip_injections(body, doc_id, quarantine)

    m = re.match(r"^(.+?)\s*ст\.?\s*(\d+(?:\.\d+)?)", title)
    law_key, art_no = (m.group(1).strip(), m.group(2)) if m else (title, "?")
    law_name = LAW_NAMES.get(law_key, law_key)
    # в НК нумерованные части называются "пункты", в остальных законах - "части"
    part_word = "п." if law_key == "НК" else "ч."

    art_title, edition_notes, blocks, pending, cur, unl = None, [], [], [], None, 0
    heading_is_part, in_notes = False, False
    for l in body:
        if art_title is None:                          # всё до заголовка статьи - справка издателя
            ma = LAW_ART_RE.match(l)
            if ma:
                art_no, art_title = ma.group(1), l
                rest = ma.group(2).strip()
                if len(rest) > 60 and rest.endswith("."):   # сама норма стоит в заголовке (как в МРОТ)
                    heading_is_part, unl = True, 1
                    cur = {"label": None, "idx": 1, "lines": [l], "note": None}
                    blocks.append(cur)
            else:
                edition_notes.append(l)
            continue
        if is_note(l):
            pending.append(l)
            continue
        mp = LAW_PART_RE.match(l)
        if re.match(r"^Примечани\w*[:.]?\s*$", l):      # заголовок раздела примечаний
            in_notes, cur = True, None
            continue
        if re.match(r"^Примечание\.", l):                 # одиночное примечание с текстом
            in_notes = True
            cur = {"label": "прим", "lines": [l], "note": None}
            blocks.append(cur)
        elif mp:
            cur = {"label": ("прим " if in_notes else "") + mp.group(1), "lines": [l], "note": None}
            blocks.append(cur)
        elif cur is not None and (cur["label"] is not None or ITEM_RE.match(l) or l[0].islower()):
            cur["lines"].append(l)                      # продолжение: пункты 1), 2), строки списка
        else:
            if cur is None and len(l) < 90 and not l.endswith((".", ":", ";")):
                edition_notes.append(l)                 # служебная строка вроде ссылки на срок давности
                continue
            unl += 1                                    # новая безномерная часть (как в ТК)
            cur = {"label": None, "idx": unl, "lines": [l], "note": None}
            blocks.append(cur)
        if pending:
            cur["note"] = " ".join(filter(None, [cur.get("note")] + pending))
            pending = []

    note_dates = sorted({d for n in edition_notes + [b_["note"] for b_ in blocks if b_["note"]]
                         for _, d in find_dates(n)})
    doc = {"doc_id": doc_id, "file": fname, "title": title, "kind": "law", "doc_type": "law",
           "ref": "%s, ст. %s" % (law_name, art_no), "status": "действующая редакция",
           "doc_date": None, "valid_from": None, "valid_to": None, "number": None,
           "related_ref": None, "source": meta.get("source"), "url": meta.get("url"),
           "export_date": meta.get("export_date"), "edition_notes": edition_notes,
           "amendment_dates": note_dates, "chars": len(text)}

    b = Builder(doc, item_word="пп." if law_key == "НК" else "п.")
    if art_title and not heading_is_part:
        b.add("ст. %s, заголовок" % art_no, art_title, is_heading=True,
              note=" ".join(edition_notes) or None)
    for blk in blocks:
        if blk["label"] == "прим":
            base = "ст. %s, примечание" % art_no
        elif blk["label"] and blk["label"].startswith("прим "):
            base = "ст. %s, примечание %s" % (art_no, blk["label"][5:])
        elif blk["label"]:
            base = "ст. %s, %s %s" % (art_no, part_word, blk["label"])
        else:
            base = "ст. %s, ч. %d" % (art_no, blk["idx"])
        note = blk["note"]
        if heading_is_part and blk["idx"] == 1 and blk["label"] is None and edition_notes:
            note = " ".join(filter(None, [" ".join(edition_notes), note]))
        b.add_long(base, blk["lines"], note=note)
    return doc, b.finish()


# ---------------------------------------------------------------- запуск
def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("knowledge-base")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("out")
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(src.rglob("*.txt"))
    if not files:
        sys.exit("В папке %s нет .txt файлов" % src)

    docs, all_chunks, quarantine, used, hashes, dups = [], [], [], set(), {}, []
    for f in files:
        h = hashlib.md5(f.read_bytes()).hexdigest()
        if h in hashes:                                 # точная копия уже обработанного файла
            dups.append("%s == %s" % (f.name, hashes[h]))
            continue
        hashes[h] = f.name
        kind, title = classify(f.name)
        doc_id = slug(title)
        base_id, k = doc_id, 1
        while doc_id in used:
            k += 1
            doc_id = "%s-%d" % (base_id, k)
        used.add(doc_id)
        parse = parse_law if kind == "law" else parse_company
        doc, chunks = parse(read(f), title, f.name, doc_id, quarantine)
        doc["n_chunks"] = len(chunks)
        docs.append(doc)
        all_chunks += chunks

    with open(out / "chunks.jsonl", "w", encoding="utf-8") as fh:
        for c in all_chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    (out / "docs.json").write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")

    rep = ["Файлов: %d, карточек: %d" % (len(docs), len(all_chunks)), ""]
    for d in docs:
        rep.append("%-10s %-20s %-23s карточек=%-3d %s" % (
            d["doc_type"], d["status"], "%s..%s" % (d["valid_from"] or "-", d["valid_to"] or "-"),
            d["n_chunks"], d["title"]))
    if dups:
        rep += ["", "Пропущены дубликаты (одинаковое содержимое): %d" % len(dups)] + ["  " + x for x in dups]
    big = [c for c in all_chunks if len(c["text"]) > MAX_CHARS * 1.3]
    rep += ["", "Слишком длинных карточек: %d" % len(big)]
    rep += ["", "ПОДОЗРИТЕЛЬНЫЕ ИНСТРУКЦИИ В ДОКУМЕНТАХ (вырезаны из карточек): %d" % len(quarantine)]
    for q in quarantine:
        rep.append("  [%s] %s" % (q["doc_id"], q["line"]))
    (out / "report.txt").write_text("\n".join(rep), encoding="utf-8")
    (out / "quarantine.json").write_text(json.dumps(quarantine, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
