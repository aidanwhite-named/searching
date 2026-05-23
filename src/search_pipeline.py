"""
1차 검색 파이프라인: 쿼리 생성 → DB 검색 → 문서 캐시 저장.
"""

from dataclasses import dataclass, field
from src.config_manager import ConfigManager
from src.llm_router import LLMRouter
from src.claims_parser import ClaimNode
from src.patent_preprocessor import PatentData
from src.query_generator import QueryGenerator, QuerySpec
from src.search_clients import SearchResult, build_clients
from src.document_cache import DocumentCache


_DEFAULT_DBS = ["kipris", "semantic_scholar", "uspto"]


@dataclass
class ClaimSearchResults:
    claim_number: int
    query: QuerySpec
    results: list = field(default_factory=list)  # list[SearchResult]


class SearchPipeline:
    def __init__(self, router: LLMRouter, config: ConfigManager):
        self.generator = QueryGenerator(router)
        self.clients = build_clients(config)
        self.cache = DocumentCache()

    def run(
        self,
        patent_data: PatentData,
        claim_nodes: dict,
        target_claims: list | None = None,
        databases: list | None = None,
        max_per_db: int = 10,
    ) -> list:
        """
        target_claims: None이면 독립항 전체
        databases: None이면 _DEFAULT_DBS
        반환: list[ClaimSearchResults]
        """
        dbs = databases or _DEFAULT_DBS
        cutoff = patent_data.reference_date

        if target_claims is None:
            target_claims = [n.number for n in claim_nodes.values() if n.is_independent]

        all_results = []
        for num in target_claims:
            node = claim_nodes.get(num)
            if not node:
                print(f"[search] 청구항 {num} 없음 — skip")
                continue

            print(f"\n[search] 청구항 {num} 쿼리 생성 중...")
            query = self.generator.generate(num, node.text, cutoff)
            print(f"  키워드: {query.keywords}")
            print(f"  CPC: {query.cpc_codes}")
            print(f"  Boolean: {query.boolean_query[:80]}...")

            found: list[SearchResult] = []
            for db in dbs:
                client = self.clients.get(db)
                if not client:
                    print(f"[search] 알 수 없는 DB: {db} — skip")
                    continue
                print(f"  [{db}] 검색 중...", end=" ", flush=True)
                hits = client.search(query, cutoff, max_per_db)
                print(f"{len(hits)}건 발견")
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
        """CLI 출력용 요약 문자열."""
        lines = ["\n=== 1차 검색 결과 요약 ==="]
        for cr in all_results:
            lines.append(f"\n  청구항 {cr.claim_number} — {len(cr.results)}건")
            lines.append(f"  쿼리: {cr.query.boolean_query[:70]}...")
            by_src: dict[str, int] = {}
            for r in cr.results:
                by_src[r.source] = by_src.get(r.source, 0) + 1
            for src, cnt in by_src.items():
                lines.append(f"    · {src}: {cnt}건")
            if cr.results:
                lines.append("  상위 3건:")
                for r in cr.results[:3]:
                    lines.append(f"    [{r.pub_date}] {r.title[:60]}")
        return "\n".join(lines)
