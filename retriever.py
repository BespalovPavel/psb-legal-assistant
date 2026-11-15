from __future__ import annotations

import re
from dataclasses import dataclass, field
import httpx
import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

import config
import llm_client
import models
from database_models import Chunk, Document

RETRIEVAL_CANDIDATES = 28
RERANK_TOP_CHUNKS = 10
MAX_CONTEXT_DOCS = 5
SHORT_DOC_THRESHOLD = 4800
MAX_TOTAL_CONTEXT_CHARS = 22000


def format_date_dmy(d_val: str | None) -> str:
    if not d_val:
        return ""
    d_val = d_val.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", d_val)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return d_val


@dataclass
class IndexedDoc:
    doc_id: str
    file: str
    title: str
    raw_text: str
    header_summary: str
    is_contract: bool = False
    is_addendum: bool = False
    entities: set[str] = field(default_factory=set)
    codes: set[str] = field(default_factory=set)
    chunk_indices: list[int] = field(default_factory=list)


@dataclass
class IndexedChunk:
    chunk_idx: int
    chunk_id: str
    doc_id: str
    path: str
    text_with_header: str
    raw_chunk_text: str


class HybridLegalRetriever:
    def __init__(
        self,
        docs: list[IndexedDoc],
        chunks: list[IndexedChunk],
    ) -> None:
        self.docs = docs
        self.doc_by_id = {d.doc_id: d for d in docs}
        self.chunks = chunks

        self.our_company = models.normalize_entity_name("Меридиан")
        self.entity_to_docs: dict[str, list[str]] = {}
        self.code_to_docs: dict[str, list[str]] = {}
        self.article_to_docs: dict[str, list[str]] = {}

        for doc in docs:
            for ent in doc.entities:
                self.entity_to_docs.setdefault(ent, []).append(doc.doc_id)
            for code in doc.codes:
                self.code_to_docs.setdefault(code, []).append(doc.doc_id)
            for m in config.ARTICLE_REF_RE.finditer(
                models.normalize_yo(doc.title.lower() + " " + doc.file.lower())
            ):
                self.article_to_docs.setdefault(m.group(1), []).append(doc.doc_id)

        if chunks:
            chunk_texts = [c.text_with_header for c in chunks]
            self.bm25 = BM25Okapi([models.tokenize_for_bm25(t) for t in chunk_texts])
            self.tfidf_vectorizer = TfidfVectorizer(
                analyzer="char_wb",
                ngram_range=(3, 5),
                min_df=1,
                sublinear_tf=True,
            )
            self.tfidf_matrix = self.tfidf_vectorizer.fit_transform(
                [models.normalize_yo(t.lower()) for t in chunk_texts]
            )
        else:
            self.bm25 = None
            self.tfidf_vectorizer = None
            self.tfidf_matrix = None

        self.chunk_embeddings: np.ndarray | None = None

    @classmethod
    def from_db(cls, db: Session) -> HybridLegalRetriever:
        db_docs = db.query(Document).order_by(Document.doc_id.asc()).all()
        db_chunks = (
            db.query(Chunk)
            .order_by(Chunk.doc_id.asc(), Chunk.ord.asc())
            .all()
        )

        chunks_by_doc: dict[str, list[Chunk]] = {}
        for ch in db_chunks:
            chunks_by_doc.setdefault(ch.doc_id, []).append(ch)

        indexed_docs: list[IndexedDoc] = []
        indexed_chunks: list[IndexedChunk] = []
        chunk_counter = 0

        for doc in db_docs:
            if doc.valid_to:
                status_tag = f"УТРАТИЛА СИЛУ с {format_date_dmy(doc.valid_to)}"
            elif doc.valid_from:
                status_tag = (
                    f"ДЕЙСТВУЮЩАЯ (редакция от {format_date_dmy(doc.valid_from)}, "
                    "если не изменена более поздним актом/ДС)"
                )
            else:
                status_tag = doc.status or "ДЕЙСТВУЮЩАЯ"

            header_summary = f"[Файл: {doc.file} | Документ: {doc.title} | Статус: {status_tag}]"

            is_contract = (doc.doc_type == "contract")
            is_addendum = (doc.doc_type == "addendum")

            entities: set[str] = set()
            if isinstance(doc.parties, list):
                for p in doc.parties:
                    canon = models.normalize_entity_name(str(p))
                    if len(canon) >= 2:
                        entities.add(canon)

            codes: set[str] = set()
            if doc.number and str(doc.number).strip():
                codes.add(str(doc.number).strip())
            if doc.related_ref and str(doc.related_ref).strip():
                codes.add(str(doc.related_ref).strip())

            doc_chunks = chunks_by_doc.get(doc.doc_id, [])
            doc_chunk_indices: list[int] = []

            if not doc_chunks:
                raw_text = doc.raw_text or ""
                ic = IndexedChunk(
                    chunk_idx=chunk_counter,
                    chunk_id=f"{doc.doc_id}:whole",
                    doc_id=doc.doc_id,
                    path="документ целиком",
                    text_with_header=f"{header_summary}\n{raw_text}",
                    raw_chunk_text=raw_text,
                )
                indexed_chunks.append(ic)
                doc_chunk_indices.append(chunk_counter)
                chunk_counter += 1
            else:
                for ch in doc_chunks:
                    text_body = ch.text or ""
                    ic = IndexedChunk(
                        chunk_idx=chunk_counter,
                        chunk_id=ch.chunk_id,
                        doc_id=doc.doc_id,
                        path=ch.path or "документ целиком",
                        text_with_header=f"{header_summary}\n{text_body}",
                        raw_chunk_text=text_body,
                    )
                    indexed_chunks.append(ic)
                    doc_chunk_indices.append(chunk_counter)
                    chunk_counter += 1

            indexed_doc = IndexedDoc(
                doc_id=doc.doc_id,
                file=doc.file,
                title=doc.title,
                raw_text=doc.raw_text or "",
                header_summary=header_summary,
                is_contract=is_contract,
                is_addendum=is_addendum,
                entities=entities,
                codes=codes,
                chunk_indices=doc_chunk_indices,
            )
            indexed_docs.append(indexed_doc)

        return cls(indexed_docs, indexed_chunks)

    def detect_query_counterparties(
        self, search_query: str
    ) -> tuple[set[str], set[str]]:
        q_entities, q_codes = models.extract_entities_and_codes(search_query)
        known_counterparties = set(self.entity_to_docs.keys()) - {self.our_company}
        matched_cp = q_entities & known_counterparties

        if not matched_cp:
            q_stemmed_str = models.normalize_entity_name(search_query)
            for cp in sorted(known_counterparties, key=len, reverse=True):
                pattern = r"(?<![а-яa-z0-9-])" + re.escape(cp) + r"(?![а-яa-z0-9-])"
                if re.search(pattern, q_stemmed_str):
                    matched_cp.add(cp)
                    break

        return matched_cp, q_codes

    def retrieve(
        self, client: httpx.Client, search_query: str
    ) -> tuple[str, list[dict]]:
        if not self.chunks:
            return "", []

        n_chunks = len(self.chunks)
        rrf_scores = np.zeros(n_chunks, dtype=np.float64)
        rrf_k = 35.0

        # Embeddings: lazy loading / computation
        if self.chunk_embeddings is None:
            chunk_texts = [c.text_with_header for c in self.chunks]
            self.chunk_embeddings = llm_client.fetch_embeddings_batched(
                client, chunk_texts, batch_size=32
            )

        query_embedding: np.ndarray | None = None
        if self.chunk_embeddings is not None:
            q_embs = llm_client.fetch_embeddings_batched(
                client, [search_query], batch_size=1
            )
            if q_embs is not None and len(q_embs) > 0:
                query_embedding = q_embs[0]

        # 1. BM25
        if self.bm25 is not None:
            bm25_tokens = models.tokenize_for_bm25(search_query)
            if bm25_tokens:
                bm25_scores = self.bm25.get_scores(bm25_tokens)
                bm25_order = np.argsort(bm25_scores)[::-1]
                for rank, idx in enumerate(bm25_order[:RETRIEVAL_CANDIDATES]):
                    if bm25_scores[idx] > 0:
                        rrf_scores[idx] += 1.3 / (rrf_k + rank + 1)

        # 2. Char-WB TF-IDF
        if self.tfidf_vectorizer is not None and self.tfidf_matrix is not None:
            q_tfidf = self.tfidf_vectorizer.transform(
                [models.normalize_yo(search_query.lower())]
            )
            tfidf_scores = cosine_similarity(q_tfidf, self.tfidf_matrix).ravel()
            tfidf_order = np.argsort(tfidf_scores)[::-1]
            for rank, idx in enumerate(tfidf_order[:RETRIEVAL_CANDIDATES]):
                if tfidf_scores[idx] > 0:
                    rrf_scores[idx] += 1.0 / (rrf_k + rank + 1)

        # 3. Dense Embeddings
        if self.chunk_embeddings is not None and query_embedding is not None:
            dense_scores = np.dot(self.chunk_embeddings, query_embedding)
            dense_order = np.argsort(dense_scores)[::-1]
            for rank, idx in enumerate(dense_order[:RETRIEVAL_CANDIDATES]):
                rrf_scores[idx] += 1.5 / (rrf_k + rank + 1)

        # 4. Бустинг по контрагентам и номерам договоров
        q_counterparties, q_codes = self.detect_query_counterparties(search_query)
        q_norm = models.normalize_yo(search_query.lower())

        for idx, chunk in enumerate(self.chunks):
            doc = self.doc_by_id[chunk.doc_id]
            doc_counterparties = {e for e in doc.entities if e != self.our_company}

            if q_counterparties and (doc.is_contract or doc.is_addendum):
                if doc_counterparties & q_counterparties:
                    rrf_scores[idx] += 0.45
                elif doc_counterparties and not (doc_counterparties & q_counterparties):
                    rrf_scores[idx] -= 0.30

            for code in doc.codes:
                if code in q_codes or (len(code) >= 3 and code in q_norm):
                    rrf_scores[idx] += 0.45

        top_chunk_indices = [
            int(i)
            for i in np.argsort(rrf_scores)[::-1][:RETRIEVAL_CANDIDATES]
        ]

        # 5. Нейросетевой реранкинг (техническая защита: топ 22, обрезка 2400)
        rerank_candidates = top_chunk_indices[:22]
        candidate_texts = [
            self.chunks[i].text_with_header[:2400] for i in rerank_candidates
        ]
        reranked_local = llm_client.call_reranker(
            client,
            search_query,
            candidate_texts,
            top_n=min(len(rerank_candidates), RERANK_TOP_CHUNKS),
        )
        if reranked_local:
            winning_chunk_indices = [rerank_candidates[i] for i in reranked_local]
        else:
            winning_chunk_indices = top_chunk_indices[:RERANK_TOP_CHUNKS]

        doc_to_best_chunks: dict[str, list[int]] = {}
        initial_doc_ids: list[str] = []
        for c_idx in winning_chunk_indices:
            d_id = self.chunks[c_idx].doc_id
            doc = self.doc_by_id[d_id]
            doc_counterparties = {e for e in doc.entities if e != self.our_company}

            if (
                q_counterparties
                and (doc.is_contract or doc.is_addendum)
                and doc_counterparties
                and not (doc_counterparties & q_counterparties)
            ):
                continue

            if d_id not in doc_to_best_chunks:
                doc_to_best_chunks[d_id] = []
                initial_doc_ids.append(d_id)
            doc_to_best_chunks[d_id].append(c_idx)

        # 6. Приоритетный Sibling Expansion
        priority_siblings: list[str] = []
        for d_id in initial_doc_ids[:2]:
            doc = self.doc_by_id[d_id]
            raw_siblings: list[str] = []
            for code in doc.codes:
                raw_siblings.extend(self.code_to_docs.get(code, []))
            if not (doc.is_contract or doc.is_addendum):
                for ent in doc.entities:
                    raw_siblings.extend(self.entity_to_docs.get(ent, []))
            else:
                for ent in doc.entities:
                    if ent != self.our_company:
                        raw_siblings.extend(self.entity_to_docs.get(ent, []))

            for m in config.ARTICLE_REF_RE.finditer(
                models.normalize_yo(doc.raw_text[:2500].lower())
            ):
                art_num = m.group(1)
                if art_num != "1":
                    raw_siblings.extend(self.article_to_docs.get(art_num, []))

            for sib_id in raw_siblings:
                sib_doc = self.doc_by_id[sib_id]
                if not (doc.is_contract or doc.is_addendum) and (
                    sib_doc.is_contract or sib_doc.is_addendum
                ):
                    continue
                if sib_id != d_id and sib_id not in priority_siblings:
                    priority_siblings.append(sib_id)

        ordered_doc_ids: list[str] = []
        for d_id in (
            initial_doc_ids[:2] + priority_siblings[:2] + initial_doc_ids[2:]
        ):
            if d_id not in ordered_doc_ids:
                ordered_doc_ids.append(d_id)
            if len(ordered_doc_ids) >= MAX_CONTEXT_DOCS + 1:
                break

        # 7. Сборка контекста
        context_blocks: list[str] = []
        sources_meta: list[dict] = []
        total_chars = 0

        for idx, d_id in enumerate(ordered_doc_ids, 1):
            doc = self.doc_by_id[d_id]
            best_for_doc = doc_to_best_chunks.get(d_id, [])
            if not best_for_doc:
                best_for_doc = sorted(
                    doc.chunk_indices,
                    key=lambda cid: float(rrf_scores[cid]),
                    reverse=True,
                )[:4]

            first_c_idx = (
                best_for_doc[0]
                if best_for_doc
                else (doc.chunk_indices[0] if doc.chunk_indices else None)
            )
            first_chunk = (
                self.chunks[first_c_idx] if first_c_idx is not None else None
            )

            if len(doc.raw_text) <= SHORT_DOC_THRESHOLD:
                body_text = doc.raw_text
            else:
                chosen_c_ids = sorted(
                    best_for_doc[:4],
                    key=lambda cid: float(rrf_scores[cid]),
                    reverse=True,
                )
                parts = [self.chunks[cid].raw_chunk_text for cid in chosen_c_ids]
                body_text = "\n...\n".join(parts)

            block = f"=== ДОКУМЕНТ #{idx}: {doc.header_summary} ===\n{body_text}"
            if total_chars + len(block) > MAX_TOTAL_CONTEXT_CHARS and idx > 3:
                break
            context_blocks.append(block)
            total_chars += len(block)

            sources_meta.append(
                {
                    "doc_id": doc.doc_id,
                    "chunk_id": (
                        first_chunk.chunk_id
                        if first_chunk
                        else f"{doc.doc_id}:whole"
                    ),
                    "filename": doc.file,
                    "title": doc.title,
                    "path": (
                        first_chunk.path if first_chunk else "документ целиком"
                    ),
                    "snippet": body_text[:800],
                }
            )

        return "\n\n".join(context_blocks), sources_meta
