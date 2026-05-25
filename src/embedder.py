import time

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from src.logger import get_logger

logger = get_logger(__name__)


class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("임베딩 모델 로드 중: '%s' (device=%s)", model_name, self.device)
        t0 = time.time()
        self._model = SentenceTransformer(model_name, device=self.device)
        self.dimension = self._model.get_embedding_dimension()
        logger.info("임베딩 모델 로드 완료: %.1f초, dimension=%d", time.time() - t0, self.dimension)

    def embed(self, texts: list, batch_size: int = 16) -> np.ndarray:
        """
        Embed a list of text segments.
        Returns: L2-normalized float32 NumPy array of shape (N, D).
        """
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        logger.debug("임베딩 시작: %d개 텍스트 (batch_size=%d)", len(texts), batch_size)
        t0 = time.time()
        vecs = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 20,
            normalize_embeddings=True,  # L2 normalization -> cosine similarity = inner product
            convert_to_numpy=True,
        )
        elapsed = time.time() - t0
        logger.info("임베딩 완료: %d개, %.1f초 (%.0f개/초)", len(texts), elapsed, len(texts) / max(elapsed, 0.001))
        return vecs.astype(np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        """Embed a single text segment. Returns float32 array of shape (D,)."""
        return self.embed([text])[0]
