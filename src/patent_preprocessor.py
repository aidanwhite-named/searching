import re
from dataclasses import dataclass, field
from typing import Optional
from src.pdf_parser import PDFParser


@dataclass
class PatentData:
    reference_date: str        # "YYYY-MM-DD"
    date_type: str             # "priority" | "filing" | "unknown"
    claims_markdown: str       # 청구범위 섹션 원문
    full_markdown: str         # 전체 Markdown
    title: str = ""


# ── 날짜 패턴 ────────────────────────────────────────────────────────────────

# 한국식: 2023. 01. 15  /  2023-01-15  /  2023.01.15
_KR_DATE = r"(\d{4})[.\-\s]+(\d{1,2})[.\-\s]+(\d{1,2})"

_PRIORITY_PATTERNS = [
    # 한국어 우선권
    re.compile(rf"우선권\s*주장일?\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    re.compile(rf"우선일\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    # 영어 우선권
    re.compile(r"Priority\s+Date\s*[:：]\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    re.compile(r"Priority\s+Date\s*[:：]\s*(\w+\.?\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
    re.compile(r"filed\s+(\w+\.?\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
]

_FILING_PATTERNS = [
    # 한국어 출원일
    re.compile(rf"출원일\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    re.compile(rf"출원\s*일자\s*[:：]\s*{_KR_DATE}", re.IGNORECASE),
    # 영어 출원일
    re.compile(r"(?:Filing|Application)\s+Date\s*[:：]\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    re.compile(r"(?:Filing|Application)\s+Date\s*[:：]\s*(\w+\.?\s+\d{1,2},?\s+\d{4})", re.IGNORECASE),
]

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ── 청구범위 섹션 패턴 ────────────────────────────────────────────────────────

_CLAIMS_SECTION = re.compile(
    r"(?:^|\n)#+\s*(?:청구\s*범위|CLAIMS?)\s*\n(.*?)(?=\n#+\s|\Z)",
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

    # ISO 형식 직접 매칭
    if len(groups) == 1:
        raw = groups[0].strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", raw):
            return raw
        # "January 15, 2023" 형식
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

    # 한국식 연/월/일 그룹
    try:
        y, m_num, d = int(groups[0]), int(groups[1]), int(groups[2])
        return f"{y:04d}-{m_num:02d}-{d:02d}"
    except (ValueError, IndexError):
        return None


class PatentPreprocessor:
    def __init__(self):
        self._parser = PDFParser()

    def process(self, pdf_path: str) -> PatentData:
        full_md = self._parser.parse(pdf_path)
        ref_date, date_type = self._extract_date(full_md)
        claims_md = self._extract_claims_section(full_md)
        title = self._extract_title(full_md)
        return PatentData(
            reference_date=ref_date,
            date_type=date_type,
            claims_markdown=claims_md,
            full_markdown=full_md,
            title=title,
        )

    def process_markdown(self, full_md: str) -> PatentData:
        """이미 변환된 Markdown 문자열로 처리 (테스트/재처리용)."""
        ref_date, date_type = self._extract_date(full_md)
        claims_md = self._extract_claims_section(full_md)
        title = self._extract_title(full_md)
        return PatentData(
            reference_date=ref_date,
            date_type=date_type,
            claims_markdown=claims_md,
            full_markdown=full_md,
            title=title,
        )

    def _extract_date(self, text: str) -> tuple[str, str]:
        # 1순위: 우선권 주장일
        for pat in _PRIORITY_PATTERNS:
            m = pat.search(text)
            if m:
                date = _parse_date_groups(m)
                if date:
                    return date, "priority"

        # 2순위: 출원일
        for pat in _FILING_PATTERNS:
            m = pat.search(text)
            if m:
                date = _parse_date_groups(m)
                if date:
                    return date, "filing"

        return "unknown", "unknown"

    def _extract_claims_section(self, text: str) -> str:
        m = _CLAIMS_SECTION.search(text)
        if m:
            return m.group(1).strip()
        # fallback: 전체 반환 후 경고
        print("[warn] 청구범위 섹션을 찾지 못했습니다. 전체 텍스트를 사용합니다.")
        return text

    def _extract_title(self, text: str) -> str:
        for pat in _TITLE_PATTERNS:
            m = pat.search(text)
            if m:
                title = m.group(1).strip().strip("*#").strip()
                if len(title) > 3:
                    return title
        return ""
