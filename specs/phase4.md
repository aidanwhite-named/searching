# Phase 4 Spec: 로컬 RAG 파이프라인

## 목표
Phase 3에서 캐시한 문서(`.cache/documents/*.json`)를 로드하여
문단 단위로 청킹 → 로컬 임베딩 → 벡터 DB 인덱싱 → 청구항 유사도 검색.
결과는 Phase 5 매칭 알고리즘의 입력값이 된다.

---

## 파일 구조 추가분

```
src/
├── chunker.py       # 문서 텍스트 청킹 (langchain RecursiveCharacterTextSplitter)
├── embedder.py      # sentence-transformers 로컬 임베딩
├── vector_store.py  # FAISS / ChromaDB 추상화 래퍼
└── rag_pipeline.py  # 위 모듈 조합 + 청구항 검색 오케스트레이터
.cache/
├── documents/       # Phase 3 JSON 캐시
└── vector_db/       # FAISS 인덱스 또는 ChromaDB 퍼시스턴트 데이터
```

---

## 데이터 모델

```python
@dataclass
class Chunk:
    text: str
    doc_id: str
    source: str
    pub_date: str
    title: str
    chunk_idx: int

@dataclass
class ChunkResult:   # 유사도 검색 결과
    chunk: Chunk
    score: float     # 코사인 유사도 (0~1)

@dataclass
class RAGClaimResult:
    claim_number: int
    top_chunks: list[ChunkResult]
```

---

## Chunker 인터페이스

```python
class Chunker:
    def __init__(chunk_size: int = 512, chunk_overlap: int = 64)
    def chunk_document(result: SearchResult, text: str) -> list[Chunk]
    def chunk_all(search_results: list[ClaimSearchResults],
                  cache: DocumentCache) -> list[Chunk]
```

- langchain `RecursiveCharacterTextSplitter` 사용
- 각 청크에 `doc_id`, `source`, `pub_date`, `title`, `chunk_idx` 메타데이터 포함
- 청크 텍스트가 비어 있거나 50자 미만이면 제외

---

## Embedder 인터페이스

```python
class Embedder:
    def __init__(model_name: str = "sentence-transformers/all-MiniLM-L6-v2")
    def embed(texts: list[str]) -> np.ndarray   # shape: (N, D), L2 정규화됨
    def embed_one(text: str) -> np.ndarray       # shape: (D,)
```

- `sentence_transformers.SentenceTransformer` 사용
- 결과는 L2 정규화 → 코사인 유사도 = 내적(Inner Product)

---

## VectorStore 인터페이스

```python
class VectorStore:
    def __init__(backend: str, cache_dir: str, dimension: int)
    def add(chunks: list[Chunk], embeddings: np.ndarray) -> None
    def search(query_vec: np.ndarray, k: int) -> list[tuple[Chunk, float]]
    def save(name: str) -> None     # 인덱스 파일 저장
    def load(name: str) -> bool     # 인덱스 파일 로드 (없으면 False)
    def count(self) -> int          # 저장된 청크 수
```

| backend | 저장 경로 | 특이사항 |
|---------|----------|---------|
| faiss | `.cache/vector_db/<name>.index` + `.pkl` | 빠른 검색, numpy 의존 |
| chromadb | `.cache/vector_db/chroma/` | 퍼시스턴트 자동 저장 |

---

## RAGPipeline 인터페이스

```python
class RAGPipeline:
    def __init__(config: ConfigManager)
    def build_index(
        search_results: list[ClaimSearchResults],
        cache: DocumentCache,
        index_name: str = "session",
        force_rebuild: bool = False,
    ) -> int   # 인덱싱된 청크 수

    def search(
        claim_nodes: dict[int, ClaimNode],
        target_claims: list[int],
        top_k: int = 5,
    ) -> list[RAGClaimResult]
```

### 처리 흐름

```
build_index():
  캐시 문서 로드 → Chunker → Embedder → VectorStore.add() → save()

search():
  for each claim:
    embed(claim.text) → VectorStore.search(k) → ChunkResult 목록
```

---

## main.py 신규 명령

```
python main.py rag <pdf_path>
  [--results results.json]   # Phase 3 결과 JSON (없으면 search 자동 실행)
  [--claims 1,3]             # 검색 대상 청구항
  [--top-k 5]                # 청구항당 반환할 상위 청크 수
  [--rebuild]                # 기존 벡터 인덱스 무시하고 재구축
  [--out rag_results.json]   # 결과 저장 경로
```

---

## 검증 기준

- [x] 문서 텍스트 → 청크 분리 (50자 미만 제외, 메타데이터 포함)
- [x] sentence-transformers 임베딩 L2 정규화 확인 (노름≈1)
- [x] FAISS 인덱스 add/search/save/load 정상 동작
- [x] ChromaDB add/search 정상 동작
- [x] RAGPipeline.build_index() → 청크 수 반환 + 인덱스 재사용
- [x] RAGPipeline.search() → claim별 top-k ChunkResult 반환 (score 0~1)
- [x] `python main.py rag` 명령 등록 완료

## 비고
- all-MiniLM-L6-v2는 영어 특화 모델 → 한/영 교차 유사도 낮음 (0.267)
- 한국어 특허 중심이면 config에서 `paraphrase-multilingual-MiniLM-L12-v2`로 교체 권장

## 구현 완료: 2026-05-23
