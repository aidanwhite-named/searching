"""
외부 DB 검색 클라이언트.
각 클라이언트는 BaseSearchClient를 상속하며 search() 하나만 구현한다.
"""

import re
import time
import urllib.parse
import urllib.request
import urllib.error
import json
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from src.query_generator import QuerySpec


@dataclass
class SearchResult:
    doc_id: str
    title: str
    abstract: str
    pub_date: str      # "YYYY-MM-DD"
    source: str        # "kipris" | "uspto" | "semantic_scholar"
    url: str = ""
    local_path: str = ""


# ── 유틸리티 ─────────────────────────────────────────────────────────────────

def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PatentSearchCLI/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _date_ok(pub_date: str, cutoff: str) -> bool:
    """pub_date가 cutoff보다 이전인지 확인. 날짜 불명 시 포함."""
    if not pub_date or pub_date == "unknown":
        return True
    # YYYY-MM-DD 형식 비교 (lexicographic)
    return pub_date[:10] < cutoff[:10]


def _query_keywords(q: QuerySpec) -> str:
    """Boolean 식이 있으면 사용, 없으면 키워드 AND 결합."""
    if q.boolean_query:
        return q.boolean_query
    return " AND ".join(q.keywords) if q.keywords else ""


# ── 기반 클래스 ───────────────────────────────────────────────────────────────

class BaseSearchClient(ABC):
    @abstractmethod
    def search(self, query: QuerySpec, cutoff_date: str, max_results: int) -> list:
        """cutoff_date 이전 문헌만 반환. 오류 시 빈 리스트."""


# ── KIPRIS (한국특허정보원) ───────────────────────────────────────────────────

_KIPRIS_BASE = "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getWordSearch"

class KiprisClient(BaseSearchClient):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: QuerySpec, cutoff_date: str, max_results: int) -> list:
        if not self.api_key:
            print("[kipris] API 키 없음 — skip")
            return []
        kw = _query_keywords(query)
        if not kw:
            return []
        params = urllib.parse.urlencode({
            "ServiceKey": self.api_key,
            "searchWord": kw,
            "pageNo": 1,
            "numOfRows": max_results,
        })
        url = f"{_KIPRIS_BASE}?{params}"
        try:
            raw = _http_get(url)
            return self._parse_xml(raw, cutoff_date)
        except Exception as e:
            print(f"[kipris] 검색 오류: {e}")
            return []

    def _parse_xml(self, raw: str, cutoff_date: str) -> list:
        results = []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"[kipris] XML 파싱 오류: {e}")
            return []
        for item in root.iter("item"):
            t = lambda tag: (item.findtext(tag) or "").strip()
            pub_date = self._normalize_date(t("openDate") or t("applicationDate"))
            if not _date_ok(pub_date, cutoff_date):
                continue
            doc_id = t("applicationNumber") or t("registrationNumber")
            results.append(SearchResult(
                doc_id=doc_id,
                title=t("inventionTitle"),
                abstract=t("astrtCont") or t("abstract") or "",
                pub_date=pub_date,
                source="kipris",
                url=f"https://www.kipris.or.kr/khome/main.jsp?method=getLitPatent&isPatent=TRUE&docId={doc_id}",
            ))
        return results

    @staticmethod
    def _normalize_date(raw: str) -> str:
        """YYYYMMDD → YYYY-MM-DD"""
        raw = re.sub(r"\D", "", raw)
        if len(raw) == 8:
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        return raw


# ── USPTO PatentsView ─────────────────────────────────────────────────────────

_USPTO_BASE = "https://search.patentsview.org/api/v1/patent/"
_USPTO_FIELDS = [
    "patent_number", "patent_title", "patent_abstract",
    "patent_date", "patent_type",
]

class UsptoClient(BaseSearchClient):
    def search(self, query: QuerySpec, cutoff_date: str, max_results: int) -> list:
        kw = " ".join(query.keywords) if query.keywords else ""
        if not kw:
            return []
        q_obj = {
            "_and": [
                {"_text_any": {"patent_abstract": kw}},
                {"_lte": {"patent_date": cutoff_date}},
            ]
        }
        params = urllib.parse.urlencode({
            "q": json.dumps(q_obj),
            "f": json.dumps(_USPTO_FIELDS),
            "o": json.dumps({"per_page": max_results}),
        })
        url = f"{_USPTO_BASE}?{params}"
        try:
            raw = _http_get(url)
            data = json.loads(raw)
            return self._parse(data)
        except Exception as e:
            print(f"[uspto] 검색 오류: {e}")
            return []

    def _parse(self, data: dict) -> list:
        results = []
        for p in data.get("patents") or []:
            pnum = p.get("patent_number", "")
            results.append(SearchResult(
                doc_id=pnum,
                title=p.get("patent_title", ""),
                abstract=p.get("patent_abstract", ""),
                pub_date=p.get("patent_date", ""),
                source="uspto",
                url=f"https://patents.google.com/patent/US{pnum}",
            ))
        return results


# ── Semantic Scholar ──────────────────────────────────────────────────────────

_S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_FIELDS = "title,abstract,year,openAccessPdf,externalIds"

class SemanticScholarClient(BaseSearchClient):
    # 무료 티어 속도 제한 대응 (1 req/sec)
    _last_call: float = 0.0

    def search(self, query: QuerySpec, cutoff_date: str, max_results: int) -> list:
        kw = " ".join(query.keywords) if query.keywords else ""
        if not kw:
            return []
        # 속도 제한
        elapsed = time.time() - SemanticScholarClient._last_call
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)

        cutoff_year = int(cutoff_date[:4]) if cutoff_date and cutoff_date != "unknown" else 9999
        params = urllib.parse.urlencode({
            "query": kw,
            "limit": max_results,
            "fields": _S2_FIELDS,
        })
        url = f"{_S2_BASE}?{params}"
        try:
            SemanticScholarClient._last_call = time.time()
            raw = _http_get(url)
            data = json.loads(raw)
            return self._parse(data, cutoff_year)
        except Exception as e:
            print(f"[semantic_scholar] 검색 오류: {e}")
            return []

    def _parse(self, data: dict, cutoff_year: int) -> list:
        results = []
        for p in data.get("data") or []:
            year = p.get("year") or 0
            if year and year >= cutoff_year:
                continue
            pdf_info = p.get("openAccessPdf") or {}
            ext_ids = p.get("externalIds") or {}
            paper_id = p.get("paperId", "")
            results.append(SearchResult(
                doc_id=paper_id,
                title=p.get("title", ""),
                abstract=p.get("abstract") or "",
                pub_date=f"{year}-01-01" if year else "unknown",
                source="semantic_scholar",
                url=pdf_info.get("url") or f"https://www.semanticscholar.org/paper/{paper_id}",
            ))
        return results


# ── Espacenet (stub) ──────────────────────────────────────────────────────────

class EspacenetClient(BaseSearchClient):
    def search(self, query: QuerySpec, cutoff_date: str, max_results: int) -> list:
        # TODO: EPO OPS API OAuth2 인증 구현 예정
        print("[espacenet] 미구현 stub — skip")
        return []


# ── 팩토리 ───────────────────────────────────────────────────────────────────

def build_clients(config) -> dict:
    """config에서 API 키를 읽어 활성 클라이언트 딕셔너리 반환."""
    kipris_key = config.get("search", "kipris_api_key", default="") or ""
    return {
        "kipris": KiprisClient(kipris_key),
        "uspto": UsptoClient(),
        "semantic_scholar": SemanticScholarClient(),
        "espacenet": EspacenetClient(),
    }
