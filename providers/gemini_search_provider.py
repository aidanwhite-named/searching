"""
Gemini 웹 검색 프로바이더.
Gemini CLI의 내장 Google 검색 도구를 활용해 Google Patents, Justia 등에서
실제 선행특허를 직접 검색한다. KIPRIS/EPO API 키가 없어도 동작.
"""

import json
import re
from providers.base_provider import BaseProvider, SearchResult

_SEARCH_PROMPT_BY_NUMBER = """\
특허번호 {patent_number}에 대한 선행기술조사를 수행하세요.

[단계 1] 먼저 웹 검색으로 특허번호 {patent_number}를 Google Patents 또는 KIPRIS에서 조회하여 \
이 특허의 발명 내용과 청구항을 파악하세요.

[단계 2] 파악한 발명 내용을 바탕으로, 기준일 {cutoff_date} 이전에 출원된 선행특허를 \
Google Patents, Justia, Espacenet, USPTO에서 최대 {limit}건 검색하세요.
참고 IPC/CPC 코드: {ipc_codes}

검색 완료 후 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "results": [
    {{
      "doc_id": "US10123456B2",
      "title": "발명 제목",
      "abstract": "핵심 내용 1~2문장 이내",
      "pub_date": "YYYY-MM-DD",
      "url": "https://patents.google.com/patent/US10123456B2",
      "source": "google_patents"
    }}
  ]
}}

중요: abstract는 반드시 100자 이내 영어로 작성하세요. 실제로 존재하는 특허번호만 포함하세요."""

_SEARCH_PROMPT_BY_CLAIM = """\
아래 특허 청구항과 기술적으로 관련된 선행특허를 Google Patents, Justia, Espacenet에서 \
웹 검색 도구를 사용하여 직접 찾아주세요.

[기준일] {cutoff_date} 이전 출원/공개 문헌만 포함하세요.
[검색 수] 최대 {limit}건

[청구항]
{claim_text}

검색 완료 후 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "results": [
    {{
      "doc_id": "US10123456B2",
      "title": "발명 제목",
      "abstract": "핵심 내용 1~2문장 이내",
      "pub_date": "YYYY-MM-DD",
      "url": "https://patents.google.com/patent/US10123456B2",
      "source": "google_patents"
    }}
  ]
}}

중요: abstract는 반드시 100자 이내 영어로 작성하세요. 실제로 존재하는 특허번호만 포함하세요."""


def _find_balanced(text: str, start: int) -> int:
    """start 위치의 '{' 에 대응하는 닫는 '}' 인덱스 반환. 없으면 -1."""
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 추출.
    JSON이 토큰 한도로 잘린 경우에도 완성된 result 객체만 부분 복구한다."""
    # 1) 마크다운 코드펜스 내 JSON 시도
    m = re.search(r"```(?:json)?\s*(\{[^`]*\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2) 완전한 최상위 JSON 객체 시도
    start = text.find("{")
    if start != -1:
        end = _find_balanced(text, start)
        if end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    # 3) 잘린 JSON 복구: "results" 배열에서 완성된 객체만 추출
    results_pos = text.find('"results"')
    if results_pos != -1:
        array_start = text.find("[", results_pos)
        if array_start != -1:
            recovered = []
            pos = array_start + 1
            while pos < len(text):
                obj_start = text.find("{", pos)
                if obj_start == -1:
                    break
                obj_end = _find_balanced(text, obj_start)
                if obj_end == -1:
                    break  # 불완전한 객체 — 더 이상 없음
                try:
                    recovered.append(json.loads(text[obj_start:obj_end + 1]))
                except json.JSONDecodeError:
                    pass
                pos = obj_end + 1
            if recovered:
                print(f"[gemini_search] 잘린 JSON 부분 복구: {len(recovered)}건")
                return {"results": recovered}

    raise ValueError("응답에서 JSON을 찾을 수 없습니다.")


class GeminiSearchProvider(BaseProvider):
    """Gemini CLI 웹 검색으로 Google Patents 등에서 선행특허를 직접 수집."""

    def __init__(self, router):
        self.router = router
        self.patent_number: str = ""   # search_pipeline이 주입
        self.ipc_codes: list = []

    def search(self, claim_text: str, cutoff_date: str, limit: int = 10) -> list[SearchResult]:
        import time
        # 특허번호가 있으면 번호 기반 조회 (더 정확)
        if self.patent_number:
            print(f"[gemini_search] 특허번호 {self.patent_number} 기반 선행기술 검색")
            prompt = _SEARCH_PROMPT_BY_NUMBER.format(
                patent_number=self.patent_number,
                cutoff_date=cutoff_date,
                limit=limit,
                ipc_codes=", ".join(self.ipc_codes[:6]) or "미추출",
            )
        else:
            print(f"[gemini_search] 청구항 텍스트 기반 선행기술 검색")
            prompt = _SEARCH_PROMPT_BY_CLAIM.format(
                cutoff_date=cutoff_date,
                limit=limit,
                claim_text=claim_text[:1500],
            )
        print("[gemini_search] Google Patents 웹 검색 중 — 보통 1~3분, 최대 5분 대기...")
        t0 = time.time()
        try:
            response = self.router.call(prompt, timeout=300)
        except Exception as e:
            print(f"[gemini_search] LLM 호출 오류 ({time.time()-t0:.0f}초 후): {e}")
            return []
        print(f"[gemini_search] 응답 수신 ({time.time()-t0:.0f}초, {len(response)}자)")

        return self._parse(response)

    def _parse(self, response: str) -> list[SearchResult]:
        try:
            data = _extract_json(response)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"[gemini_search] JSON 파싱 실패: {e}")
            print(f"  응답 앞부분: {response[:300]}")
            return []

        results = []
        for item in data.get("results", []):
            doc_id = item.get("doc_id", "").strip()
            if not doc_id:
                continue
            results.append(SearchResult(
                doc_id=doc_id,
                title=item.get("title", "").strip() or "Unknown Title",
                abstract=item.get("abstract", "").strip(),
                pub_date=item.get("pub_date", "unknown"),
                source=item.get("source", "gemini_search"),
                url=item.get("url", ""),
                language="en",
            ))

        print(f"[gemini_search] {len(results)}건 수집")
        return results
