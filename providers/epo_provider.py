import os
import re
import base64
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from providers.base_provider import BaseProvider, SearchResult

_EPO_AUTH_URL = "https://ops.epo.org/3.2/auth/accesstoken"
_EPO_SEARCH_URL = "https://ops.epo.org/3.2/rest-services/published-data/search/biblio"

class EpoProvider(BaseProvider):
    def __init__(self, key: str = None, secret: str = None):
        self.key = key or os.getenv("EPO_OPS_KEY", "")
        self.secret = secret or os.getenv("EPO_OPS_SECRET", "")
        self._token = None
        self._token_expires = 0

    def _get_token(self) -> str:
        import time
        if self._token and time.time() < self._token_expires:
            return self._token

        if not self.key or not self.secret:
            return ""

        auth_str = f"{self.key}:{self.secret}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        
        req = urllib.request.Request(
            _EPO_AUTH_URL,
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {b64_auth}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                self._token = data["access_token"]
                # Set expiry slightly earlier than returned expires_in
                self._token_expires = time.time() + int(data.get("expires_in", 3500)) - 60
                return self._token
        except Exception as e:
            print(f"[epo] Authentication failed: {e}")
            return ""

    def search(self, query: str, cutoff_date: str, limit: int = 10) -> list[SearchResult]:
        token = self._get_token()
        if not token:
            print("[epo] EPO credentials not configured or auth failed. Skipping.")
            return []

        if not query:
            return []

        # Convert query to EPO CQL format. E.g. txt = "query"
        # If query has complex boolean, wrap it, otherwise format
        clean_q = query.replace('"', '')
        cql_query = f'txt="{clean_q}"'
        
        params = urllib.parse.urlencode({
            "q": cql_query,
            "range": f"1-{limit}"
        })
        url = f"{_EPO_SEARCH_URL}?{params}"
        
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/xml"
            }
        )
        
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_xml = resp.read().decode("utf-8", errors="replace")
            return self._parse_xml(raw_xml, cutoff_date)
        except Exception as e:
            print(f"[epo] Search failed: {e}")
            return []

    def _parse_xml(self, raw: str, cutoff_date: str) -> list[SearchResult]:
        results = []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            print(f"[epo] XML Parsing Error: {e}")
            return []

        # Utility helpers for namespace-agnostic search
        def find_first_by_suffix(element, suffix):
            for el in element.iter():
                if el.tag.endswith(suffix):
                    return el
            return None

        # Each result resides in a "bibliographic-data" (or "search-result" / "document-id")
        # In EPO OPS, search-result items are wrapped inside <ops:search-result>
        # Let's extract each bibliographic data record
        for entry in root.iter():
            if not entry.tag.endswith("search-result"):
                continue
                
            biblio = find_first_by_suffix(entry, "bibliographic-data")
            if biblio is None:
                continue

            # Extract publication reference
            pub_ref = find_first_by_suffix(biblio, "publication-reference")
            doc_id = ""
            pub_date = "unknown"
            
            if pub_ref is not None:
                doc_id_el = find_first_by_suffix(pub_ref, "document-id")
                if doc_id_el is not None:
                    country = find_first_by_suffix(doc_id_el, "country")
                    doc_num = find_first_by_suffix(doc_id_el, "doc-number")
                    kind = find_first_by_suffix(doc_id_el, "kind")
                    
                    c_text = country.text.strip() if country is not None and country.text else ""
                    dn_text = doc_num.text.strip() if doc_num is not None and doc_num.text else ""
                    k_text = kind.text.strip() if kind is not None and kind.text else ""
                    doc_id = f"{c_text}{dn_text}{k_text}"
                    
                    date_el = find_first_by_suffix(doc_id_el, "date")
                    if date_el is not None and date_el.text:
                        raw_date = date_el.text.strip()
                        if len(raw_date) == 8:
                            pub_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                            
            if not doc_id:
                continue

            if pub_date and cutoff_date and pub_date[:10] >= cutoff_date[:10]:
                continue

            # Extract title
            title_el = find_first_by_suffix(biblio, "invention-title")
            title = title_el.text.strip() if title_el is not None and title_el.text else "Unknown Title"

            # Extract abstract
            abstract_el = find_first_by_suffix(biblio, "abstract")
            abstract_parts = []
            if abstract_el is not None:
                for p in abstract_el.iter():
                    if p.tag.endswith("p") and p.text:
                        abstract_parts.append(p.text.strip())
            abstract = " ".join(abstract_parts) if abstract_parts else ""

            # Extract IPC classification
            ipc_codes = []
            for ipcr in biblio.iter():
                if ipcr.tag.endswith("classification-ipcr"):
                    txt_el = find_first_by_suffix(ipcr, "text")
                    if txt_el is not None and txt_el.text:
                        # Clean up formatting, e.g. "H01M  10/42" -> "H01M10/42"
                        raw_ipc = txt_el.text.strip()
                        # Extract first part
                        m = re.match(r"^([A-Z]\d+[A-Z]\s*\d+/\d+)", raw_ipc)
                        if m:
                            ipc_codes.append(re.sub(r"\s+", "", m.group(1)))
                        else:
                            ipc_codes.append(re.sub(r"\s+", "", raw_ipc[:15]))

            results.append(SearchResult(
                doc_id=doc_id,
                title=title,
                abstract=abstract,
                pub_date=pub_date,
                source="epo",
                url=f"https://patents.google.com/patent/{doc_id}",
                language="en", # Default EPO metadata language
                ipc_codes=ipc_codes
            ))
            
        return results
