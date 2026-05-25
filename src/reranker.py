import time

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from src.logger import get_logger

logger = get_logger(__name__)


class Reranker:
    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("리랭커 모델 로드 중: '%s' (device=%s)", model_name, self.device)
        t0 = time.time()
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
        self.model.eval()
        logger.info("리랭커 모델 로드 완료: %.1f초", time.time() - t0)

    def rerank(self, query: str, candidates: list, top_k: int = 10) -> list:
        """
        Rerank candidate chunks based on similarity to query text.
        candidates: list of tuple(Chunk, float) or list of Chunk.
        Returns: list of tuple(Chunk, float) sorted by reranker score descending, limited to top_k.
        """
        if not candidates:
            return []

        # Standardize candidates to list of Chunk
        chunks = []
        for c in candidates:
            if isinstance(c, tuple):
                chunks.append(c[0])
            else:
                chunks.append(c)

        logger.debug("리랭킹 시작: 후보 %d개 → top_%d 선택", len(chunks), top_k)
        t0 = time.time()

        pairs = [[query, chunk.text] for chunk in chunks]

        try:
            with torch.no_grad():
                inputs = self.tokenizer(
                    pairs,
                    padding=True,
                    truncation=True,
                    return_tensors='pt',
                    max_length=512
                ).to(self.device)

                logits = self.model(**inputs).logits.view(-1,)
                scores = torch.sigmoid(logits).cpu().numpy().tolist()

            scored = [(chunks[idx], float(scores[idx])) for idx in range(len(chunks))]
            scored.sort(key=lambda x: x[1], reverse=True)
            result = scored[:top_k]
            elapsed = time.time() - t0
            if result:
                logger.debug(
                    "리랭킹 완료: %.1f초, top 점수=%.3f~%.3f",
                    elapsed, result[0][1], result[-1][1],
                )
            return result

        except Exception as e:
            logger.error("리랭킹 실패: %s — 원래 순서로 fallback", e)
            return [(chunks[idx], 1.0 / (idx + 1)) for idx in range(len(chunks))][:top_k]
