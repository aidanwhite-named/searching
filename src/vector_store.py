import os
import uuid
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, MatchAny,
)
from src.chunker import Chunk


class VectorStore:
    """
    Qdrant 벡터 스토어 래퍼.

    mode="memory"  → QdrantClient(":memory:")  세션마다 초기화, 영구 저장 없음
    mode="local"   → QdrantClient(path=...)    디스크에 영구 저장
    mode="remote"  → QdrantClient(url=...)     원격 Qdrant 서버
    """

    def __init__(
        self,
        backend: str = "qdrant",
        cache_dir: str = ".cache/qdrant_db",
        dimension: int = 1024,
        mode: str = "memory",          # "memory" | "local" | "remote"
    ):
        self.collection_name = "patent_chunks"
        self.dimension = dimension
        self.mode = mode

        qdrant_url = os.getenv("QDRANT_URL", "")

        if qdrant_url:
            # 환경변수로 원격 서버 지정
            print(f"[vector_store] 원격 Qdrant 서버 연결: {qdrant_url}")
            self.client = QdrantClient(url=qdrant_url)
            self.mode = "remote"

        elif mode == "memory":
            # ── 인메모리: 세션마다 깔끔하게 초기화 ──────────────────────────
            print("[vector_store] 인메모리 Qdrant 초기화 (세션 종료 시 자동 삭제)")
            self.client = QdrantClient(":memory:")

        else:
            # ── 로컬 디스크 영구 저장 ────────────────────────────────────────
            local_path = os.path.join(cache_dir, "db")
            os.makedirs(local_path, exist_ok=True)
            print(f"[vector_store] 로컬 Qdrant 저장소: {local_path}")
            self.client = QdrantClient(path=local_path)

        self._ensure_collection()

    # ── 컬렉션 초기화 ─────────────────────────────────────────────────────────

    def _ensure_collection(self):
        """컬렉션 없으면 생성. 코사인 유사도를 Qdrant 내부 엔진에 위임."""
        try:
            existing = {c.name for c in self.client.get_collections().collections}
            if self.collection_name not in existing:
                print(
                    f"[vector_store] 컬렉션 '{self.collection_name}' 생성 "
                    f"(dim={self.dimension}, metric=COSINE)"
                )
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.dimension,
                        distance=Distance.COSINE,   # C++ 엔진이 코사인 유사도 계산
                    ),
                )
        except Exception as e:
            print(f"[vector_store] 컬렉션 생성 오류: {e}")

    # ── 청크 색인 ─────────────────────────────────────────────────────────────

    def add(self, chunks: list, embeddings: np.ndarray) -> None:
        if not chunks:
            return

        points = []
        for chunk, vector in zip(chunks, embeddings):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.uid))
            payload = {
                "text":         chunk.text,
                "doc_id":       chunk.doc_id,
                "source":       chunk.source,
                "pub_date":     chunk.pub_date,
                "title":        chunk.title,
                "chunk_idx":    chunk.chunk_idx,
                "chunk_type":   chunk.chunk_type,
                "claim_number": chunk.claim_number,
                "sub_index":    chunk.sub_index,
                "language":     chunk.language,
                "ipc_codes":    chunk.ipc_codes or [],
                "cpc_codes":    chunk.cpc_codes or [],
            }
            points.append(PointStruct(id=point_id, vector=vector.tolist(), payload=payload))

        try:
            self.client.upsert(collection_name=self.collection_name, points=points)
            print(f"[vector_store] {len(chunks)}개 청크 색인 완료.")
        except Exception as e:
            print(f"[vector_store] upsert 오류: {e}")

    # ── 유사도 검색 ───────────────────────────────────────────────────────────

    def search(self, query_vec: np.ndarray, k: int = 10, filter_dict: dict = None) -> list:
        """
        Qdrant 내부 코사인 유사도로 상위 k개 반환.
        반환: list[tuple[Chunk, float]]  (score = cosine similarity, 높을수록 유사)
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
            hits = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vec.tolist(),
                query_filter=qdrant_filter,
                limit=k,
            )
        except Exception as e:
            print(f"[vector_store] 검색 오류: {e}")
            return []

        results = []
        for hit in hits:
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
                cpc_codes=p.get("cpc_codes", []),
            )
            results.append((chunk, hit.score))
        return results

    # ── 유틸리티 ─────────────────────────────────────────────────────────────

    def count(self) -> int:
        try:
            return self.client.get_collection(self.collection_name).points_count or 0
        except:
            return 0

    def clear(self) -> None:
        """컬렉션의 모든 벡터를 삭제하고 빈 컬렉션으로 초기화한다."""
        try:
            self.client.delete_collection(self.collection_name)
            print(f"[vector_store] 컬렉션 '{self.collection_name}' 초기화 완료.")
        except Exception:
            pass
        self._ensure_collection()

    def save(self, name: str) -> None:
        pass  # 인메모리: no-op / 로컬: Qdrant가 자동 저장

    def load(self, name: str) -> bool:
        return self.count() > 0
