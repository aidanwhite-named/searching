"""
핵심 매칭 알고리즘.
허용 오차 밴드 + Set Cover(W1×score + W2×coverage) + 재사용 우선 원칙 구현.
"""

from dataclasses import dataclass, field
from typing import Optional
from src.claims_parser import ClaimNode
from src.rag_pipeline import RAGClaimResult
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CandidateDoc:
    doc_id: str
    source: str
    title: str
    pub_date: str
    score: float            # 청크 최고 유사도
    best_chunk: str         # 가장 유사한 청크 텍스트
    covers_claims: list = field(default_factory=list)  # top-k에 등장한 청구항 번호

    @property
    def uid(self) -> str:
        return f"{self.source}_{self.doc_id}"


@dataclass
class DocumentMatch:
    doc_id: str
    source: str
    title: str
    pub_date: str
    similarity_score: float
    covers_claims: list = field(default_factory=list)
    matched_paragraph: str = ""
    paragraph_verified: bool = False


@dataclass
class ClaimMatch:
    claim_number: int
    is_independent: bool
    primary_ref: Optional[DocumentMatch] = None
    secondary_refs: list = field(default_factory=list)
    is_covered: bool = False


# ── 후보 구축 ─────────────────────────────────────────────────────────────────

def build_candidates(rag_results: list) -> dict:
    """
    RAGClaimResult 목록 → {uid: CandidateDoc} 딕셔너리.
    동일 문서가 여러 청구항 결과에 등장할 경우 max score + covers_claims 집계.
    """
    cands: dict[str, CandidateDoc] = {}
    for cr in rag_results:
        for chunk_result in cr.top_chunks:
            c = chunk_result.chunk
            uid = f"{c.source}_{c.doc_id}"
            if uid not in cands:
                cands[uid] = CandidateDoc(
                    doc_id=c.doc_id, source=c.source,
                    title=c.title, pub_date=c.pub_date,
                    score=chunk_result.score,
                    best_chunk=c.text,
                    covers_claims=[cr.claim_number],
                )
            else:
                cand = cands[uid]
                if chunk_result.score > cand.score:
                    cand.score = chunk_result.score
                    cand.best_chunk = c.text
                if cr.claim_number not in cand.covers_claims:
                    cand.covers_claims.append(cr.claim_number)

    logger.info("후보 문헌 집계: %d개 고유 문서", len(cands))
    for uid, c in list(cands.items())[:5]:
        logger.debug("  후보: %s | score=%.3f | covers=%s", uid[:40], c.score, c.covers_claims)
    return cands


# ── Matcher ───────────────────────────────────────────────────────────────────

