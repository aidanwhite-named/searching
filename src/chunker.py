from dataclasses import dataclass
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.search_clients import SearchResult


@dataclass
class Chunk:
    text: str
    doc_id: str
    source: str
    pub_date: str
    title: str
    chunk_idx: int

    @property
    def uid(self) -> str:
        return f"{self.source}_{self.doc_id}_{self.chunk_idx}"


_MIN_CHUNK_CHARS = 50


class Chunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", " ", ""],
        )

    def chunk_document(self, result: SearchResult, text: str) -> list:
        """단일 문서 텍스트를 Chunk 리스트로 분리."""
        if not text or not text.strip():
            return []
        raw_chunks = self._splitter.split_text(text)
        chunks = []
        for idx, raw in enumerate(raw_chunks):
            raw = raw.strip()
            if len(raw) < _MIN_CHUNK_CHARS:
                continue
            chunks.append(Chunk(
                text=raw,
                doc_id=result.doc_id,
                source=result.source,
                pub_date=result.pub_date,
                title=result.title,
                chunk_idx=idx,
            ))
        return chunks

    def chunk_all(self, search_results: list, cache) -> list:
        """
        ClaimSearchResults 목록 전체에서 문서 텍스트를 로드해 청킹.
        중복 doc_id는 한 번만 처리.
        """
        seen: set[str] = set()
        all_chunks: list[Chunk] = []

        for claim_result in search_results:
            for result in claim_result.results:
                uid = f"{result.source}_{result.doc_id}"
                if uid in seen:
                    continue
                seen.add(uid)

                text = cache.load_text(result.source, result.doc_id)
                if not text:
                    # 캐시에 텍스트 없으면 abstract만 사용
                    text = result.abstract or ""
                chunks = self.chunk_document(result, text)
                all_chunks.extend(chunks)

        return all_chunks
