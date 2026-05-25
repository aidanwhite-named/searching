import time
from dataclasses import dataclass, field
from src.config_manager import ConfigManager
from src.chunker import Chunk, Chunker
from src.embedder import Embedder
from src.vector_store import VectorStore
from src.document_cache import DocumentCache
from src.reranker import Reranker
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ChunkResult:
    chunk: Chunk
    score: float    # Reranked score (0~1)


@dataclass
class RAGClaimResult:
    claim_number: int
    top_chunks: list = field(default_factory=list)  # list[ChunkResult]


class RAGPipeline:
    def __init__(self, config: ConfigManager):
        self._cfg = config
        self._embedder = Embedder(config.get("rag", "embedding_model", default="BAAI/bge-m3"))
        # mode: "memory"(기본, 세션마다 초기화) | "local"(디스크 영구 저장)
        store_mode = config.get("rag", "store_mode", default="memory")
        self._store = VectorStore(
            backend=config.get("rag", "vector_db", default="qdrant"),
            dimension=self._embedder.dimension,
            mode=store_mode,
        )
        self._chunker = Chunker(
            chunk_size=config.get("rag", "chunk_size", default=512),
            chunk_overlap=config.get("rag", "chunk_overlap", default=64),
        )
        self._reranker = Reranker(config.get("rag", "reranker_model", default="BAAI/bge-reranker-v2-m3"))
        self._cache = DocumentCache()

    def build_index(
        self,
        search_results: list,
        cache: DocumentCache | None = None,
        index_name: str = "session",
        force_rebuild: bool = False,
    ) -> int:
        """
        Build local vector database index by chunking search results and storing embeddings.
        """
        cache = cache or self._cache

        # Qdrant client checks persistence and counts automatically
        if not force_rebuild and self._store.load(index_name):
            n = self._store.count()
            logger.info("기존 벡터 인덱스 로드: %d개 청크", n)
            return n

        if force_rebuild:
            self._store.clear()

        logger.info("문서 청킹 시작 (청구항 기반 규칙 적용)...")
        t0 = time.time()
        chunks = self._chunker.chunk_all(search_results, cache)
        if not chunks:
            logger.warning("생성된 청크 없음 — 인덱스가 비어있습니다")
            return 0
        logger.info("청킹 완료: %d개 청크, %.1f초", len(chunks), time.time() - t0)

        logger.info("임베딩 시작: %d개 청크 (BGE-M3 다국어 모델)...", len(chunks))
        texts = [c.text for c in chunks]
        embeddings = self._embedder.embed(texts)

        logger.info("벡터 DB 저장 중 (Qdrant)...")
        t0 = time.time()
        self._store.add(chunks, embeddings)
        logger.info("벡터 인덱스 구축 완료: %d개 청크, %.1f초", self._store.count(), time.time() - t0)
        return len(chunks)

    def search(
        self,
        claim_nodes: dict,
        target_claims: list,
        top_k: int = 10,
    ) -> list:
        """
        Search vector store for chunks matching the claim text, retrieve top 50, rerank to top_k.
        """
        results = []
        for num in target_claims:
            node = claim_nodes.get(num)
            if not node:
                logger.warning("청구항 %d 노드 없음 — 건너뜀", num)
                continue

            logger.info("청구항 %d RAG 검색 중 (벡터 검색 50개 → 리랭킹 top_%d)...", num, top_k)
            t0 = time.time()

            # Dense vector query representation
            query_vec = self._embedder.embed_one(node.text)

            # Retrieve top 50 candidates from Qdrant
            hits = self._store.search(query_vec, k=50)

            # Perform semantic reranking using bge-reranker-v2-m3 to get top_k (default 10)
            reranked_hits = self._reranker.rerank(node.text, hits, top_k=top_k)

            top_chunks = [ChunkResult(chunk=chunk, score=score) for chunk, score in reranked_hits]
            results.append(RAGClaimResult(claim_number=num, top_chunks=top_chunks))

            elapsed = time.time() - t0
            if top_chunks:
                logger.info(
                    "청구항 %d 검색 완료: %.1f초, top 점수=%.3f, 문서=%s",
                    num, elapsed, top_chunks[0].score,
                    top_chunks[0].chunk.doc_id[:30],
                )
            else:
                logger.info("청구항 %d 검색 완료: %.1f초, 결과 없음", num, elapsed)

        return results

    def summary(self, rag_results: list) -> str:
        """Generate a summary of the RAG search results for CLI feedback."""
        lines = ["\n=== Reranked RAG Search Results ==="]
        for cr in rag_results:
            lines.append(f"\n  Claim {cr.claim_number} — top {len(cr.top_chunks)} chunks")
            for i, r in enumerate(cr.top_chunks, 1):
                c = r.chunk
                lines.append(f"    [{i}] score={r.score:.3f} | {c.source} | {c.pub_date} | type={c.chunk_type}")
                lines.append(f"        Title: {c.title[:50]}")
                lines.append(f"        Text: {c.text[:120].replace(chr(10), ' ')}...")
        return "\n".join(lines)
