"""
EPO OPS Provider — python-epo-ops-client 기반
토큰 갱신·쓰로틀링·재시도를 라이브러리가 자동 처리.
"""

import os
import re
import xml.etree.ElementTree as ET
from providers.base_provider import BaseProvider, SearchResult


class EpoProvider(BaseProvider):
    def __init__(self, key: str = None, secret: str = None):
        self.key    = key    or os.getenv("EPO_OPS_KEY", "")
        self.secret = secret or os.getenv("EPO_OPS_SECRET", "")
        self._client = None  # lazy init

    # ── 클라이언트 초기화 ──────────────────────────────────────────────
    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import epo_ops
        except ImportError:
            raise ImportError(
                "pip install python-epo-ops-client  # EPO OPS 라이브러리 누락"
            )
        if not self.key or not self.secret:
            raise ValueError(
                "EPO OPS 키·시크릿이 없습니다. "
                "config.yaml의 search.epo_ops_key / epo_ops_secret 를 입력하세요."
            )
        # middlewares: 토큰 자동 갱신 + 요청 쓰로틀링
        self._client = epo_ops.Client(
            key=self.key,
            secret=self.secret,
            accept_type="xml",
            middlewares=[
                epo_ops.middlewares.Throttler(),
                epo_ops.middlewares.Dogpile(),   # 응답 캐싱
            ],
        )
        return self._client

    # ── 공개 API ──────────────────────────────────────────────────────
    def search(self, query: str, cutoff_date: str, limit: int = 10) -> list[SearchResult]:
        if not query:
            return []
        if not self.key or not self.secret:
            print("[epo] 키·시크릿 미설정 — EPO 검색 건너뜀.")
            return []

        try:
            client = self._get_client()
        except (ImportError, ValueError) as e:
            print(f"[epo] {e}")
            return []

        # CQL 쿼리 구성 (cut-off 날짜 필터 포함)
        safe_q  = query.replace('"', "").strip()
        cql     = f'txt="{safe_q}"'
        if cutoff_date:
            # EPO CQL 날짜 형식: YYYYMMDD
            date_str = cutoff_date[:10].replace("-", "")
            cql += f" AND pd<{date_str}"

        range_end = max(limit, 1)
        try:
            resp = client.published_data_search(
                cql=cql,
                range_begin=1,
                range_end=range_end,
            )
        except Exception as e:
            print(f"[epo] 검색 실패: {e}")
            return []

        return self._parse_xml(resp.text, cutoff_date)

    # ── XML 파싱 ──────────────────────────────────────────────────────
    def _parse_xml(self, raw: str, cutoff_date: str) -> list[SearchResult]:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"[epo] XML 파싱 오류: {e}")
            return []

        def first(element, suffix):
            for el in element.iter():
                if el.tag.endswith(suffix):
                    return el
            return None

        results = []
        for entry in root.iter():
            if not entry.tag.endswith("search-result"):
                continue

            biblio = first(entry, "bibliographic-data")
            if biblio is None:
                continue

            # ─ 문서 ID & 출판일 ─
            pub_ref = first(biblio, "publication-reference")
            doc_id, pub_date = "", "unknown"
            if pub_ref is not None:
                doc_id_el = first(pub_ref, "document-id")
                if doc_id_el is not None:
                    country = first(doc_id_el, "country")
                    doc_num = first(doc_id_el, "doc-number")
                    kind    = first(doc_id_el, "kind")
                    doc_id  = "".join(
                        el.text.strip() for el in [country, doc_num, kind]
                        if el is not None and el.text
                    )
                    date_el = first(doc_id_el, "date")
                    if date_el is not None and date_el.text:
                        raw_d = date_el.text.strip()
                        if len(raw_d) == 8:
                            pub_date = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:]}"

            if not doc_id:
                continue
            # cut-off 날짜 이후 문헌 제외
            if pub_date != "unknown" and cutoff_date and pub_date[:10] >= cutoff_date[:10]:
                continue

            # ─ 제목 ─
            title_el = first(biblio, "invention-title")
            title = title_el.text.strip() if title_el is not None and title_el.text else "Unknown Title"

            # ─ 초록 ─
            abstract_el = first(biblio, "abstract")
            abstract = ""
            if abstract_el is not None:
                abstract = " ".join(
                    p.text.strip()
                    for p in abstract_el.iter()
                    if p.tag.endswith("p") and p.text
                )

            # ─ IPC 분류코드 ─
            ipc_codes = []
            for ipcr in biblio.iter():
                if not ipcr.tag.endswith("classification-ipcr"):
                    continue
                txt_el = first(ipcr, "text")
                if txt_el is not None and txt_el.text:
                    raw_ipc = txt_el.text.strip()
                    m = re.match(r"^([A-Z]\d+[A-Z]\s*\d+/\d+)", raw_ipc)
                    code = re.sub(r"\s+", "", m.group(1) if m else raw_ipc[:15])
                    ipc_codes.append(code)

            results.append(SearchResult(
                doc_id   = doc_id,
                title    = title,
                abstract = abstract,
                pub_date = pub_date,
                source   = "epo",
                url      = f"https://worldwide.espacenet.com/patent/search?q=pn%3D{doc_id}",
                language = "en",
                ipc_codes= ipc_codes,
            ))

        return results
