"""
특허 선행기술조사 CLI 시스템
사용법: python main.py <command> [options]
"""

import argparse
import sys
import io

# Windows 터미널 UTF-8 출력 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import json as _json

from src.config_manager import ConfigManager
from src.llm_router import LLMRouter
from src.patent_preprocessor import PatentPreprocessor
from src.claims_parser import ClaimsParser
from src.search_pipeline import SearchPipeline
from src.rag_pipeline import RAGPipeline
from src.document_cache import DocumentCache
from src.matcher import Matcher
from src.hallucination_checker import HallucinationChecker
from src.output_formatter import OutputFormatter


def cmd_config(args):
    cfg = ConfigManager()
    if args.setup:
        cfg.setup_wizard()
    else:
        cfg.show()


def cmd_test(args):
    cfg = ConfigManager()
    cfg.show()
    router = LLMRouter(cfg)
    print(f"[test] 에이전트: {router.agent} / 모드: {router.mode} / 모델: {router.model}")
    success = router.test_connection()
    sys.exit(0 if success else 1)


def cmd_parse(args):
    preprocessor = PatentPreprocessor()
    parser = ClaimsParser()

    print(f"[parse] PDF 변환 중: {args.pdf}")
    data = preprocessor.process(args.pdf)

    nodes = parser.parse(data.claims_markdown)
    independent = [n for n in nodes.values() if n.is_independent]

    print("\n=== 특허 파싱 결과 ===")
    print(f"  발명 명칭  : {data.title or '(추출 실패)'}")
    print(f"  기준일     : {data.reference_date} ({data.date_type})")
    print(f"  청구항 수  : {len(nodes)}개 (독립항 {len(independent)}개, 종속항 {len(nodes)-len(independent)}개)")
    print()
    print("  의존성 트리:")
    print(parser.render_tree(nodes))

    if args.claims:
        print("\n  --- 청구범위 원문 ---")
        print(data.claims_markdown[:2000])
        if len(data.claims_markdown) > 2000:
            print(f"  ... (이하 생략, 총 {len(data.claims_markdown)}자)")


def cmd_search(args):
    cfg = ConfigManager()
    router = LLMRouter(cfg)
    preprocessor = PatentPreprocessor()
    claims_parser = ClaimsParser()
    pipeline = SearchPipeline(router, cfg)

    # PDF 파싱
    print(f"[search] PDF 변환 중: {args.pdf}")
    data = preprocessor.process(args.pdf)
    nodes = claims_parser.parse(data.claims_markdown)
    print(f"[search] 기준일: {data.reference_date} ({data.date_type}), 청구항: {len(nodes)}개")

    # 대상 청구항 결정
    target = None
    if args.claims:
        target = [int(c.strip()) for c in args.claims.split(",") if c.strip().isdigit()]

    # DB 목록
    dbs = [d.strip() for d in args.db.split(",")] if args.db else None

    # 검색 실행
    results = pipeline.run(
        patent_data=data,
        claim_nodes=nodes,
        target_claims=target,
        databases=dbs,
        max_per_db=args.max,
    )

    # 결과 출력
    print(pipeline.summary(results))

    # 파일 저장
    if args.out:
        def _to_dict(cr):
            return {
                "claim_number": cr.claim_number,
                "query": {
                    "keywords": cr.query.keywords,
                    "cpc_codes": cr.query.cpc_codes,
                    "boolean_query": cr.query.boolean_query,
                },
                "results": [
                    {
                        "doc_id": r.doc_id,
                        "title": r.title,
                        "abstract": r.abstract,
                        "pub_date": r.pub_date,
                        "source": r.source,
                        "url": r.url,
                        "local_path": r.local_path,
                    }
                    for r in cr.results
                ],
            }
        with open(args.out, "w", encoding="utf-8") as f:
            _json.dump([_to_dict(cr) for cr in results], f, ensure_ascii=False, indent=2)
        print(f"\n[search] 결과 저장: {args.out}")