class Matcher:
    def __init__(
        self,
        tolerance_band: float = 0.05,
        max_refs: int = 2,
        w_score: float = 0.6,
        w_coverage: float = 0.4,
    ):
        self.tolerance_band = tolerance_band
        self.max_refs = max_refs
        self.w_score = w_score
        self.w_coverage = w_coverage
        logger.debug(
            "Matcher 초기화: tolerance_band=%.2f, max_refs=%d, w_score=%.1f, w_coverage=%.1f",
            tolerance_band, max_refs, w_score, w_coverage,
        )

    def match(
        self,
        claim_nodes: dict,
        rag_results: list,
    ) -> list:
        """
        반환: list[ClaimMatch] (청구항 번호 오름차순)
        """
        cands = build_candidates(rag_results)
        total_claims = len(claim_nodes)
        logger.info("매칭 시작: 청구항 %d개, 후보 문헌 %d개", total_claims, len(cands))

        # 독립항 → primary ref 저장 (종속항 재사용용)
        primary_refs: dict[int, CandidateDoc] = {}

        results: list[ClaimMatch] = []

        independent = [n for n in claim_nodes.values() if n.is_independent]
        dependent = [n for n in claim_nodes.values() if not n.is_independent]

        logger.info("독립항 매칭: %d개", len(independent))
        for node in sorted(independent, key=lambda n: n.number):
            cm = self._match_independent(node, cands, total_claims)
            if cm.primary_ref:
                uid = f"{cm.primary_ref.source}_{cm.primary_ref.doc_id}"
                primary_refs[node.number] = cands.get(uid)
                logger.info(
                    "  청구항 %d (독립항) → %s | score=%.3f | covers=%s",
                    node.number, cm.primary_ref.doc_id[:30],
                    cm.primary_ref.similarity_score, cm.primary_ref.covers_claims,
                )
            else:
                logger.warning("  청구항 %d (독립항) → 매칭 문헌 없음", node.number)
            results.append(cm)

        logger.info("종속항 매칭: %d개", len(dependent))
        for node in sorted(dependent, key=lambda n: n.number):
            root_num = self._find_root(node, claim_nodes)
            primary_cand = primary_refs.get(root_num)
            cm = self._match_dependent(node, cands, primary_cand, total_claims)
            if cm.primary_ref:
                logger.debug(
                    "  청구항 %d (종속항, root=%d) → %s | covered=%s",
                    node.number, root_num, cm.primary_ref.doc_id[:30], cm.is_covered,
                )
            else:
                logger.debug("  청구항 %d (종속항) → 매칭 문헌 없음", node.number)
            results.append(cm)

        covered = sum(1 for cm in results if cm.is_covered)
        logger.info("매칭 완료: %d/%d 청구항 커버 (%.0f%%)", covered, len(results), covered / max(len(results), 1) * 100)

        return sorted(results, key=lambda cm: cm.claim_number)

    # ── 독립항 매칭 ───────────────────────────────────────────────────────────

    def _match_independent(self, node: ClaimNode, cands: dict, total_claims: int) -> ClaimMatch:
        claim_cands = [c for c in cands.values() if node.number in c.covers_claims]
        if not claim_cands:
            return ClaimMatch(claim_number=node.number, is_independent=True, is_covered=False)

        selected = self._select_by_band(claim_cands, total_claims, n=1)
        if not selected:
            return ClaimMatch(claim_number=node.number, is_independent=True, is_covered=False)

        primary = _to_doc_match(selected[0])
        return ClaimMatch(
            claim_number=node.number,
            is_independent=True,
            primary_ref=primary,
            is_covered=True,
        )

    # ── 종속항 매칭 ───────────────────────────────────────────────────────────

    def _match_dependent(
        self,
        node: ClaimNode,
        cands: dict,
        primary_cand: Optional[CandidateDoc],
        total_claims: int,
    ) -> ClaimMatch:
        # 1순위: primary ref가 이 종속항을 커버하는지 확인 (재사용 우선)
        if primary_cand and node.number in primary_cand.covers_claims:
            logger.debug("    청구항 %d → primary ref 재사용 (%s)", node.number, primary_cand.doc_id[:20])
            return ClaimMatch(
                claim_number=node.number,
                is_independent=False,
                primary_ref=_to_doc_match(primary_cand),
                is_covered=True,
            )

        # 2순위: 별도 후보에서 선택
        claim_cands = [c for c in cands.values() if node.number in c.covers_claims]
        if not claim_cands:
            if primary_cand:
                return ClaimMatch(
                    claim_number=node.number,
                    is_independent=False,
                    primary_ref=_to_doc_match(primary_cand),
                    is_covered=False,
                )
            return ClaimMatch(claim_number=node.number, is_independent=False, is_covered=False)

        primary_uid = primary_cand.uid if primary_cand else ""
        secondaries_pool = [c for c in claim_cands if c.uid != primary_uid]
        secondaries = self._select_by_band(secondaries_pool, total_claims, n=self.max_refs - 1)

        secondary_refs = [_to_doc_match(c) for c in secondaries]
        return ClaimMatch(
            claim_number=node.number,
            is_independent=False,
            primary_ref=_to_doc_match(primary_cand) if primary_cand else None,
            secondary_refs=secondary_refs,
            is_covered=bool(secondary_refs),
        )

    # ── 허용 오차 밴드 + Set Cover 선택 ──────────────────────────────────────

    def _select_by_band(self, candidates: list, total_claims: int, n: int) -> list:
        """허용 오차 밴드 적용 후 조정 점수 기준 상위 n개 선택."""
        if not candidates:
            return []
        max_score = max(c.score for c in candidates)
        band = [c for c in candidates if c.score >= max_score - self.tolerance_band]
        logger.debug(
            "허용 오차 밴드: 전체 %d개 → 밴드 내 %d개 (max=%.3f, band>=%.3f)",
            len(candidates), len(band), max_score, max_score - self.tolerance_band,
        )

        def adjusted(c: CandidateDoc) -> float:
            coverage_ratio = len(c.covers_claims) / max(total_claims, 1)
            return self.w_score * c.score + self.w_coverage * coverage_ratio

        band.sort(key=adjusted, reverse=True)
        return band[:n]

    # ── 유틸리티 ─────────────────────────────────────────────────────────────

    @staticmethod
    def _find_root(node: ClaimNode, claim_nodes: dict) -> int:
        """종속항에서 루트 독립항 번호를 탐색."""
        visited = set()
        current = node
        while current.parents and current.number not in visited:
            visited.add(current.number)
            parent_num = current.parents[0]
            current = claim_nodes.get(parent_num, current)
            if current.is_independent:
                return current.number
        return current.number


def _to_doc_match(cand: CandidateDoc) -> DocumentMatch:
    return DocumentMatch(
        doc_id=cand.doc_id,
        source=cand.source,
        title=cand.title,
        pub_date=cand.pub_date,
        similarity_score=cand.score,
        covers_claims=list(cand.covers_claims),
    )
