"""
FAISS / ChromaDB 추상화 래퍼.
add() / search() / save() / load() 네 가지 연산만 외부에 노출.
"""

import os
import pickle
import numpy as np
from src.chunker import Chunk


class VectorStore:
    def __init__(self, backend: str = "faiss", cache_dir: str = ".cache/vector_db", dimension: int = 384):
        self.backend = backend.lower()
        self.cache_dir = cache_dir
        self.dimension = dimension
        os.makedirs(cache_dir, exist_ok=True)

        if self.backend == "faiss":
            self._store = _FaissStore(cache_dir, dimension)
        elif self.backend == "chromadb":
            self._store = _ChromaStore(cache_dir)
        else:
            raise ValueError(f"지원하지 않는 벡터 DB: {backend}. faiss 또는 chromadb를 사용하세요.")

    def add(self, chunks: list, embeddings: np.ndarray) -> None:
        self._store.add(chunks, embeddings)

    def search(self, query_vec: np.ndarray, k: int = 5) -> list:
        """반환: list[tuple[Chunk, float]] (score 내림차순)"""
        return self._store.search(query_vec, k)

    def save(self, name: str) -> None:
        self._store.save(name)

    def load(self, name: str) -> bool:
        return self._store.load(name)

    def count(self) -> int:
        return self._store.count()


# ── FAISS 구현 ────────────────────────────────────────────────────────────────

class _FaissStore:
    def __init__(self, cache_dir: str, dimension: int):
        import faiss
        self._faiss = faiss
        self.cache_dir = cache_dir
        self.dimension = dimension
        self._index = faiss.IndexFlatIP(dimension)  # Inner product (= cosine on L2-normalized vecs)
        self._chunks: list[Chunk] = []

    def add(self, chunks: list, embeddings: np.ndarray) -> None:
        if len(chunks) == 0:
            return
        self._index.add(embeddings)
        self._chunks.extend(chunks)

    def search(self, query_vec: np.ndarray, k: int) -> list:
        if self._index.ntotal == 0:
            return []
        k = min(k, self._index.ntotal)
        q = query_vec.reshape(1, -1).astype(np.float32)
        scores, indices = self._index.search(q, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append((self._chunks[idx], float(score)))
        return results

    def save(self, name: str) -> None:
        import faiss
        index_path = os.path.join(self.cache_dir, f"{name}.index")
        meta_path = os.path.join(self.cache_dir, f"{name}.pkl")
        faiss.write_index(self._index, index_path)
        with open(meta_path, "wb") as f:
            pickle.dump(self._chunks, f)

    def load(self, name: str) -> bool:
        import faiss
        index_path = os.path.join(self.cache_dir, f"{name}.index")
        meta_path = os.path.join(self.cache_dir, f"{name}.pkl")
        if not (os.path.exists(index_path) and os.path.exists(meta_path)):
            return False
        self._index = faiss.read_index(index_path)
        with open(meta_path, "rb") as f:
            self._chunks = pickle.load(f)
        return True

    def count(self) -> int:
        return self._index.ntotal


# ── ChromaDB 구현 ─────────────────────────────────────────────────────────────

class _ChromaStore:
    _COLLECTION = "patent_docs"

    def __init__(self, cache_dir: str):
        import chromadb
        chroma_path = os.path.join(cache_dir, "chroma")
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._col = self._client.get_or_create_collection(
            self._COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, chunks: list, embeddings: np.ndarray) -> None:
        if not chunks:
            return
        # ChromaDB는 str ID를 요구하며 중복 허용 안 함
        ids = [f"{c.uid}" for c in chunks]
        docs = [c.text for c in chunks]
        metas = [
            {"doc_id": c.doc_id, "source": c.source,
             "pub_date": c.pub_date, "title": c.title, "chunk_idx": c.chunk_idx}
            for c in chunks
        ]
        self._col.add(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=docs,
            metadatas=metas,
        )

    def search(self, query_vec: np.ndarray, k: int) -> list:
        n = self._col.count()
        if n == 0:
            return []
        k = min(k, n)
        res = self._col.query(
            query_embeddings=[query_vec.tolist()],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        results = []
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            score = 1.0 - float(dist)  # cosine distance → similarity
            chunk = Chunk(
                text=doc,
                doc_id=meta.get("doc_id", ""),
                source=meta.get("source", ""),
                pub_date=meta.get("pub_date", ""),
                title=meta.get("title", ""),
                chunk_idx=int(meta.get("chunk_idx", 0)),
            )
            results.append((chunk, score))
        return results

    def save(self, name: str) -> None:
        # ChromaDB PersistentClient는 자동 저장됨
        pass

    def load(self, name: str) -> bool:
        # PersistentClient는 자동 로드됨
        return self._col.count() > 0

    def count(self) -> int:
        return self._col.count()
