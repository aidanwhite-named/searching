import json
import re
from dataclasses import dataclass, field
from src.llm_router import LLMRouter


@dataclass
class QuerySpec:
    claim_number: int
    keywords: list = field(default_factory=list)
    synonyms: dict = field(default_factory=dict)
    cpc_codes: list = field(default_factory=list)
    boolean_query: str = ""


_SYSTEM = (
    "당신은 특허청 심사관 수준의 전문가입니다. "
    "청구항을 분석하여 선행기술 데이터베이스 검색에 최적화된 쿼리를 JSON으로만 출력합니다."
)

_PROMPT = """\
아래 특허 청구항을 분석하여 선행기술 검색 쿼리를 생성하세요.

[기준일] {reference_date} 이전 문헌만 검색합니다.

[청구항 {claim_number}]
{claim_text}

JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "keywords": ["핵심 기술 용어 3~5개 (한/영 혼용 가능)"],
  "synonyms": {{"키워드": ["동의어1", "영문표현"]}},
  "cpc_codes": ["H01M10/42", "H02J7/00"],
  "boolean_query": "(keyword1 OR synonym1) AND keyword2 AND keyword3"
}}"""


def _extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 객체 추출. 코드블록 및 날 JSON 모두 처리."""
    # ```json ... ``` 블록
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # 중첩 중괄호 추적으로 JSON 경계 탐색
    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(text[start : i + 1])
    raise ValueError("응답에서 JSON을 찾을 수 없습니다.")


class QueryGenerator:
    def __init__(self, router: LLMRouter):
        self.router = router

    def generate(self, claim_number: int, claim_text: str, reference_date: str) -> QuerySpec:
        prompt = _PROMPT.format(
            reference_date=reference_date,
            claim_number=claim_number,
            claim_text=claim_text,
        )
        response = self.router.call(prompt, system=_SYSTEM, max_tokens=1024)
        return self._parse(response, claim_number)

    def _parse(self, response: str, claim_number: int) -> QuerySpec:
        try:
            data = _extract_json(response)
            return QuerySpec(
                claim_number=claim_number,
                keywords=data.get("keywords", []),
                synonyms=data.get("synonyms", {}),
                cpc_codes=data.get("cpc_codes", []),
                boolean_query=data.get("boolean_query", ""),
            )
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[warn] 쿼리 파싱 실패 (청구항 {claim_number}): {e}")
            print(f"       응답 앞부분: {response[:300]}")
            return QuerySpec(claim_number=claim_number)
