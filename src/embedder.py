import numpy as np
from sentence_transformers import SentenceTransformer


class Embedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        print(f"[embedder] 모델 로드: {model_name}")
        self._model = SentenceTransformer(model_name)
        self.dimension = self._model.get_embedding_dimension()
        print(f"[embedder] 차원: {self.dimension}")

    def embed(self, texts: list, batch_size: int = 64) -> np.ndarray:
        """텍스트 목록을 임베딩. 반환: L2 정규화된 (N, D) float32 배열."""
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vecs = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 100,
            normalize_embeddings=True,  # L2 정규화 → 내적 = 코사인 유사도
            convert_to_numpy=True,
        )
        return vecs.astype(np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        """단일 텍스트 임베딩. 반환: (D,) float32."""
        return self.embed([text])[0]
