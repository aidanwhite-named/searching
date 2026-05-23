import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from providers.base_provider import BaseProvider, SearchResult

_KIPRIS_BASE = "http://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getWordSearch"

class KiprisProvider(BaseProvider):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("KIPRIS_API_KEY", "")

    def search(self, query: str, cutoff_date: str, limit: int = 10) -> list[SearchResult]:
        if not self.api_key:
            print("[kipris] KIPRIS API Key not configured. Skipping.")
            return []
            
        if not query:
            return []
            
        params = urllib.parse.urlencode({
            "ServiceKey": self.api_key,
            "searchWord": query,
            "pageNo": 1,
            "numOfRows": limit,
        })
        url = f"{_KIPRIS_BASE}?{params}"
        
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "PatentSearch/2.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_xml = resp.read().decode("utf-8", errors="replace")
            return self._parse_xml(raw_xml, cutoff_date)
        except Exception as e:
            print(f"[kipris] Search failed: {e}")
            return []

    def _parse_xml(self, raw: str, cutoff_date: str) -> list[SearchResult]:
        results = []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"[kipris] XML Parsing Error: {e}")
            return []
            
        for item in root.iter("item"):
            t = lambda tag: (item.findtext(tag) or "").strip()
            
            pub_date = self._normalize_date(t("openDate") or t("applicationDate"))
            if pub_date and cutoff_date and pub_date[:10] >= cutoff_date[:10]:
                continue
                
            doc_id = t("applicationNumber") or t("registrationNumber")
            if not doc_id:
                continue
                
            ipc_raw = t("ipcNumber")
            ipc_codes = [code.strip() for code in ipc_raw.split(",") if code.strip()] if ipc_raw else []
            
            results.append(SearchResult(
                doc_id=doc_id,
                title=t("inventionTitle"),
                abstract=t("astrtCont") or t("abstract") or "",
                pub_date=pub_date or "unknown",
                source="kipris",
                url=f"https://www.kipris.or.kr/khome/main.jsp?method=getLitPatent&isPatent=TRUE&docId={doc_id}",
                language="ko",
                ipc_codes=ipc_codes
            ))
        return results

    @staticmethod
    def _normalize_date(raw: str) -> str:
        raw = re.sub(r"\D", "", raw)
        if len(raw) == 8:
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        return raw
