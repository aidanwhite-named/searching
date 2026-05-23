from dataclasses import dataclass, field
from src.config_manager import ConfigManager
from src.chunker import Chunk, Chunker
from src.embedder import Embedder
from src.vector_store import VectorStore
from src.document_cache import DocumentCache


@dataclass
class ChunkResult:
    chunk: Chunk
    score: float    # 코사인 유사도 (0~1)


@dataclass
class RAGClaimResult:
    claim_number: int
    top_chunks: list = field(default_factory=list)  # list[ChunkResult]


class RAGPipeline:
    def __init__(self, config: ConfigManager):
        self._cfg = config
        self._embedder = Embedder(config.get("rag", "embedding_model"))
        self._store = VectorStore(
            backend=config.get("rag", "vector_db"),
            dimension=self._embedder.dimension,
        )
        self._chunker = Chunker(
            chunk_size=config.get("rag", "chunk_size"),
            chunk_overlap=config.get("rag", "chunk_overlap"),
        )
        self._cache = DocumentCache()

    def build_index(
        self,
        search_results: list,
        cache: DocumentCache | None = None,
        index_name: str = "session",
        force_rebuild: bool = False,
    ) -> int:
        """
        문서 로드 → 청킹 → 임베딩 → 벡터 DB 인덱싱.
        반환: 인덱싱된 청크 수.
        """
        cache = cache or self._cache

        # 기존 인덱스 로드 시도
        if not force_rebuild and self._store.load(index_name):
            n = self._store.count()
            print(f"[rag] 기존 인덱스 로드: {n}개 청크 ({index_name})")
            return n

        print("[rag] 문서 청킹 중...")
        chunks = self._chunker.chunk_all(search_results, cache)
        if not chunks:
            print("[rag] 청킹 결과 없음 — 인덱스 비어 있음")
            return 0

        print(f"[rag] {len(chunks)}개 청크 임베딩 중...")
        texts = [c.text for c in chunks]
        embeddings = self._embedder.embed(texts)

        print(f"[rag] 벡터 DB에 추가 중 ({self._cfg.get('rag', 'vector_db')})...")
        self._store.add(chunks, embeddings)
        self._store.save(index_name)
        print(f"[rag] 인덱스 구축 완료: {len(chunks)}개 청크")
        return len(chunks)

    def search(
        self,
        claim_nodes: dict,
        target_claims: list,
        top_k: int = 5,
    ) -> list:
        """
        청구항 텍스트를 임베딩하여 벡터 DB에서 유사 청크 검색.
        반환: list[RAGClaimResult]
        """
        results = []
        for num in target_claims:
            node = claim_nodes.get(num)
            if not node:
                continue

            query_vec = self._embedder.embed_one(node.text)
            hits = self._store.search(query_vec, k=top_k)
            top_chunks = [ChunkResult(chunk=chunk, score=score) for chunk, score in hits]
            results.append(RAGClaimResult(claim_number=num, top_chunks=top_chunks))

        return results

    def summary(self, rag_results: list) -> str:
        lines = ["\n=== 2차 RAG 검색 결과 ==="]
        for cr in rag_results:
            lines.append(f"\n  청구항 {cr.claim_number} — 상위 {len(cr.top_chunks)}개 청크")
            for i, r in enumerate(cr.top_chunks, 1):
                c = r.chunk
                lines.append(f"    [{i}] score={r.score:.3f} | {c.source} | {c.pub_date}")
                lines.append(f"        제목: {c.title[:50]}")
                lines.append(f"        본문: {c.text[:120].replace(chr(10), ' ')}...")
        return "\n".join(lines)
