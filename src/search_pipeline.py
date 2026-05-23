import os
import dotenv
from dataclasses import dataclass, field
from src.config_manager import ConfigManager
from src.llm_router import LLMRouter
from src.claims_parser import ClaimNode
from src.patent_preprocessor import PatentData
from src.query_generator import QueryGenerator, QuerySpec
from providers.base_provider import SearchResult
from providers.kipris_provider import KiprisProvider
from providers.epo_provider import EpoProvider
from providers.openalex_provider import OpenAlexProvider
from src.document_cache import DocumentCache

# Load environment variables from .env if present
dotenv.load_dotenv()

_DEFAULT_DBS = ["kipris", "epo", "openalex"]


@dataclass
class ClaimSearchResults:
    claim_number: int
    query: QuerySpec
    results: list = field(default_factory=list)  # list[SearchResult]


class SearchPipeline:
    def __init__(self, router: LLMRouter, config: ConfigManager):
        self.generator = QueryGenerator(router)
        self.cache = DocumentCache()
        
        # Load API keys from environment or fallback to config
        kipris_key = os.getenv("KIPRIS_API_KEY", "") or config.get("search", "kipris_api_key", default="")
        epo_key = os.getenv("EPO_OPS_KEY", "") or config.get("search", "epo_ops_key", default="")
        epo_secret = os.getenv("EPO_OPS_SECRET", "") or config.get("search", "epo_ops_secret", default="")
        openalex_email = os.getenv("OPENALEX_EMAIL", "") or config.get("search", "openalex_email", default="")
        
        self.providers = {
            "kipris": KiprisProvider(api_key=kipris_key),
            "epo": EpoProvider(key=epo_key, secret=epo_secret),
            "openalex": OpenAlexProvider(email=openalex_email)
        }

    def run(
        self,
        patent_data: PatentData,
        claim_nodes: dict,
        target_claims: list | None = None,
        databases: list | None = None,
        max_per_db: int = 10,
    ) -> list:
        """
        Run search query generation and retrieve results from external databases.
        """
        dbs = databases or _DEFAULT_DBS
        cutoff = patent_data.reference_date

        if target_claims is None:
            target_claims = [n.number for n in claim_nodes.values() if n.is_independent]

        all_results = []
        for num in target_claims:
            node = claim_nodes.get(num)
            if not node:
                print(f"[search] Claim {num} not found — skipping.")
                continue

            print(f"\n[search] Generating query for Claim {num}...")
            query = self.generator.generate(num, node.text, cutoff)
            print(f"  Keywords: {query.keywords}")
            print(f"  CPC Codes: {query.cpc_codes}")
            print(f"  Boolean Query: {query.boolean_query[:80]}...")

            found: list[SearchResult] = []
            for db in dbs:
                provider = self.providers.get(db)
                if not provider:
                    print(f"[search] Unknown provider: {db} — skipping.")
                    continue
                    
                print(f"  [{db}] Querying database...", end=" ", flush=True)
                
                # Format search query string depending on provider characteristics
                if db == "kipris":
                    # KIPRIS works best with boolean statements
                    q_str = query.boolean_query or " AND ".join(query.keywords)
                elif db == "epo":
                    # EPO Published-data searches using CQL
                    q_str = " AND ".join(query.keywords)
                else:
                    # OpenAlex handles simple keyword strings well
                    q_str = " ".join(query.keywords)
                    
                hits = provider.search(q_str, cutoff, max_per_db)
                print(f"{len(hits)} hits retrieved")
                
                for hit in hits:
                    hit = self.cache.fetch_and_store(hit)
                    found.append(hit)

            all_results.append(ClaimSearchResults(
                claim_number=num,
                query=query,
                results=found,
            ))

        return all_results

    def summary(self, all_results: list) -> str:
        """Generate a summary of the search results for CLI feedback."""
        lines = ["\n=== External search results ==="]
        for cr in all_results:
            lines.append(f"\n  Claim {cr.claim_number} — {len(cr.results)} documents")
            lines.append(f"  Query: {cr.query.boolean_query[:70]}...")
            by_src: dict[str, int] = {}
            for r in cr.results:
                by_src[r.source] = by_src.get(r.source, 0) + 1
            for src, cnt in by_src.items():
                lines.append(f"    · {src}: {cnt} docs")
            if cr.results:
                lines.append("  Top 3 hits:")
                for r in cr.results[:3]:
                    lines.append(f"    [{r.pub_date}] {r.title[:60]}")
        return "\n".join(lines)
