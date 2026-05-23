"""
최종 결과 JSON / CSV 직렬화.
출력 구조는 '거절이유 보고서 생성 프로그램'의 입력 스펙에 맞춘다.
"""

import csv
import io
import json
import os
from datetime import date
from src.matcher import ClaimMatch, DocumentMatch
from src.claims_parser import ClaimNode
from src.patent_preprocessor import PatentData


def _doc_to_dict(dm: DocumentMatch | None) -> dict | None:
    if dm is None:
        return None
    return {
        "doc_id": dm.doc_id,
        "source": dm.source,
        "title": dm.title,
        "pub_date": dm.pub_date,
        "similarity_score": round(dm.similarity_score, 4),
        "covers_claims": dm.covers_claims,
        "matched_paragraph": dm.matched_paragraph,
        "paragraph_verified": dm.paragraph_verified,
    }


class OutputFormatter:
    def to_json(
        self,
        patent_data: PatentData,
        claim_matches: list,
        claim_nodes: dict,
    ) -> str:
        covered = sum(1 for cm in claim_matches if cm.is_covered)
        total = len(claim_matches)

        payload = {
            "metadata": {
                "title": patent_data.title,
                "reference_date": patent_data.reference_date,
                "date_type": patent_data.date_type,
                "processed_at": str(date.today()),
                "total_claims": total,
                "covered_claims": covered,
                "coverage_rate": round(covered / total, 4) if total else 0.0,
            },
            "claim_matches": [self._claim_to_dict(cm) for cm in claim_matches],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def to_csv(self, claim_matches: list) -> str:
        buf = io.StringIO()
        fields = [
            "claim_number", "is_independent", "is_covered",
            "primary_doc_id", "primary_source", "primary_title",
            "primary_pub_date", "primary_score", "primary_verified",
            "primary_paragraph",
            "secondary_doc_ids",
        ]
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for cm in claim_matches:
            p = cm.primary_ref
            row = {
                "claim_number": cm.claim_number,
                "is_independent": cm.is_independent,
                "is_covered": cm.is_covered,
                "primary_doc_id": p.doc_id if p else "",
                "primary_source": p.source if p else "",
                "primary_title": p.title if p else "",
                "primary_pub_date": p.pub_date if p else "",
                "primary_score": round(p.similarity_score, 4) if p else "",
                "primary_verified": p.paragraph_verified if p else "",
                "primary_paragraph": (p.matched_paragraph or "")[:200] if p else "",
                "secondary_doc_ids": "|".join(s.doc_id for s in cm.secondary_refs),
            }
            writer.writerow(row)
        return buf.getvalue()

    def save(self, content: str, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _claim_to_dict(self, cm: ClaimMatch) -> dict:
        return {
            "claim_number": cm.claim_number,
            "is_independent": cm.is_independent,
            "is_covered": cm.is_covered,
            "primary_reference": _doc_to_dict(cm.primary_ref),
            "secondary_references": [_doc_to_dict(s) for s in cm.secondary_refs],
        }

    def print_summary(self, patent_data: PatentData, claim_matches: list) -> None:
        covered = sum(1 for cm in claim_matches if cm.is_covered)
        total = len(claim_matches)
        print(f"\n{'='*60}")
        print(f"  발명 명칭  : {patent_data.title or '(없음)'}")
        print(f"  기준일     : {patent_data.reference_date} ({patent_data.date_type})")
        print(f"  커버율     : {covered}/{total} 청구항 ({covered/total*100:.1f}%)" if total else "")
        print(f"{'='*60}")

        for cm in claim_matches:
            kind = "독립항" if cm.is_independent else "종속항"
            covered_mark = "[O]" if cm.is_covered else "[X]"
            print(f"\n  [{covered_mark}] 청구항 {cm.claim_number} ({kind})")
            if cm.primary_ref:
                p = cm.primary_ref
                verified = "검증O" if p.paragraph_verified else "검증X"
                print(f"    주 인용: [{p.source}] {p.doc_id} | {p.pub_date} | "
                      f"score={p.similarity_score:.3f} | {verified}")
                if p.matched_paragraph:
                    print(f"    단락  : {p.matched_paragraph[:100]}...")
            for s in cm.secondary_refs:
                print(f"    보조  : [{s.source}] {s.doc_id} | {s.pub_date} | score={s.similarity_score:.3f}")
            if not cm.primary_ref:
                print("    (선행문헌 없음)")
