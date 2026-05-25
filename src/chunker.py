import re
from dataclasses import dataclass, field
from langchain_text_splitters import RecursiveCharacterTextSplitter
from providers.base_provider import SearchResult
from src.claims_parser import ClaimsParser
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Chunk:
    text: str
    doc_id: str
    source: str
    pub_date: str
    title: str
    chunk_idx: int
    chunk_type: str = "summary"         # "abstract" | "summary" | "claim" | "independent_claim" | "sub_claim"
    claim_number: int | None = None
    sub_index: str | None = None        # "A", "B", "C" etc. for sub-claims
    language: str = "en"
    ipc_codes: list[str] = field(default_factory=list)
    cpc_codes: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        suffix = f"_{self.chunk_type}"
        if self.claim_number is not None:
            suffix += f"_{self.claim_number}"
        if self.sub_index is not None:
            suffix += f"_{self.sub_index}"
        return f"{self.source}_{self.doc_id}_{self.chunk_idx}{suffix}"


class Chunker:
    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", "。", " ", ""],
        )
        self._parser = ClaimsParser()

    def chunk_document(self, result: SearchResult, full_text: str) -> list[Chunk]:
        """
        Chunk a single document based on its claim structure and sections.
        """
        is_patent = result.source in ("kipris", "epo")
        chunks = []

        # 1. Abstract Chunk
        if result.abstract and result.abstract.strip():
            chunks.append(Chunk(
                text=result.abstract.strip(),
                doc_id=result.doc_id,
                source=result.source,
                pub_date=result.pub_date,
                title=result.title,
                chunk_idx=0,
                chunk_type="abstract",
                language=result.language,
                ipc_codes=result.ipc_codes,
                cpc_codes=result.cpc_codes
            ))

        if not full_text or not full_text.strip():
            logger.debug("[%s/%s] 전문 없음 — abstract 청크만 생성", result.source, result.doc_id[:20])
            return chunks

        # 2. Extract Claims (특허만)
        claims_dict = {}
        if is_patent:
            try:
                claims_sec = self._extract_claims_section(full_text)
                if claims_sec:
                    nodes = self._parser.parse(claims_sec)
                    for num, node in nodes.items():
                        claims_dict[num] = node
                    logger.debug("[%s/%s] 청구항 파싱: %d개", result.source, result.doc_id[:20], len(claims_dict))
            except Exception as e:
                logger.warning("[%s/%s] 청구항 파싱 실패: %s", result.source, result.doc_id[:20], e)

        # 3. Claim Chunks
        chunk_idx = 1
        if claims_dict:
            for num, node in claims_dict.items():
                is_ind = node.is_independent
                ctype = "independent_claim" if is_ind else "claim"

                chunks.append(Chunk(
                    text=node.text,
                    doc_id=result.doc_id,
                    source=result.source,
                    pub_date=result.pub_date,
                    title=result.title,
                    chunk_idx=chunk_idx,
                    chunk_type=ctype,
                    claim_number=num,
                    language=result.language,
                    ipc_codes=result.ipc_codes,
                    cpc_codes=result.cpc_codes
                ))
                chunk_idx += 1

                # Sub-claim 분할 (세미콜론 기준)
                sub_parts = [p.strip() for p in re.split(r";", node.text) if len(p.strip()) > 30]
                if len(sub_parts) > 1:
                    for idx, part in enumerate(sub_parts):
                        sub_char = chr(65 + idx)  # A, B, C...
                        chunks.append(Chunk(
                            text=part,
                            doc_id=result.doc_id,
                            source=result.source,
                            pub_date=result.pub_date,
                            title=result.title,
                            chunk_idx=chunk_idx,
                            chunk_type="sub_claim",
                            claim_number=num,
                            sub_index=sub_char,
                            language=result.language,
                            ipc_codes=result.ipc_codes,
                            cpc_codes=result.cpc_codes
                        ))
                        chunk_idx += 1

        # 4. Description/Summary Chunks
        desc_text = full_text
        if claims_dict:
            claims_sec = self._extract_claims_section(full_text)
            if claims_sec:
                desc_text = full_text.replace(claims_sec, "")

        raw_desc_chunks = self._splitter.split_text(desc_text)
        desc_count = 0
        for raw in raw_desc_chunks:
            raw = raw.strip()
            if len(raw) < 50:
                continue
            chunks.append(Chunk(
                text=raw,
                doc_id=result.doc_id,
                source=result.source,
                pub_date=result.pub_date,
                title=result.title,
                chunk_idx=chunk_idx,
                chunk_type="summary",
                language=result.language,
                ipc_codes=result.ipc_codes,
                cpc_codes=result.cpc_codes
            ))
            chunk_idx += 1
            desc_count += 1

        logger.debug(
            "[%s/%s] 청킹 완료: abstract=%d, claims=%d, summary=%d, 합계=%d",
            result.source, result.doc_id[:20],
            1 if result.abstract else 0, len(claims_dict), desc_count, len(chunks),
        )
        return chunks

    def chunk_all(self, search_results: list, cache) -> list[Chunk]:
        """
        Retrieve document text from cache, chunk it, and return all chunks.
        """
        seen: set[str] = set()
        all_chunks: list[Chunk] = []

        total_docs = sum(len(cr.results) for cr in search_results)
        logger.info("전체 문서 청킹 시작: 청구항별 결과 %d건 (중복 제외)", total_docs)

        for claim_result in search_results:
            for result in claim_result.results:
                uid = f"{result.source}_{result.doc_id}"
                if uid in seen:
                    continue
                seen.add(uid)

                text = cache.load_text(result.source, result.doc_id)
                if not text:
                    text = result.abstract or ""
                chunks = self.chunk_document(result, text)
                all_chunks.extend(chunks)

        logger.info("전체 청킹 완료: 고유 문서 %d개 → %d개 청크", len(seen), len(all_chunks))
        return all_chunks

    def _extract_claims_section(self, text: str) -> str:
        pattern = re.compile(
            r"(?:^|\n)#+\s*(?:청구\s*범위|CLAIMS?)\s*\n(.*?)(?=\n#+\s|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        m = pattern.search(text)
        if m:
            return m.group(1).strip()
        return ""
