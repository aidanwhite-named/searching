# Phase 3 Spec: 1차 외부 DB 검색 파이프라인

## 목표
청구항 텍스트를 LLM으로 분석하여 CPC+키워드 하이브리드 쿼리를 생성하고,
외부 특허/논문 DB에서 선행문헌을 검색한 뒤 전문을 로컬에 캐시한다.
결과는 Phase 4 RAG 파이프라인과 Phase 5 매칭 알고리즘의 입력값이 된다.

---

## 파일 구조 추가분

```
src/
├── query_generator.py    # LLM → QuerySpec (CPC + 키워드 + Boolean식)
├── search_clients.py     # DB별 API 클라이언트 + SearchResult 데이터클래스
├── document_cache.py     # 검색 결과 로컬 JSON 캐시
└── search_pipeline.py    # 위 모듈 조합 오케스트레이터
.cache/
└── documents/            # 캐시된 문서 JSON 파일 저장 위치
```

---

## 데이터 모델

```python
@dataclass
class QuerySpec:
    claim_number: int
    keywords: list[str]           # 핵심 기술 용어 3~5개
    synonyms: dict[str, list[str]] # 동의어 맵
    cpc_codes: list[str]          # CPC 분류 코드 (예: "H01M10/42")
    boolean_query: str            # "(keyword1 OR syn1) AND keyword2"

@dataclass
class SearchResult:
    doc_id: str        # 특허번호 또는 논문 ID
    title: str
    abstract: str
    pub_date: str      # "YYYY-MM-DD" (기준일 컷오프 필터용)
    source: str        # "kipris" | "uspto" | "semantic_scholar" | "espacenet"
    url: str
    local_path: str    # 캐시된 JSON 파일 경로 (DocumentCache가 채움)

@dataclass
class ClaimSearchResults:
    claim_number: int
    query: QuerySpec
    results: list[SearchResult]
```

---

## QueryGenerator 인터페이스

```python
class QueryGenerator:
    def __init__(router: LLMRouter)
    def generate(claim_number: int, claim_text: str, reference_date: str) -> QuerySpec
```

### LLM 프롬프트 출력 형식
```json
{
  "keywords": ["배터리 관리", "셀 밸런싱"],
  "synonyms": {"배터리 관리": ["battery management", "BMS"]},
  "cpc_codes": ["H01M10/42", "H02J7/00"],
  "boolean_query": "(배터리 OR battery OR BMS) AND (관리 OR management) AND 셀"
}
```

---

## SearchClient 인터페이스

```python
class BaseSearchClient(ABC):
    def search(query: QuerySpec, cutoff_date: str, max_results: int) -> list[SearchResult]
```

| 클라이언트 | DB | API 키 | 비고 |
|------------|-----|--------|------|
| KiprisClient | KIPRIS (한국특허) | `search.kipris_api_key` | XML 응답, 날짜 필터 지원 |
| UsptoClient | USPTO PatentsView | 불필요 | JSON, 무료 |
| SemanticScholarClient | Semantic Scholar | 불필요 | JSON, 논문 포함 |
| EspacenetClient | EPO Espacenet | 불필요 (stub) | 향후 OAuth2 구현 예정 |

---

## DocumentCache 인터페이스

```python
class DocumentCache:
    def __init__(cache_dir: str = ".cache/documents")
    def get(doc_id: str) -> Optional[dict]         # 캐시 히트
    def store(result: SearchResult) -> str          # JSON 저장 후 경로 반환
    def fetch_and_store(result: SearchResult) -> SearchResult  # URL → 캐시
```

캐시 파일 형식 (`.cache/documents/<source>_<doc_id>.json`):
```json
{
  "doc_id": "KR20220001234",
  "title": "...",
  "abstract": "...",
  "pub_date": "2022-03-15",
  "source": "kipris",
  "url": "...",
  "full_text": ""
}
```

---

## SearchPipeline 인터페이스

```python
class SearchPipeline:
    def __init__(router: LLMRouter, config: ConfigManager)
    def run(
        patent_data: PatentData,
        claim_nodes: dict[int, ClaimNode],
        target_claims: list[int] = None,   # None이면 독립항 전체
        databases: list[str] = None,       # None이면 모든 활성 DB
        max_per_db: int = 10,
    ) -> list[ClaimSearchResults]
```

---

## main.py 신규 명령

```
python main.py search <pdf_path>
  [--claims 1,3]              # 검색 대상 청구항 번호 (기본: 독립항만)
  [--db kipris,semantic_scholar,uspto]  # 사용 DB
  [--max 10]                  # DB당 최대 결과 수
  [--out results.json]        # 결과 저장 경로 (기본: stdout)
```

---

## 검증 기준

- [x] LLM → QuerySpec JSON 파싱 성공 (코드블록/날 JSON 모두 처리)
- [x] 각 DB 클라이언트 search() 호출 시 결과 반환 (키 없으면 skip)
- [x] 기준일 이후 문헌 자동 필터링 (_date_ok)
- [x] DocumentCache: 저장/로드/전문결합 정상 동작
- [x] KIPRIS 날짜 정규화 (YYYYMMDD → YYYY-MM-DD)
- [x] `python main.py search <pdf>` 명령 등록 완료

## 구현 완료: 2026-05-23
