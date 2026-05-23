# Phase 5 Spec: 평가 & 매칭 알고리즘 + 최종 출력

## 목표
Phase 4 RAG 결과를 허용 오차 밴드 + Set Cover로 최적화하여
청구항별 최소 인용 문헌을 결정하고, LLM으로 매칭 단락을 추출하고,
할루시네이션 검증 후 JSON/CSV로 출력한다.

---

## 파일 구조 추가분

```
src/
├── matcher.py              # 핵심 매칭 알고리즘 (허용 오차 밴드, Set Cover)
├── hallucination_checker.py# Exact Match 검증 + LLM 재귀 추출
└── output_formatter.py     # JSON / CSV 직렬화
```

---

## 데이터 모델

```python
@dataclass
class CandidateDoc:
    doc_id: str
    source: str
    title: str
    pub_date: str
    score: float           # 최고 청크 유사도 (0~1)
    best_chunk: str        # 가장 유사한 청크 텍스트
    covers_claims: list[int]  # 이 후보가 top-k에 등장하는 청구항 번호 목록

@dataclass
class DocumentMatch:
    doc_id: str
    source: str
    title: str
    pub_date: str
    similarity_score: float
    matched_paragraph: str    # LLM이 추출한 매칭 단락
    paragraph_verified: bool  # Exact Match 검증 결과
    covers_claims: list[int]

@dataclass
class ClaimMatch:
    claim_number: int
    is_independent: bool
    primary_ref: Optional[DocumentMatch]
    secondary_refs: list[DocumentMatch]   # 최대 2개 (예외 3개)
    is_covered: bool
```

---

## Matcher 알고리즘

### 핵심 파라미터
| 파라미터 | 기본값 | 설명 |
|---------|-------|------|
| `tolerance_band` | 0.05 | 최고 유사도 대비 허용 오차 (5%p) |
| `max_refs` | 2 | 결합 문헌 최대 수 (예외 3) |
| `w_coverage` | 0.4 | Set Cover 가중치 (W2) |
| `w_score` | 0.6 | 유사도 점수 가중치 (W1) |

### 처리 흐름

```
1. Phase 4 RAGClaimResult → CandidateDoc 맵 구축
   - doc별 max chunk score 집계
   - covers_claims: 해당 doc이 top-k에 나타난 청구항 번호 목록

2. 독립항 매칭 (부모 없는 청구항 우선)
   a. 후보 수집
   b. 허용 오차 밴드 적용 (max_score - tolerance_band 이상)
   c. 밴드 내 조정 점수 계산:
      adjusted = W1 * score + W2 * (|covers_claims| / total_claims)
   d. 조정 점수 최고 문헌 → Primary Reference 선택
   e. Primary Reference 저장 (독립항 번호 → CandidateDoc)

3. 종속항 매칭
   a. 루트 독립항의 Primary Reference 로컬 RAG 재검색
   b. Primary 청크에서 종속항 특징 발견 → 동일 문헌 사용 (재사용 우선)
   c. 미발견 → Secondary Reference 추가 선택
   d. 총 문헌 수 max_refs 초과 방지

4. 각 채택 문헌에 대해 HallucinationChecker 실행
```

---

## HallucinationChecker 인터페이스

```python
class HallucinationChecker:
    def find_and_verify(
        claim_text: str,
        doc_match: DocumentMatch,
        router: LLMRouter,
        cache: DocumentCache,
        max_retries: int = 3,
    ) -> tuple[str, bool]   # (matched_paragraph, is_verified)
```

### 로직
1. LLM에게 청구항 vs 문서 텍스트로 매칭 단락 추출 요청
2. 응답 단락이 원본 텍스트에 `paragraph in doc_text` 로 존재하는지 확인
3. 실패 시 실패 이유와 함께 LLM 재호출 (최대 `max_retries`회)

---

## OutputFormatter 인터페이스

```python
class OutputFormatter:
    def to_json(patent_data, claim_matches, claim_nodes) -> str
    def to_csv(claim_matches) -> str
    def save(content: str, path: str) -> None
```

### JSON 최상위 구조
```json
{
  "metadata": {
    "title": "발명 명칭",
    "reference_date": "2022-03-15",
    "date_type": "priority",
    "processed_at": "2026-05-23",
    "total_claims": 15,
    "covered_claims": 12,
    "coverage_rate": 0.80
  },
  "claim_matches": [ ... ]
}
```

---

## main.py 신규 명령

```
python main.py match <pdf_path>
  [--rag-results rag.json]    # Phase 4 결과 재사용
  [--claims 1,3]              # 대상 청구항 (기본: 전체)
  [--tolerance 0.05]          # 허용 오차 밴드
  [--max-refs 2]              # 최대 인용 문헌 수
  [--format json|csv]         # 출력 형식
  [--out report.json]         # 결과 저장 경로 (기본: stdout)
  [--no-llm]                  # LLM 단락 추출 생략 (빠른 모드)
```

---

## 검증 기준

- [x] CandidateDoc 구축: doc별 max score + covers_claims 집계 (동일 문서 중복 병합)
- [x] 허용 오차 밴드: max_score - tolerance 이상인 문헌만 후보군
- [x] 조정 점수: W1×score + W2×coverage 적용
- [x] 재사용 우선: 독립항 primary ref가 종속항 covers_claims에 있으면 재사용
- [x] 최대 문헌 수 max_refs 초과 방지 (secondary 풀에서 n-1개 선택)
- [x] HallucinationChecker: exact match + PARAGRAPH 파싱 (정상/멀티라인/미준수 형식)
- [x] JSON 출력: metadata + claim_matches (4/4 커버 확인)
- [x] CSV 출력: 청구항별 1행 (헤더 포함 5행)
- [x] `python main.py match <pdf>` 명령 등록 완료

## 구현 완료: 2026-05-23
