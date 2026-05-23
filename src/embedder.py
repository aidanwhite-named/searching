import numpy as np
import torch
from sentence_transformers import SentenceTransformer


class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3"):
        # Detect device
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[embedder] Loading embedding model '{model_name}' on device '{self.device}'")
        
        self._model = SentenceTransformer(model_name, device=self.device)
        self.dimension = self._model.get_embedding_dimension()
        print(f"[embedder] Model loaded successfully. Dimension: {self.dimension}")

    def embed(self, texts: list, batch_size: int = 16) -> np.ndarray:
        """
        Embed a list of text segments.
        Returns: L2-normalized float32 NumPy array of shape (N, D).
        """
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
            
        vecs = self._model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 20,
            normalize_embeddings=True,  # L2 normalization -> cosine similarity = inner product
            convert_to_numpy=True,
        )
        return vecs.astype(np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        """Embed a single text segment. Returns float32 array of shape (D,)."""
        return self.embed([text])[0]
