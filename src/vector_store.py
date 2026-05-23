import os
import uuid
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, MatchAny
from src.chunker import Chunk

class VectorStore:
    def __init__(self, backend: str = "qdrant", cache_dir: str = ".cache/qdrant_db", dimension: int = 1024):
        self.collection_name = "patent_chunks"
        self.dimension = dimension
        self.cache_dir = cache_dir
        
        # Determine client initialization based on config or env
        # Let's support an optional QDRANT_URL environment variable
        qdrant_url = os.getenv("QDRANT_URL", "")
        if qdrant_url:
            print(f"[vector_store] Connecting to Qdrant server at: {qdrant_url}")
            self.client = QdrantClient(url=qdrant_url)
        else:
            local_path = os.path.join(cache_dir, "db")
            os.makedirs(local_path, exist_ok=True)
            print(f"[vector_store] Initializing embedded Qdrant local storage: {local_path}")
            self.client = QdrantClient(path=local_path)
            
        self._ensure_collection()

    def _ensure_collection(self):
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                print(f"[vector_store] Creating collection '{self.collection_name}' with dimension {self.dimension}")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.dimension, distance=Distance.COSINE)
                )
        except Exception as e:
            print(f"[vector_store] Error ensuring collection exists: {e}")

    def add(self, chunks: list, embeddings: np.ndarray) -> None:
        if len(chunks) == 0:
            return
        
        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, embeddings)):
            # Generate deterministic UUID based on chunk UID to prevent duplicates
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.uid))
            payload = {
                "text": chunk.text,
                "doc_id": chunk.doc_id,
                "source": chunk.source,
                "pub_date": chunk.pub_date,
                "title": chunk.title,
                "chunk_idx": chunk.chunk_idx,
                "chunk_type": chunk.chunk_type,
                "claim_number": chunk.claim_number,
                "sub_index": chunk.sub_index,
                "language": chunk.language,
                "ipc_codes": chunk.ipc_codes or [],
                "cpc_codes": chunk.cpc_codes or []
            }
            points.append(PointStruct(id=point_id, vector=vector.tolist(), payload=payload))
            
        try:
            self.client.upsert(collection_name=self.collection_name, points=points)
            print(f"[vector_store] Successfully indexed {len(chunks)} chunks into Qdrant.")
        except Exception as e:
            print(f"[vector_store] Error upserting points to Qdrant: {e}")

    def search(self, query_vec: np.ndarray, k: int = 5, filter_dict: dict = None) -> list:
        """
        Search for nearest vectors.
        Returns: list[tuple[Chunk, float]]
        """
        qdrant_filter = None
        if filter_dict:
            conditions = []
            for field_name, val in filter_dict.items():
                if isinstance(val, list):
                    conditions.append(FieldCondition(key=field_name, match=MatchAny(any=val)))
                else:
                    conditions.append(FieldCondition(key=field_name, match=MatchValue(value=val)))
            qdrant_filter = Filter(must=conditions)
            
        try:
            res = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vec.tolist(),
                query_filter=qdrant_filter,
                limit=k
            )
            
            results = []
            for hit in res:
                p = hit.payload
                chunk = Chunk(
                    text=p.get("text", ""),
                    doc_id=p.get("doc_id", ""),
                    source=p.get("source", ""),
                    pub_date=p.get("pub_date", ""),
                    title=p.get("title", ""),
                    chunk_idx=p.get("chunk_idx", 0),
                    chunk_type=p.get("chunk_type", "summary"),
                    claim_number=p.get("claim_number"),
                    sub_index=p.get("sub_index"),
                    language=p.get("language", "en"),
                    ipc_codes=p.get("ipc_codes", []),
                    cpc_codes=p.get("cpc_codes", [])
                )
                results.append((chunk, hit.score))
            return results
        except Exception as e:
            print(f"[vector_store] Qdrant search failed: {e}")
            return []

    def save(self, name: str) -> None:
        # Embedded Qdrant client handles persistence automatically
        pass

    def load(self, name: str) -> bool:
        # Returns True if collection exists and has points
        try:
            count = self.count()
            return count > 0
        except:
            return False

    def count(self) -> int:
        try:
            res = self.client.get_collection(collection_name=self.collection_name)
            return res.points_count or 0
        except:
            return 0
