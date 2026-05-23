import os
import json
import urllib.parse
import urllib.request
from providers.base_provider import BaseProvider, SearchResult

_OPENALEX_BASE = "https://api.openalex.org/works"

class OpenAlexProvider(BaseProvider):
    def __init__(self, email: str = None):
        self.email = email or os.getenv("OPENALEX_EMAIL", "")

    def search(self, query: str, cutoff_date: str, limit: int = 10) -> list[SearchResult]:
        if not query:
            return []

        params = {
            "search": query,
            "per_page": limit,
        }
        
        if self.email:
            params["mailto"] = self.email
            
        url = f"{_OPENALEX_BASE}?{urllib.parse.urlencode(params)}"
        
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PatentSearchDashboard/2.0 (mailto:agent@antigravity.ai)"}
        )
        
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            return self._parse_json(data, cutoff_date)
        except Exception as e:
            print(f"[openalex] Search failed: {e}")
            return []

    def _parse_json(self, data: dict, cutoff_date: str) -> list[SearchResult]:
        results = []
        for work in data.get("results", []):
            pub_date = work.get("publication_date") or "unknown"
            if pub_date and cutoff_date and pub_date[:10] >= cutoff_date[:10]:
                continue

            full_id = work.get("id", "")
            doc_id = full_id.split("/")[-1] if full_id else ""
            if not doc_id:
                continue

            title = work.get("title") or "Unknown Title"
            
            # Reconstruct abstract from inverted index
            inverted_index = work.get("abstract_inverted_index")
            abstract = self._reconstruct_abstract(inverted_index)

            # Get PDF or landing page URL
            url = work.get("doi") or ""
            if not url:
                loc = work.get("primary_location") or {}
                url = loc.get("landing_page_url") or work.get("pdf_url") or ""

            results.append(SearchResult(
                doc_id=doc_id,
                title=title,
                abstract=abstract,
                pub_date=pub_date,
                source="openalex",
                url=url,
                language="en"  # OpenAlex concepts/papers are mostly English
            ))
        return results

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict) -> str:
        if not inverted_index:
            return ""
        try:
            word_map = {}
            max_idx = 0
            for word, indices in inverted_index.items():
                for idx in indices:
                    word_map[idx] = word
                    if idx > max_idx:
                        max_idx = idx
            words = []
            for i in range(max_idx + 1):
                words.append(word_map.get(i, ""))
            return " ".join(words).strip()
        except Exception:
            return ""
