import logging
import os
import json
import urllib.parse
import urllib.request
from providers.base_provider import BaseProvider, SearchResult

logger = logging.getLogger(__name__)

_OPENALEX_BASE = "https://api.openalex.org/works"


class OpenAlexProvider(BaseProvider):
    def __init__(self, email: str = None):
        self.email = email or os.getenv("OPENALEX_EMAIL", "")

    def search(self, query: str, cutoff_date: str, limit: int = 10) -> list[SearchResult]:
        if not query:
            return []

        params = {"search": query, "per_page": limit}
        if self.email:
            params["mailto"] = self.email

        url = f"{_OPENALEX_BASE}?{urllib.parse.urlencode(params)}"
        logger.debug("OpenAlex 요청: %s...", query[:60])

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "PatentSearchDashboard/2.0 (mailto:agent@antigravity.ai)"}
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            results = self._parse_json(data, cutoff_date)
            logger.info("OpenAlex 결과: %d건 (cutoff=%s)", len(results), cutoff_date)
            return results
        except Exception as e:
            logger.error("OpenAlex 검색 실패: %s", e)
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

            title = work.get("display_name") or work.get("title") or "Unknown Title"

            abstract_inverted = work.get("abstract_inverted_index")
            abstract = ""
            if abstract_inverted:
                try:
                    words = {pos: word for word, positions in abstract_inverted.items() for pos in positions}
                    abstract = " ".join(words[i] for i in sorted(words.keys()))
                except Exception:
                    pass

            doi = work.get("doi") or ""
            url = doi if doi.startswith("http") else (f"https://doi.org/{doi}" if doi else full_id)

            results.append(SearchResult(
                doc_id=doc_id,
                title=title,
                abstract=abstract,
                pub_date=pub_date,
                source="openalex",
                url=url,
                language="en",
            ))
        return results
