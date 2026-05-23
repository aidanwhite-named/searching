from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class SearchResult:
    doc_id: str
    title: str
    abstract: str
    pub_date: str          # "YYYY-MM-DD"
    source: str            # "kipris" | "epo" | "openalex"
    url: str = ""
    local_path: str = ""
    language: str = "en"
    ipc_codes: list[str] = field(default_factory=list)
    cpc_codes: list[str] = field(default_factory=list)

class BaseProvider(ABC):
    @abstractmethod
    def search(self, query: str, cutoff_date: str, limit: int = 10) -> list[SearchResult]:
        """Perform search and return list of SearchResults up to cutoff_date."""
        pass
