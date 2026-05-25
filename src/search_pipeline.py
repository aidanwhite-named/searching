import os
import dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from providers.gemini_search_provider import GeminiSearchProvider
from src.document_cache import DocumentCache

dotenv.load_dotenv()

_DEFAULT_DBS = ["kipris", "epo", "openalex"]
_DEFAULT_MAX_PER_DB = 200   # 기본 수집 한도 200건


@dataclass
class ClaimSearchResults:
    claim_number: int
    query: QuerySpec
    results: list = field(default_factory=list)  # list[SearchResult]


class SearchPipeline:
    def __init__(self, router: LLMRouter, config: ConfigManager):
        self.generator = QueryGenerator(router)
        self.cache = DocumentCache()

        kipris_key     = os.getenv("KIPRIS_API_KEY", "")    or config.get("search", "kipris_api_key",  default="")
        epo_key        = os.getenv("EPO_OPS_KEY", "")       or config.get("search", "epo_ops_key",     default="")
        epo_secret     = os.getenv("EPO_OPS_SECRET", "")    or config.get("search", "epo_ops_secret",  default="")
        openalex_email = os.getenv("OPENALEX_EMAIL", "")    or config.get("search", "openalex_email",  default="")

        self._gemini_search = GeminiSearchProvider(router)
        self.providers = {
            "kipris":        KiprisProvider(api_key=kipris_key),
            "epo":           EpoProvider(key=epo_key, secret=epo_secret),
            "openalex":      OpenAlexProvider(email=openalex_email),
            "gemini_search": self._gemini_search,
        }

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def run(
        self,
        patent_data: PatentData,
        claim_nodes: dict,
        target_claims: list | None = None,
        databases: list | None = None,
        max_per_db: int = _DEFAULT_MAX_PER_DB,
    ) -> list:
        dbs = databases or _DEFAULT_DBS
        cutoff = patent_data.reference_date

        # 특허번호·IPC 코드를 Gemini 검색 프로바이더에 주입
        self._gemini_search.patent_number = patent_data.patent_number
        self._gemini_search.ipc_codes = patent_data.ipc_codes

        # DB별 키 설정 상태 출력
        pn = patent_data.patent_number or "미추출"
        print("\n[search] === 외부 DB 설정 상태 ===")
        print(f"  KIPRIS       : {'✓ 키 있음' if self.providers['kipris'].api_key else '✗ API 키 없음 → skip'}")
        print(f"  EPO          : {'✓ 키 있음' if self.providers['epo'].key else '✗ API 키 없음 → skip'}")
        print(f"  OpenAlex     : ✓ (무료, 학술논문 전용)")
        print(f"  Gemini Search: ✓ Google Patents 웹 검색 (특허번호: {pn})")
        print(f"  기준일       : {cutoff}")

        if target_claims is None:
            target_claims = [n.number for n in claim_nodes.values() if n.is_independent]

        # KIPRIS/EPO/OpenAlex 중 실제로 사용 가능한 DB가 있는지 확인
        needs_query = (
            bool(self.providers["kipris"].api_key) or
            bool(self.providers["epo"].key) or
            True  # OpenAlex는 항상 가능
        )
        # 그러나 gemini_search만 있으면 쿼리 생성은 낭비 → skip
        only_gemini = (
            not self.providers["kipris"].api_key and
            not self.providers["epo"].key
        )

        all_results = []
        for num in target_claims:
            node = claim_nodes.get(num)
            if not node:
                print(f"[search] Claim {num} not found — 건너뜀.")
                continue

            # 청구항 텍스트를 1500자로 제한 (Gemini CLI 프롬프트 과부하 방지)
            claim_text = node.text[:1500]

            if only_gemini:
                # KIPRIS/EPO 키 없음 → 쿼리 생성 skip, gemini_search + openalex만 사용
                print(f"\n[search] 청구항 {num} — Gemini 웹 검색 + OpenAlex 직접 실행 (쿼리 생성 생략)")
                query = QuerySpec(claim_number=num)
            else:
                print(f"\n[search] 청구항 {num} 쿼리 생성 중...")
                query = self.generator.generate(num, claim_text, cutoff)
                print(f"  Keywords : {query.keywords}")
                print(f"  CPC Codes: {query.cpc_codes}")
                print(f"  Boolean  : {query.boolean_query[:80]}...")

            found = self._search_parallel(query, claim_text, dbs, cutoff, max_per_db)

            all_results.append(ClaimSearchResults(
                claim_number=num,
                query=query,
                results=found,
            ))

        return all_results

    # ── 병렬 검색 ─────────────────────────────────────────────────────────────

    def _search_parallel(
        self,
        query: QuerySpec,
        claim_text: str,
        dbs: list,
        cutoff: str,
        max_per_db: int,
    ) -> list[SearchResult]:
        """각 DB를 ThreadPoolExecutor로 동시에 쿼리.
        gemini_search는 claim_text 전체를 사용, 나머지는 boolean query 사용."""

        def _fetch(db: str) -> tuple[str, list[SearchResult]]:
            provider = self.providers.get(db)
            if not provider:
                print(f"  [{db}] 알 수 없는 프로바이더 — 건너뜀.")
                return db, []

            # gemini_search는 청구항 원문 전체를 쿼리로 사용
            if db == "gemini_search":
                q_str = claim_text
            else:
                q_str = self._build_query_str(db, query)

            try:
                hits = provider.search(q_str, cutoff, max_per_db)
            except Exception as e:
                print(f"  [{db}] 검색 오류: {e}")
                hits = []
            return db, hits

        # gemini_search는 웹 검색으로 오래 걸리므로 별도 처리 (다른 DB와 병렬)
        all_dbs = list(dbs) + (["gemini_search"] if "gemini_search" not in dbs else [])

        found: list[SearchResult] = []
        with ThreadPoolExecutor(max_workers=len(all_dbs)) as executor:
            futures = {executor.submit(_fetch, db): db for db in all_dbs}
            for future in as_completed(futures):
                db, hits = future.result()
                for hit in hits:
                    hit = self.cache.fetch_and_store(hit)
                    found.append(hit)

        return found

    # ── 프로바이더별 쿼리 포맷 ────────────────────────────────────────────────

    @staticmethod
    def _build_query_str(db: str, query: QuerySpec) -> str:
        if db == "kipris":
            return query.boolean_query or " AND ".join(query.keywords)
        if db == "epo":
            # EPO CQL: boolean_query 우선, 없으면 키워드 AND 결합
            return query.boolean_query or " AND ".join(query.keywords)
        # openalex: 단순 키워드 스트링
        return " ".join(query.keywords)

    # ── 요약 출력 ─────────────────────────────────────────────────────────────

    def summary(self, all_results: list) -> str:
        lines = ["\n=== 외부 DB 검색 결과 ==="]
        for cr in all_results:
            lines.append(f"\n  청구항 {cr.claim_number} — 총 {len(cr.results)}건")
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
