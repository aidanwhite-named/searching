"""
할루시네이션 검증기.
LLM이 추출한 단락이 원본 문서에 정확히 존재하는지 exact match로 검증.
실패 시 LLM 재귀 호출 (최대 max_retries).
"""

import re
from src.matcher import DocumentMatch
from src.document_cache import DocumentCache
from src.llm_router import LLMRouter


_SYSTEM = (
    "당신은 특허 심사관입니다. "
    "선행문헌에서 주어진 청구항 특징을 개시하는 단락을 정확히 인용해야 합니다. "
    "반드시 선행문헌에 실제로 존재하는 텍스트만 그대로 인용하세요."
)

_EXTRACT_PROMPT = """\
[청구항 {claim_number}]
{claim_text}

[선행문헌: {doc_id}]
{doc_text}

위 선행문헌에서 청구항의 핵심 기술적 특징을 개시하는 단락을 찾아 **원문 그대로** 인용하세요.
응답은 반드시 다음 형식으로만:
PARAGRAPH: <원문 단락>"""

_RETRY_PROMPT = """\
이전에 인용한 단락이 원본 문서에서 발견되지 않았습니다. (시도 {attempt}/{max_retries})
원본 문서에 실제로 존재하는 텍스트를 정확히 인용해야 합니다.

[청구항 {claim_number}]
{claim_text}

[선행문헌: {doc_id} — 원문]
{doc_text}

응답 형식:
PARAGRAPH: <원문 단락>"""

_MAX_DOC_CHARS = 4000  # LLM 컨텍스트 절약


def _parse_paragraph(response: str) -> str:
    """응답에서 'PARAGRAPH: ...' 이후 텍스트 추출."""
    m = re.search(r"PARAGRAPH\s*:\s*(.+)", response, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # 형식 미준수 시 전체 응답 반환
    return response.strip()


def _exact_match(paragraph: str, doc_text: str) -> bool:
    """단락이 문서 텍스트에 정확히 포함되는지 확인."""
    return bool(paragraph) and paragraph.strip() in doc_text


class HallucinationChecker:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def find_and_verify(
        self,
        claim_number: int,
        claim_text: str,
        doc_match: DocumentMatch,
        router: LLMRouter,
        cache: DocumentCache,
    ) -> tuple[str, bool]:
        """
        LLM으로 매칭 단락 추출 → exact match 검증 → 실패 시 재시도.
        반환: (matched_paragraph, is_verified)
        """
        doc_text = cache.load_text(doc_match.source, doc_match.doc_id)
        if not doc_text:
            # 캐시에 텍스트 없으면 best_chunk만 검증
            return doc_match.matched_paragraph, False

        truncated = doc_text[:_MAX_DOC_CHARS]
        paragraph = ""

        for attempt in range(1, self.max_retries + 1):
            if attempt == 1:
                prompt = _EXTRACT_PROMPT.format(
                    claim_number=claim_number,
                    claim_text=claim_text,
                    doc_id=doc_match.doc_id,
                    doc_text=truncated,
                )
            else:
                prompt = _RETRY_PROMPT.format(
                    attempt=attempt,
                    max_retries=self.max_retries,
                    claim_number=claim_number,
                    claim_text=claim_text,
                    doc_id=doc_match.doc_id,
                    doc_text=truncated,
                )

            try:
                response = router.call(prompt, system=_SYSTEM, max_tokens=512)
            except Exception as e:
                print(f"    [checker] LLM 호출 실패 (시도 {attempt}): {e}")
                continue

            paragraph = _parse_paragraph(response)
            if _exact_match(paragraph, doc_text):
                return paragraph, True
            print(f"    [checker] Exact match 실패 (시도 {attempt}/{self.max_retries}): {paragraph[:60]}...")

        return paragraph, False

    def verify_only(self, paragraph: str, doc_match: DocumentMatch, cache: DocumentCache) -> bool:
        """LLM 없이 exact match만 수행 (--no-llm 모드용)."""
        doc_text = cache.load_text(doc_match.source, doc_match.doc_id)
        return _exact_match(paragraph, doc_text) if doc_text else False
