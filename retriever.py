"""Слой 5 (Retriever Engine): 3-канальный гибридный поиск, детекция контрагентов без кавычек и приоритетные Siblings."""

from __future__ import annotations

import re
import httpx
import numpy as np
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import config
import llm_client
import models


class HybridLegalIndex:
    def __init__(
        self,
        documents: list[models.LegalDocument],
        chunks: list[models.LegalChunk],
        client: httpx.Client,
    ) -> None:
        self.documents = documents
        self.doc_by_id = {d.doc_id: d for d in documents}
        self.chunks = chunks

        self.our_company = models.normalize_entity_name("Меридиан")
        self.entity_to_docs: dict[str, list[str]] = {}
        self.code_to_docs: dict[str, list[str]] = {}
        self.article_to_docs: dict[str, list[str]] = {}

        for doc in documents:
            for ent in doc.entities:
                self.entity_to_docs.setdefault(ent, []).append(doc.doc_id)
            for code in doc.codes:
                self.code_to_docs.setdefault(code, []).append(doc.doc_id)
            for m in config.ARTICLE_REF_RE.finditer(models.normalize_yo(doc.title.lower() + " " + doc.filename.lower())):
                self.article_to_docs.setdefault(m.group(1), []).append(doc.doc_id)

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

        self.chunk_embeddings = llm_client.fetch_embeddings_batched(client, chunk_texts, batch_size=32)

    def detect_query_counterparties(self, search_query: str) -> tuple[set[str], set[str]]:
        """Распознаёт контрагентов в вопросе как в кавычках, так и БЕЗ кавычек."""
        q_entities, q_codes = models.extract_entities_and_codes(search_query)
        known_counterparties = set(self.entity_to_docs.keys()) - {self.our_company}
        matched_cp = q_entities & known_counterparties

        # Если пользователь не поставил кавычки, ищем известных контрагентов по стеммам слов запроса
        if not matched_cp:
            q_stemmed_str = models.normalize_entity_name(search_query)
            # Сортируем по убыванию длины, чтобы "альфа-трейдинг" проверялся раньше "альфа-трейд"
            for cp in sorted(known_counterparties, key=len, reverse=True):
                pattern = r"(?<![а-яa-z0-9-])" + re.escape(cp) + r"(?![а-яa-z0-9-])"
                if re.search(pattern, q_stemmed_str):
                    matched_cp.add(cp)
                    break

        return matched_cp, q_codes

    def retrieve_and_assemble_context(
        self,
        client: httpx.Client,
        search_query: str,
        query_embedding: np.ndarray | None,
    ) -> tuple[str, list[dict]]:
        n_chunks = len(self.chunks)
        rrf_scores = np.zeros(n_chunks, dtype=np.float64)
        rrf_k = 35.0

        # 1. BM25
        bm25_tokens = models.tokenize_for_bm25(search_query)
        if bm25_tokens:
            bm25_scores = self.bm25.get_scores(bm25_tokens)
            bm25_order = np.argsort(bm25_scores)[::-1]
            for rank, idx in enumerate(bm25_order[: config.RETRIEVAL_CANDIDATES]):
                if bm25_scores[idx] > 0:
                    rrf_scores[idx] += 1.3 / (rrf_k + rank + 1)

        # 2. Char-WB TF-IDF
        q_tfidf = self.tfidf_vectorizer.transform([models.normalize_yo(search_query.lower())])
        tfidf_scores = cosine_similarity(q_tfidf, self.tfidf_matrix).ravel()
        tfidf_order = np.argsort(tfidf_scores)[::-1]
        for rank, idx in enumerate(tfidf_order[: config.RETRIEVAL_CANDIDATES]):
            if tfidf_scores[idx] > 0:
                rrf_scores[idx] += 1.0 / (rrf_k + rank + 1)

        # 3. Dense Embeddings (bge-m3 / gemini-embedding-001)
        if self.chunk_embeddings is not None and query_embedding is not None:
            dense_scores = np.dot(self.chunk_embeddings, query_embedding)
            dense_order = np.argsort(dense_scores)[::-1]
            for rank, idx in enumerate(dense_order[: config.RETRIEVAL_CANDIDATES]):
                rrf_scores[idx] += 1.5 / (rrf_k + rank + 1)

        # 4. Бустинг по контрагентам и номерам договоров
        q_counterparties, q_codes = self.detect_query_counterparties(search_query)
        q_norm = models.normalize_yo(search_query.lower())

        for idx, chunk in enumerate(self.chunks):
            doc = self.doc_by_id[chunk.doc_id]
            doc_counterparties = {e for e in doc.entities if e != self.our_company}

            if q_counterparties and doc.is_contract:
                if doc_counterparties & q_counterparties:
                    rrf_scores[idx] += 0.45
                elif doc_counterparties and not (doc_counterparties & q_counterparties):
                    rrf_scores[idx] -= 0.30

            for code in doc.codes:
                if code in q_codes or (len(code) >= 3 and code in q_norm):
                    rrf_scores[idx] += 0.45

        top_chunk_indices = [int(i) for i in np.argsort(rrf_scores)[::-1][: config.RETRIEVAL_CANDIDATES]]

        # 5. Нейросетевой реранкинг
        candidate_texts = [self.chunks[i].text_with_header for i in top_chunk_indices]
        reranked_local = llm_client.call_reranker(
            client,
            search_query,
            candidate_texts,
            top_n=min(len(top_chunk_indices), config.RERANK_TOP_CHUNKS),
        )
        if reranked_local:
            winning_chunk_indices = [top_chunk_indices[i] for i in reranked_local]
        else:
            winning_chunk_indices = top_chunk_indices[: config.RERANK_TOP_CHUNKS]

        doc_to_best_chunks: dict[str, list[int]] = {}
        initial_doc_ids: list[str] = []
        for c_idx in winning_chunk_indices:
            d_id = self.chunks[c_idx].doc_id
            doc = self.doc_by_id[d_id]
            doc_counterparties = {e for e in doc.entities if e != self.our_company}

            if q_counterparties and doc.is_contract and doc_counterparties and not (doc_counterparties & q_counterparties):
                continue

            if d_id not in doc_to_best_chunks:
                doc_to_best_chunks[d_id] = []
                initial_doc_ids.append(d_id)
            doc_to_best_chunks[d_id].append(c_idx)

        # 6. Приоритетный Sibling Expansion: вставляем парные редакции / ДС / связанные статьи
        # сразу после Топ-2 документов, чтобы они никогда не обрезались лимитом длины!
        priority_siblings: list[str] = []
        for d_id in initial_doc_ids[:2]:
            doc = self.doc_by_id[d_id]
            raw_siblings: list[str] = []
            for code in doc.codes:
                raw_siblings.extend(self.code_to_docs.get(code, []))
            if not doc.is_contract:
                for ent in doc.entities:
                    raw_siblings.extend(self.entity_to_docs.get(ent, []))
            else:
                for ent in doc.entities:
                    if ent != self.our_company:
                        raw_siblings.extend(self.entity_to_docs.get(ent, []))

            for m in config.ARTICLE_REF_RE.finditer(models.normalize_yo(doc.raw_text[:2500].lower())):
                art_num = m.group(1)
                # Не притягиваем "Статью 1" (МРОТ) по случайным упоминаниям "пункта 1 статьи 1..."
                if art_num != "1":
                    raw_siblings.extend(self.article_to_docs.get(art_num, []))

            for sib_id in raw_siblings:
                sib_doc = self.doc_by_id[sib_id]
                if not doc.is_contract and sib_doc.is_contract:
                    continue
                if sib_id != d_id and sib_id not in priority_siblings:
                    priority_siblings.append(sib_id)

        ordered_doc_ids: list[str] = []
        for d_id in initial_doc_ids[:2] + priority_siblings[:2] + initial_doc_ids[2:]:
            if d_id not in ordered_doc_ids:
                ordered_doc_ids.append(d_id)
            if len(ordered_doc_ids) >= config.MAX_CONTEXT_DOCS + 1:
                break

        # 7. Сборка контекста (для длинных законов выбираем самые релевантные чанки по rrf_scores!)
        context_blocks: list[str] = []
        sources_meta: list[dict] = []
        total_chars = 0

        for idx, d_id in enumerate(ordered_doc_ids, 1):
            doc = self.doc_by_id[d_id]
            if len(doc.raw_text) <= config.SHORT_DOC_THRESHOLD:
                body_text = doc.raw_text
            else:
                # Выбираем лучшие чанки этого документа по rrf_scores для текущего запроса
                best_for_doc = doc_to_best_chunks.get(d_id, [])
                if not best_for_doc:
                    best_for_doc = sorted(doc.chunk_ids, key=lambda cid: float(rrf_scores[cid]), reverse=True)[:4]
                chosen_c_ids = sorted(set(best_for_doc[:5]))
                parts = [self.chunks[cid].raw_chunk_text for cid in chosen_c_ids]
                body_text = "\n...\n".join(parts)

            block = f"=== ДОКУМЕНТ #{idx}: {doc.header_summary} ===\n{body_text}"
            if total_chars + len(block) > config.MAX_TOTAL_CONTEXT_CHARS and idx > 3:
                break
            context_blocks.append(block)
            total_chars += len(block)

            sources_meta.append(
                {
                    "doc_id": doc.doc_id,
                    "filename": doc.filename,
                    "title": doc.title,
                    "is_expired": doc.is_expired,
                    "snippet": body_text[:800],
                    "full_text": doc.raw_text,
                }
            )

        return "\n\n".join(context_blocks), sources_meta