def cmd_rag(args):
    cfg = ConfigManager()
    router = LLMRouter(cfg)
    preprocessor = PatentPreprocessor()
    claims_parser_obj = ClaimsParser()
    cache = DocumentCache()
    rag = RAGPipeline(cfg)

    # PDF 파싱
    print(f"[rag] PDF 변환 중: {args.pdf}")
    data = preprocessor.process(args.pdf)
    nodes = claims_parser_obj.parse(data.claims_markdown)
    print(f"[rag] 청구항: {len(nodes)}개, 기준일: {data.reference_date}")

    # Phase 3 결과 로드 또는 검색 실행
    if args.results:
        try:
            with open(args.results, "r", encoding="utf-8") as f:
                raw = _json.load(f)
            # ClaimSearchResults 재구성
            from src.search_pipeline import ClaimSearchResults
            from src.query_generator import QuerySpec
            from providers.base_provider import SearchResult
            search_results = []
            for item in raw:
                q = item["query"]
                rs = [SearchResult(
                    doc_id=r["doc_id"], title=r["title"], abstract=r["abstract"],
                    pub_date=r["pub_date"], source=r["source"], url=r.get("url",""),
                    local_path=r.get("local_path",""),
                ) for r in item["results"]]
                search_results.append(ClaimSearchResults(
                    claim_number=item["claim_number"],
                    query=QuerySpec(claim_number=item["claim_number"],
                                   keywords=q["keywords"], cpc_codes=q["cpc_codes"],
                                   boolean_query=q["boolean_query"]),
                    results=rs,
                ))
            print(f"[rag] Phase 3 결과 로드: {args.results}")
        except Exception as e:
            print(f"[rag] 결과 파일 로드 실패 ({e}), Phase 3 검색 실행...")
            search_results = None
    else:
        search_results = None

    if search_results is None:
        pipeline = SearchPipeline(router, cfg)
        target = None
        if args.claims:
            target = [int(c.strip()) for c in args.claims.split(",") if c.strip().isdigit()]
        search_results = pipeline.run(
            patent_data=data,
            claim_nodes=nodes,
            target_claims=target,
            max_per_db=10,
        )

    # RAG 인덱스 구축
    n_chunks = rag.build_index(
        search_results=search_results,
        cache=cache,
        force_rebuild=args.rebuild,
    )
    if n_chunks == 0:
        print("[rag] 인덱싱할 문서가 없습니다.")
        return

    # 검색 대상 청구항
    target_claims = None
    if args.claims:
        target_claims = [int(c.strip()) for c in args.claims.split(",") if c.strip().isdigit()]
    if target_claims is None:
        target_claims = [n.number for n in nodes.values() if n.is_independent]

    rag_results = rag.search(nodes, target_claims, top_k=args.top_k)
    print(rag.summary(rag_results))

    if args.out:
        def _chunk_to_dict(cr):
            return {
                "claim_number": cr.claim_number,
                "top_chunks": [
                    {
                        "score": r.score,
                        "doc_id": r.chunk.doc_id,
                        "source": r.chunk.source,
                        "pub_date": r.chunk.pub_date,
                        "title": r.chunk.title,
                        "text": r.chunk.text,
                    }
                    for r in cr.top_chunks
                ],
            }
        with open(args.out, "w", encoding="utf-8") as f:
            _json.dump([_chunk_to_dict(cr) for cr in rag_results], f,
                       ensure_ascii=False, indent=2)
        print(f"[rag] 결과 저장: {args.out}")


