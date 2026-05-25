"""
검색 결과 문서 로컬 JSON 캐시.
Phase 5 할루시네이션 검증기에서 exact-match할 전문(full_text)도 저장한다.
"""

import json
import os
import re
import urllib.request
from providers.base_provider import SearchResult
from src.logger import get_logger

logger = get_logger(__name__)


class DocumentCache:
    def __init__(self, cache_dir: str = ".cache/documents"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, source: str, doc_id: str) -> str:
        safe_id = re.sub(r"[^\w\-.]", "_", doc_id)
        return os.path.join(self.cache_dir, f"{source}_{safe_id}.json")

    def get(self, source: str, doc_id: str) -> dict | None:
        path = self._path(source, doc_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def store(self, result: SearchResult, full_text: str = "") -> str:
        """SearchResult를 JSON으로 저장. 경로 반환."""
        path = self._path(result.source, result.doc_id)
        payload = {
            "doc_id": result.doc_id,
            "title": result.title,
            "abstract": result.abstract,
            "pub_date": result.pub_date,
            "source": result.source,
            "url": result.url,
            "full_text": full_text,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.debug("캐시 저장: %s/%s", result.source, result.doc_id[:30])
        return path

    def fetch_and_store(self, result: SearchResult) -> SearchResult:
        """캐시 미스 시 저장. 이미 있으면 local_path만 채워 반환."""
        cached = self.get(result.source, result.doc_id)
        if cached:
            logger.debug("캐시 HIT: %s/%s", result.source, result.doc_id[:30])
            result.local_path = self._path(result.source, result.doc_id)
            return result

        logger.debug("캐시 MISS: %s/%s — 신규 저장", result.source, result.doc_id[:30])
        full_text = self._try_fetch_text(result)
        result.local_path = self.store(result, full_text)
        return result

    def _try_fetch_text(self, result: SearchResult) -> str:
        """
        Semantic Scholar open-access PDF URL이 있으면 텍스트 추출 시도.
        실패하면 abstract만 사용.
        """
        if result.source != "semantic_scholar" or not result.url.endswith(".pdf"):
            return ""
        try:
            req = urllib.request.Request(
                result.url,
                headers={"User-Agent": "PatentSearchCLI/1.0"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return ""
        except Exception as e:
            logger.debug("전문 fetch 실패 (%s): %s", result.url[:50], e)
            return ""

    def load_text(self, source: str, doc_id: str) -> str:
        """저장된 문서의 전문 + abstract 결합 텍스트 반환 (할루시네이션 검증용)."""
        cached = self.get(source, doc_id)
        if not cached:
            logger.debug("load_text MISS: %s/%s", source, doc_id[:30])
            return ""
        parts = [cached.get("abstract", ""), cached.get("full_text", "")]
        return "\n\n".join(p for p in parts if p)
