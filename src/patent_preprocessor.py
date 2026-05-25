import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional
from src.pdf_parser import PDFParser
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PatentData:
    reference_date: str        # "YYYY-MM-DD"
    date_type: str             # "priority" | "filing" | "unknown"
    claims_markdown: str       # 청구범위 섹션 원문
    full_markdown: str         # 전체 Markdown
    title: str = ""
    patent_number: str = ""    # 등록번호 (예: KR10-1942527)
    ipc_codes: list = field(default_factory=list)  # 추출된 IPC/CPC 코드


# ── 날짜 패턴 ────────────────────────────────────────────────────────────────

# 한국식 숫자: 2023. 01. 15  /  2023-01-15  /  2023.01.15
_KR_DATE = r"(\d{4})[.\-\s]+(\d{1,2})[.\-\s]+(\d{1,2})"
# 한국식 한글: 2015년11월09일 (KIPRIS 평문 출력)
_KR_DATE_HAN = r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"

_PRIORITY_PATTERNS = [
    re.compile(rf"우선권\s*주장일?\s+{_KR_DATE_HAN}", re.IGNORECASE),
    re.compile(rf"우선일\s+{_KR_DATE_HAN}", re.IGNORECASE),
    re.compile(rf"우선권\s*주장일?\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    re.compile(rf"우선일\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    re.compile(r"Priority\s+Date\s*[:：]\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    re.compile(r"Priority\s+Date\s*[:：]\s*(\w+\.?\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"filed\s+(\w+\.?\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
]

_FILING_PATTERNS = [
    re.compile(rf"출원일자\s+{_KR_DATE_HAN}", re.IGNORECASE),
    re.compile(rf"출원일\s+{_KR_DATE_HAN}", re.IGNORECASE),
    re.compile(rf"출원일\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    re.compile(rf"출원\s*일자\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    re.compile(r"(?:Filing|Application)\s+Date\s*[:：]\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    re.compile(r"(?:Filing|Application)\s+Date\s*[:：]\s*(\w+\.?\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
]

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ── 청구범위 섹션 패턴 ────────────────────────────────────────────────────────

_CLAIMS_SECTION = re.compile(
    r"(?:^|\n)(?:#+\s*)?(?:청구\s*범위|CLAIMS?)\s*\n(.*?)"
    r"(?=\n발명의\s*설명|\n【발명의\s*설명】|\n#+\s|\Z)",
    re.IGNORECASE | re.DOTALL,
)

# ── 제목 패턴 ─────────────────────────────────────────────────────────────────

_TITLE_PATTERNS = [
    re.compile(r"발명의\s*명칭\s*[:：]?\s*(.+)", re.IGNORECASE),
    re.compile(r"Title\s+of\s+Invention\s*[:：]?\s*(.+)", re.IGNORECASE),
    re.compile(r"^#\s+(.+)", re.MULTILINE),
]


def _parse_date_groups(m: re.Match) -> Optional[str]:
    """Match 객체에서 YYYY-MM-DD 문자열 추출. 실패 시 None."""
    groups = [g for g in m.groups() if g is not None]
    if not groups:
        return None

    if len(groups) == 1:
        raw = groups[0].strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", raw):
            return raw
        parts = re.split(r"[\s,]+", raw)
        parts = [p for p in parts if p]
        if len(parts) >= 3:
            try:
                month_str = parts[0].rstrip(".").lower()[:3]
                month = _MONTH_MAP.get(month_str)
                day = int(re.sub(r"\D", "", parts[1]))
                year = int(parts[-1])
                if month:
                    return f"{year:04d}-{month:02d}-{day:02d}"
            except (ValueError, IndexError):
                pass
        return None

    try:
        y, m_num, d = int(groups[0]), int(groups[1]), int(groups[2])
        return f"{y:04d}-{m_num:02d}-{d:02d}"
    except (ValueError, IndexError):
        return None


# ── LLM 추출 프롬프트 ─────────────────────────────────────────────────────────

_LLM_EXTRACT_PROMPT = """\
아래는 특허 명세서 PDF에서 추출한 원본 텍스트입니다.
다음 메타데이터를 JSON으로만 응답하세요 (설명·코드펜스 없이 JSON 객체만):

- reference_date: 우선권 주장일이 있으면 그 날짜, 없으면 출원일을 "YYYY-MM-DD"로
- date_type: "priority" | "filing" | "unknown"
- title: 발명의 명칭 (찾지 못하면 "")
- patent_number: 등록번호·출원번호 (예: "10-1942527", "US10123456B2", 없으면 "")
- ipc_codes: IPC/CPC 코드 배열 (예: ["B60W40/02", "B60W10/20"])
- claims_start_line: 청구범위 섹션을 표시하는 첫 줄의 원문 문자열 그대로 \
  (예: "청구범위" 또는 "청구항 1" 또는 "What is claimed is:"). 절대 가공·번역 금지.
- claims_end_line: 청구범위 다음에 오는 섹션의 첫 줄 원문 문자열 그대로 \
  (예: "발명의 설명" / "기 술 분 야" / "DETAILED DESCRIPTION"). \
  청구범위가 문서 끝이면 "".

응답 JSON 스키마:
{{"reference_date":"YYYY-MM-DD","date_type":"priority|filing|unknown",\
"title":"...","patent_number":"...","ipc_codes":["..."],\
"claims_start_line":"...","claims_end_line":"..."}}

[특허 텍스트]
{full_text}
"""


def _extract_json_object(text: str) -> Optional[dict]:
    """LLM 응답에서 첫 번째 완전한 JSON 객체 추출."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


class PatentPreprocessor:
    def __init__(self, router=None, cache_dir: str = ".cache/extracted"):
        """
        router: LLMRouter (있으면 LLM 추출 우선, 없으면 정규식만 사용)
        cache_dir: PDF 추출 텍스트를 저장할 디렉토리 (디버깅·재처리용)
        """
        self._parser = PDFParser()
        self._router = router
        self._cache_dir = Path(cache_dir)

    def process(self, pdf_path: str) -> PatentData:
        logger.info("PDF 파싱 시작: %s", pdf_path)
        full_text = self._parser.parse(pdf_path)
        logger.info("PDF 텍스트 추출 완료: %d자", len(full_text))
        text_path = self._save_extracted_text(pdf_path, full_text)
        logger.debug("추출 텍스트 저장: %s", text_path)

        # 1차: 정규식 (빠르고 한국 특허에 안정적)
        try:
            data = self._process_with_regex(full_text)
            logger.info("정규식 파싱 성공: 날짜=%s (%s), 청구범위=%d자",
                        data.reference_date, data.date_type, len(data.claims_markdown))
            return data
        except ValueError as e:
            logger.warning("정규식 추출 실패: %s", e)

        # 2차: LLM 폴백 (해외 특허·낯선 양식 대응)
        if self._router is not None:
            logger.info("LLM 폴백 시도 중...")
            return self._process_with_llm(full_text)

        raise ValueError("청구범위를 추출하지 못했고 LLM 폴백도 사용 불가합니다.")

    # ── LLM 경로 ──────────────────────────────────────────────────────────────

    def _process_with_llm(self, full_text: str) -> PatentData:
        """LLM에게 텍스트를 보여주고 메타데이터를 JSON으로 받는다.
        청구범위 본문은 LLM이 알려준 시작/끝 마커로 원본에서 잘라낸다 \
        (할루시네이션·토큰 한도 회피)."""
        snippet = full_text[:8000]
        prompt = _LLM_EXTRACT_PROMPT.format(full_text=snippet)
        logger.info("LLM 메타데이터 추출 중 (%d자, 약 30~60초)...", len(snippet))

        response = self._router.call(prompt, timeout=120)
        data = _extract_json_object(response)
        if not data:
            raise ValueError(f"LLM 응답에서 JSON을 찾지 못함: {response[:200]}")

        ref_date = (data.get("reference_date") or "").strip()
        date_type = (data.get("date_type") or "unknown").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", ref_date):
            today = date.today().strftime("%Y-%m-%d")
            logger.warning("LLM이 유효한 날짜를 반환하지 않음 → 오늘(%s) 사용", today)
            ref_date, date_type = today, "unknown"

        start_line = (data.get("claims_start_line") or "").strip()
        end_line = (data.get("claims_end_line") or "").strip()
        claims_md = self._slice_claims(full_text, start_line, end_line)
        if not claims_md:
            raise ValueError(
                f"청구범위 마커로 슬라이싱 실패 (start={start_line!r}, end={end_line!r})"
            )

        patent_number = (data.get("patent_number") or "").strip()
        ipc_codes = [c.strip() for c in data.get("ipc_codes", []) if c.strip()]
        title = (data.get("title") or "").strip()

        logger.info("LLM 추출 완료: 날짜=%s (%s), 청구범위=%d자", ref_date, date_type, len(claims_md))
        if patent_number:
            logger.info("특허번호: %s", patent_number)
        if ipc_codes:
            logger.info("IPC/CPC: %s", ipc_codes[:5])

        return PatentData(
            reference_date=ref_date,
            date_type=date_type,
            claims_markdown=claims_md,
            full_markdown=full_text,
            title=title,
            patent_number=patent_number,
            ipc_codes=ipc_codes,
        )

    @staticmethod
    def _slice_claims(text: str, start_line: str, end_line: str) -> str:
        """원본 텍스트에서 start_line~end_line 사이를 추출."""
        if not start_line:
            return ""
        start_idx = text.find(start_line)
        if start_idx == -1:
            return ""
        body_start = start_idx + len(start_line)
        if end_line:
            end_idx = text.find(end_line, body_start)
            if end_idx == -1:
                return text[body_start:].strip()
            return text[body_start:end_idx].strip()
        return text[body_start:].strip()

    def _save_extracted_text(self, pdf_path: str, text: str) -> Path:
        """추출 텍스트를 .cache/extracted/<pdf명>.txt 에 저장."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        name = Path(pdf_path).stem + ".txt"
        out = self._cache_dir / name
        out.write_text(text, encoding="utf-8")
        return out

    # ── 정규식 경로 ────────────────────────────────────────────────────────────

    def _process_with_regex(self, full_md: str) -> PatentData:
        ref_date, date_type = self._extract_date(full_md)
        claims_md = self._extract_claims_section(full_md)  # 실패 시 ValueError
        title = self._extract_title(full_md)
        patent_number = self._extract_patent_number(full_md)
        ipc_codes = self._extract_ipc_codes(full_md)
        if patent_number:
            logger.info("특허번호 추출: %s", patent_number)
        if ipc_codes:
            logger.info("IPC/CPC 코드: %s", ipc_codes[:5])
        return PatentData(
            reference_date=ref_date,
            date_type=date_type,
            claims_markdown=claims_md,
            full_markdown=full_md,
            title=title,
            patent_number=patent_number,
            ipc_codes=ipc_codes,
        )

    def process_markdown(self, full_md: str) -> PatentData:
        """이미 변환된 Markdown 문자열로 처리 (테스트/재처리용, 정규식 경로)."""
        return self._process_with_regex(full_md)

    def _extract_date(self, text: str) -> tuple[str, str]:
        for pat in _PRIORITY_PATTERNS:
            m = pat.search(text)
            if m:
                date_str = _parse_date_groups(m)
                if date_str:
                    logger.debug("우선권 주장일 발견: %s", date_str)
                    return date_str, "priority"

        for pat in _FILING_PATTERNS:
            m = pat.search(text)
            if m:
                date_str = _parse_date_groups(m)
                if date_str:
                    logger.debug("출원일 발견: %s", date_str)
                    return date_str, "filing"

        today = date.today().strftime("%Y-%m-%d")
        logger.warning("특허 날짜를 찾지 못했습니다. 오늘 날짜(%s)를 기준일로 사용합니다.", today)
        return today, "unknown"

    def _extract_claims_section(self, text: str) -> str:
        m = _CLAIMS_SECTION.search(text)
        if m:
            return m.group(1).strip()
        raise ValueError(
            "청구범위 섹션을 찾지 못했습니다. "
            "PDF가 올바른 특허 명세서인지 확인하세요."
        )

    def _extract_title(self, text: str) -> str:
        for pat in _TITLE_PATTERNS:
            m = pat.search(text)
            if m:
                title = m.group(1).strip().strip("*#").strip()
                if len(title) > 3:
                    return title
        return ""

    def _extract_patent_number(self, text: str) -> str:
        patterns = [
            re.compile(r"\b(10-\d{7})\b"),
            re.compile(r"\b(10-\d{4}-\d{7})\b"),
            re.compile(r"\b(US\d{6,8}[A-Z]\d?)\b"),
            re.compile(r"\b(WO\d{4}[/\-]\d{6})\b"),
        ]
        for pat in patterns:
            m = pat.search(text)
            if m:
                return m.group(1)
        return ""

    def _extract_ipc_codes(self, text: str) -> list:
        pat = re.compile(r"\b([A-H]\d{2}[A-Z]\s*\d+/\d+)\b")
        codes = pat.findall(text)
        return list(dict.fromkeys(c.replace(" ", "") for c in codes))