def cmd_match(args):
    cfg = ConfigManager()
    router = LLMRouter(cfg)
    preprocessor = PatentPreprocessor()
    claims_parser_obj = ClaimsParser()
    cache = DocumentCache()
    rag = RAGPipeline(cfg)
    matcher = Matcher(
        tolerance_band=args.tolerance,
        max_refs=args.max_refs,
    )
    checker = HallucinationChecker()
    formatter = OutputFormatter()

    # ── 1. PDF 파싱 ───────────────────────────────────────────────────────────
    print(f"[match] PDF 변환 중: {args.pdf}")
    data = preprocessor.process(args.pdf)
    nodes = claims_parser_obj.parse(data.claims_markdown)
    print(f"[match] 청구항: {len(nodes)}개, 기준일: {data.reference_date}")

    # ── 2. RAG 결과 로드 또는 전체 파이프라인 실행 ──────────────────────────
    if args.rag_results:
        try:
            with open(args.rag_results, "r", encoding="utf-8") as f:
                raw = _json.load(f)
            from src.rag_pipeline import RAGClaimResult, ChunkResult
            from src.chunker import Chunk
            rag_results = []
            for item in raw:
                chunks = [
                    ChunkResult(
                        chunk=Chunk(
                            text=c["text"], doc_id=c["doc_id"], source=c["source"],
                            pub_date=c["pub_date"], title=c["title"], chunk_idx=0,
                        ),
                        score=c["score"],
                    )
                    for c in item["top_chunks"]
                ]
                rag_results.append(RAGClaimResult(claim_number=item["claim_number"], top_chunks=chunks))
            print(f"[match] RAG 결과 로드: {args.rag_results}")
        except Exception as e:
            print(f"[match] RAG 결과 로드 실패 ({e}), 전체 파이프라인 실행...")
            rag_results = None
    else:
        rag_results = None

    if rag_results is None:
        pipeline = SearchPipeline(router, cfg)
        target = None
        if args.claims:
            target = [int(c.strip()) for c in args.claims.split(",") if c.strip().isdigit()]
        search_results = pipeline.run(
            patent_data=data, claim_nodes=nodes,
            target_claims=target, max_per_db=10,
        )
        n_chunks = rag.build_index(search_results, cache)
        if n_chunks == 0:
            print("[match] 인덱싱할 문서가 없습니다. 종료.")
            return
        # 전체 청구항 검색: 종속항 covers_claims가 있어야 재사용 로직이 작동함
        all_claim_nums = sorted(nodes.keys())
        rag_results = rag.search(nodes, all_claim_nums, top_k=10)

    # ── 3. 매칭 알고리즘 ─────────────────────────────────────────────────────
    print(f"\n[match] 매칭 알고리즘 실행 (tolerance={args.tolerance}, max_refs={args.max_refs})...")
    claim_matches = matcher.match(nodes, rag_results)

    # ── 4. 할루시네이션 검증 (--no-llm 아닐 때) ────────────────────────────
    if not args.no_llm:
        print("[match] LLM 단락 추출 & 검증 중...")
        for cm in claim_matches:
            refs_to_check = ([cm.primary_ref] if cm.primary_ref else []) + cm.secondary_refs
            for dm in refs_to_check:
                if not dm.matched_paragraph:
                    claim_node = nodes.get(cm.claim_number)
                    if claim_node:
                        print(f"  청구항 {cm.claim_number} ← {dm.doc_id} 검증 중...")
                        para, verified = checker.find_and_verify(
                            cm.claim_number, claim_node.text, dm, router, cache
                        )
                        dm.matched_paragraph = para
                        dm.paragraph_verified = verified

    # ── 5. 출력 ──────────────────────────────────────────────────────────────
    formatter.print_summary(data, claim_matches)

    fmt = args.format or cfg.get("output", "format", default="json")
    out_path = args.out
    if out_path:
        if fmt == "csv":
            content = formatter.to_csv(claim_matches)
        else:
            content = formatter.to_json(data, claim_matches, nodes)
        formatter.save(content, out_path)
        print(f"\n[match] 결과 저장: {out_path} ({fmt})")
    else:
        # stdout 출력
        if fmt == "csv":
            print(formatter.to_csv(claim_matches))
        else:
            print(formatter.to_json(data, claim_matches, nodes))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="patent-search",
        description="특허 선행기술조사 및 거절논리 매칭 CLI 시스템",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # config
    p_config = sub.add_parser("config", help="설정 확인 및 변경")
    p_config.add_argument("--setup", action="store_true", help="대화형 설정 마법사 실행")
    p_config.set_defaults(func=cmd_config)

    # test
    p_test = sub.add_parser("test", help="LLM 연결 테스트")
    p_test.set_defaults(func=cmd_test)

    # parse
    p_parse = sub.add_parser("parse", help="특허 PDF 파싱 (기준일 + 청구항 의존성 트리)")
    p_parse.add_argument("pdf", help="특허 PDF 파일 경로")
    p_parse.add_argument("--claims", action="store_true", help="청구범위 원문도 출력")
    p_parse.set_defaults(func=cmd_parse)

    # search
    p_search = sub.add_parser("search", help="1차 외부 DB 선행기술 검색")
    p_search.add_argument("pdf", help="특허 PDF 파일 경로")
    p_search.add_argument("--claims", dest="claims", default=None,
                          help="검색 대상 청구항 번호 (예: 1,3). 기본: 독립항 전체")
    p_search.add_argument("--db", default=None,
                          help="사용할 DB (예: kipris,semantic_scholar,uspto). 기본: 전체")
    p_search.add_argument("--max", type=int, default=10,
                          help="DB당 최대 결과 수 (기본: 10)")
    p_search.add_argument("--out", default=None,
                          help="결과 JSON 저장 경로")
    p_search.set_defaults(func=cmd_search)

    # rag
    p_rag = sub.add_parser("rag", help="2차 로컬 RAG 검색 (청크 유사도)")
    p_rag.add_argument("pdf", help="특허 PDF 파일 경로")
    p_rag.add_argument("--results", default=None,
                       help="Phase 3 결과 JSON 경로 (없으면 자동 검색)")
    p_rag.add_argument("--claims", default=None,
                       help="검색 대상 청구항 번호 (예: 1,3). 기본: 독립항")
    p_rag.add_argument("--top-k", type=int, default=5,
                       help="청구항당 반환할 상위 청크 수 (기본: 5)")
    p_rag.add_argument("--rebuild", action="store_true",
                       help="기존 벡터 인덱스 무시하고 재구축")
    p_rag.add_argument("--out", default=None,
                       help="결과 JSON 저장 경로")
    p_rag.set_defaults(func=cmd_rag)

    # match (최종 명령)
    p_match = sub.add_parser("match", help="선행기술 매칭 + 할루시네이션 검증 + 결과 출력")
    p_match.add_argument("pdf", help="특허 PDF 파일 경로")
    p_match.add_argument("--rag-results", default=None, dest="rag_results",
                         help="Phase 4 RAG 결과 JSON 경로 (없으면 전체 파이프라인 실행)")
    p_match.add_argument("--claims", default=None,
                         help="대상 청구항 번호 (예: 1,3). 기본: 전체")
    p_match.add_argument("--tolerance", type=float, default=0.05,
                         help="허용 오차 밴드 (기본: 0.05 = 5%%p)")
    p_match.add_argument("--max-refs", type=int, default=2, dest="max_refs",
                         help="최대 인용 문헌 수 (기본: 2)")
    p_match.add_argument("--format", choices=["json", "csv"], default=None,
                         help="출력 형식 (기본: config의 output.format)")
    p_match.add_argument("--out", default=None,
                         help="결과 저장 경로 (기본: stdout)")
    p_match.add_argument("--no-llm", action="store_true",
                         help="LLM 단락 추출 생략 (빠른 모드)")
    p_match.set_defaults(func=cmd_match)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
