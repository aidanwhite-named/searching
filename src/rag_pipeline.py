from dataclasses import dataclass, field
from src.config_manager import ConfigManager
from src.chunker import Chunk, Chunker
from src.embedder import Embedder
from src.vector_store import VectorStore
from src.document_cache import DocumentCache
from src.reranker import Reranker


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
        self._store = VectorStore(
            backend=config.get("rag", "vector_db", default="qdrant"),
            dimension=self._embedder.dimension,
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
            print(f"[rag] Loaded existing vector index: {n} chunks")
            return n

        print("[rag] Chunking documents using claim-based rules...")
        chunks = self._chunker.chunk_all(search_results, cache)
        if not chunks:
            print("[rag] No chunks produced — index is empty")
            return 0

        print(f"[rag] Embedding {len(chunks)} chunks using multilingual BGE-M3 model...")
        texts = [c.text for c in chunks]
        embeddings = self._embedder.embed(texts)

        print(f"[rag] Storing embedded chunks in Qdrant collection...")
        self._store.add(chunks, embeddings)
        print(f"[rag] Vector DB index constructed: {self._store.count()} chunks in total")
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
                continue

            # Dense vector query representation
            query_vec = self._embedder.embed_one(node.text)
            
            # Retrieve top 50 candidates from Qdrant
            hits = self._store.search(query_vec, k=50)
            
            # Perform semantic reranking using bge-reranker-v2-m3 to get top_k (default 10)
            reranked_hits = self._reranker.rerank(node.text, hits, top_k=top_k)
            
            top_chunks = [ChunkResult(chunk=chunk, score=score) for chunk, score in reranked_hits]
            results.append(RAGClaimResult(claim_number=num, top_chunks=top_chunks))

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
