# 특허 선행기술조사 CLI 시스템 — 종합 검토 보고서

> 작성일: 2026-05-23 | 검토 대상: Phase 1~5 전체 코드

---

## 1. 프로젝트 전체 구조

```
D:\Searching\
├── main.py                    # CLI 진입점 (6개 명령: config/test/parse/search/rag/match)
├── config.yaml                # 사용자 설정 (API 키, 모델, RAG 파라미터)
├── requirements.txt           # 의존성 목록
├── .gitignore
├── specs/                     # Phase별 스펙 문서
│   ├── phase1.md ~ phase5.md
├── src/
│   ├── config_manager.py      # Phase 1: 설정 관리
│   ├── llm_router.py          # Phase 1: API / CLI fallback 라우터
│   ├── pdf_parser.py          # Phase 2: PDF → Markdown
│   ├── patent_preprocessor.py # Phase 2: 기준일·청구범위 추출
│   ├── claims_parser.py       # Phase 2: 의존성 트리 파서
│   ├── query_generator.py     # Phase 3: LLM → QuerySpec
│   ├── search_clients.py      # Phase 3: KIPRIS/USPTO/S2 API 클라이언트
│   ├── document_cache.py      # Phase 3: 로컬 JSON 캐시
│   ├── search_pipeline.py     # Phase 3: 검색 오케스트레이터
│   ├── chunker.py             # Phase 4: RecursiveCharacterTextSplitter
│   ├── embedder.py            # Phase 4: sentence-transformers
│   ├── vector_store.py        # Phase 4: FAISS / ChromaDB 추상화
│   ├── rag_pipeline.py        # Phase 4: RAG 오케스트레이터
│   ├── matcher.py             # Phase 5: 허용 오차 밴드 + Set Cover
│   ├── hallucination_checker.py # Phase 5: Exact Match 검증
│   └── output_formatter.py   # Phase 5: JSON / CSV 출력
```

---

## 2. CLI 명령 요약

| 명령 | 역할 | 주요 옵션 |
|------|------|-----------|
| `config [--setup]` | 설정 확인 / 대화형 설정 | |
| `test` | LLM 연결 테스트 | |
| `parse <pdf>` | PDF 파싱, 청구항 트리 출력 | `--claims` (원문 출력) |
| `search <pdf>` | 1차 외부 DB 검색 | `--claims`, `--db`, `--max`, `--out` |
| `rag <pdf>` | 2차 로컬 RAG 검색 | `--results`, `--top-k`, `--rebuild`, `--out` |
| `match <pdf>` | 전체 파이프라인 + 최종 출력 | `--rag-results`, `--tolerance`, `--max-refs`, `--format`, `--no-llm`, `--out` |

### 권장 실행 순서

```bash
# 1. 최초 설정
python main.py config --setup

# 2. 단계별 (중간 결과 저장)
python main.py parse   patent.pdf
python main.py search  patent.pdf --out search.json
python main.py rag     patent.pdf --results search.json --out rag.json
python main.py match   patent.pdf --rag-results rag.json --out report.json

# 3. 한 번에 (전체 자동 실행)
python main.py match patent.pdf --out report.json
```

---

## 3. 발견된 버그 및 수정 내역

### BUG-1: `main.py:146` — 조건식 오류 (수정 완료)

```python
# 수정 전 (항상 True라 의도한 조건이 동작하지 않음)
if args.results and _json.JSONDecodeError:

# 수정 후
if args.results:
```

### BUG-2: `cmd_match` — 종속항 RAG 누락으로 재사용 로직 미작동 (수정 완료)

`cmd_match`에서 파이프라인 자동 실행 시 독립항만 RAG 검색해
종속항이 어느 문헌에도 `covers_claims`에 포함되지 않았음.
→ Primary Reference 재사용 원칙이 항상 실패하는 문제.

```python
# 수정 전
target_nums = target or [n.number for n in nodes.values() if n.is_independent]
rag_results = rag.search(nodes, target_nums, top_k=10)

# 수정 후 (전체 청구항 검색)
all_claim_nums = sorted(nodes.keys())
rag_results = rag.search(nodes, all_claim_nums, top_k=10)
```

### BUG-3: `output_formatter.py` — Windows cp949 인코딩 오류 (수정 완료)

`✓` / `✗` 기호 → `[O]` / `[X]` ASCII 대체

---

## 4. 설계 검토: 잘 된 부분

### Phase 1 — LLM 라우터
- API 키 우선 → CLI fallback 라우팅이 깔끔하게 분리됨
- `FileNotFoundError` 시 명확한 메시지 출력
- 3개 에이전트(Claude/Gemini/OpenAI) 대칭적 처리

### Phase 2 — 청구항 파서
- 한국어 `내지`(범위), `또는`(선택), 단일 종속 3가지 패턴 처리
- 영어 `1-3`, `any one of claims`, `claim 1, wherein` 패턴 처리
- 다중 부모 종속항의 트리 렌더링 중복 방지 (`rendered` 집합)

### Phase 3 — 검색 파이프라인
- 표준 라이브러리만 사용 (추가 의존성 없음)
- `_date_ok` 날짜 컷오프 필터 단순·명확
- KIPRIS/USPTO/S2 클라이언트가 동일 인터페이스로 교체 가능

### Phase 4 — RAG
- FAISS/ChromaDB 공통 추상화로 config 한 줄로 교체 가능
- 인덱스 저장/재사용으로 재시작 시 임베딩 비용 절약
- 50자 미만 청크 자동 제외

### Phase 5 — 매칭
- W1(유사도)×0.6 + W2(커버리지)×0.4 조정 점수로 누더기 거절 방지
- 재사용 우선 원칙: Primary Ref가 종속항도 커버하면 추가 문헌 불필요
- Exact Match 재시도 3회로 할루시네이션 억제

---

## 5. 미구현 및 부족한 부분

### 5-1. Espacenet (EPO OPS) — stub 상태

`search_clients.py`의 `EspacenetClient`는 항상 빈 리스트 반환.
OAuth2 인증 구현 필요.

```python
# 현재
class EspacenetClient(BaseSearchClient):
    def search(self, ...) -> list:
        print("[espacenet] 미구현 stub — skip")
        return []
```

**구현 방향:**
- EPO OPS 계정 등록 → client_id / client_secret 획득
- `config.yaml`에 `search.epo_client_id`, `search.epo_client_secret` 추가
- `POST https://ops.epo.org/3.2/auth/accesstoken` → bearer token
- `GET https://ops.epo.org/3.2/rest-services/published-data/search?q=...` 호출

---

### 5-2. 선행문헌 전문(Full Text) 다운로드 미완성

`document_cache.py`의 `_try_fetch_text()`는 Semantic Scholar의 PDF URL을 감지해도
실제 텍스트 추출 없이 빈 문자열을 반환함.

```python
# 현재
def _try_fetch_text(self, result: SearchResult) -> str:
    if result.source != "semantic_scholar" or not result.url.endswith(".pdf"):
        return ""
    # PDF 바이너리 다운로드만 하고 텍스트 추출 안 함
    return ""
```

**구현 방향:**
1. PDF URL 다운로드 → 임시 파일 저장
2. `opendataloader_pdf.convert()` → Markdown 변환
3. Markdown 텍스트를 `full_text`에 저장

이 기능이 없으면 할루시네이션 검증 시 `doc_text`가 abstract만으로 제한됨.

---

### 5-3. 임베딩 모델 — 한국어 성능 부족

현재 기본 모델: `sentence-transformers/all-MiniLM-L6-v2` (영어 특화)

```
'배터리 관리' ↔ 'battery management' 유사도: 0.267  ← 너무 낮음
```

**권장 대안:**
- `paraphrase-multilingual-MiniLM-L12-v2` — 한/영 균형
- `jhgan/ko-sroberta-multitask` — 한국어 특화
- `BAAI/bge-m3` — 다국어, 고성능

**변경 방법:**
```bash
python main.py config --setup
# 모델명에 paraphrase-multilingual-MiniLM-L12-v2 입력
```

또는 `config.yaml` 직접 수정:
```yaml
rag:
  embedding_model: paraphrase-multilingual-MiniLM-L12-v2
```

---

### 5-4. KIPRIS 쿼리 형식 호환성

`_query_keywords()`는 Boolean 식 (`(A OR B) AND C`)을 KIPRIS에 그대로 전달.
KIPRIS Open API는 단순 키워드 방식을 지원하며 표준 Boolean 연산자를 파싱하지 못할 수 있음.

**권장 수정:** KIPRIS 전용 키워드 추출 함수 분리

```python
# search_clients.py에 추가
def _kipris_keywords(q: QuerySpec) -> str:
    """KIPRIS는 단순 AND 결합만 지원."""
    return " ".join(q.keywords[:3]) if q.keywords else ""
```

---

### 5-5. 거절 근거 (신규성/진보성) 레이블 없음

최종 JSON 출력에 `rejection_basis` 필드가 없어 거절이유 보고서 생성 프로그램에서
신규성(§29①) vs 진보성(§29②) 구분이 불가능함.

**구현 방향:**
- `similarity_score ≥ 0.95` → 신규성(§29①) 의심
- `similarity_score < 0.95` → 진보성(§29②) 적용
- 또는 LLM에게 판단 위임 (청구항 특징 vs 선행문헌 개시 내용 비교)

```python
# output_formatter.py 수정 예시
def _rejection_basis(score: float) -> str:
    return "신규성(§29①)" if score >= 0.95 else "진보성(§29②)"
```

---

### 5-6. 설정 파일 comments 유실

`config.yaml`이 `yaml.dump()`로 재생성될 때 주석(`#`) 이 모두 사라짐.
`ruamel.yaml` 라이브러리를 쓰면 주석 보존 가능.

---

### 5-7. 할루시네이션 검증 범위 제한

`hallucination_checker.py`에서 LLM에게 전달하는 문서 텍스트가 4000자로 잘림.
문서 후반부에 있는 매칭 단락은 LLM이 볼 수 없어 추출 실패 → `paragraph_verified=False`.

**완화 방법:**
- Sliding window 방식으로 4000자씩 청크 단위로 LLM 호출
- 또는 관련 청크(`best_chunk`)를 우선 전달 후 전체 탐색

---

## 6. 의존성 및 설치 요구사항

### 필수 설치

```bash
pip install pyyaml anthropic google-generativeai openai \
            opendataloader-pdf \
            sentence-transformers faiss-cpu chromadb \
            langchain-text-splitters
```

> `opendataloader-pdf`는 Java 런타임(JRE 11+)이 필요합니다.

### 선택 설치

```bash
# 다국어 임베딩 사용 시 (추가 설치 불필요, config 변경만)
# paraphrase-multilingual-MiniLM-L12-v2 는 첫 실행 시 자동 다운로드

# Espacenet 구현 시
pip install requests  # 현재 urllib 사용 중, 선택사항
```

### API 키 필요 항목

| 서비스 | 필요 여부 | config 키 |
|--------|-----------|-----------|
| Claude API | 선택 (없으면 CLI fallback) | `llm.api_key` |
| Gemini API | 선택 | `llm.api_key` |
| OpenAI API | 선택 | `llm.api_key` |
| KIPRIS Open API | 선택 (없으면 skip) | `search.kipris_api_key` |
| USPTO PatentsView | 불필요 | — |
| Semantic Scholar | 불필요 | — |

---

## 7. 알려진 제한사항

| # | 내용 | 영향도 |
|---|------|--------|
| 1 | Espacenet stub | 유럽 특허 검색 불가 |
| 2 | 선행문헌 전문 미다운로드 | 할루시네이션 검증 정확도 저하 |
| 3 | 영어 특화 임베딩 모델 | 한국어 특허의 한↔영 교차 검색 정확도 저하 |
| 4 | KIPRIS Boolean 쿼리 비호환 | KIPRIS 검색 결과 누락 가능 |
| 5 | 거절 근거 레이블 없음 | 다운스트림 보고서 생성기에서 수동 입력 필요 |
| 6 | 4000자 컨텍스트 제한 | 긴 문서의 후반부 단락 검증 실패 |

---

## 8. 향후 개선 로드맵

### 단기 (바로 적용 가능)
- [ ] `config.yaml`에 `embedding_model: paraphrase-multilingual-MiniLM-L12-v2` 변경
- [ ] KIPRIS 전용 키워드 추출 함수 분리
- [ ] `rejection_basis` 레이블 출력 추가

### 중기 (구현 1~2일)
- [ ] 선행문헌 PDF 전문 다운로드 + opendataloader-pdf 변환
- [ ] 할루시네이션 검증 Sliding window 방식 개선
- [ ] EPO OPS Espacenet 클라이언트 구현

### 장기 (구조 변경 필요)
- [ ] `ruamel.yaml`로 config 주석 보존
- [ ] 비동기(asyncio) 병렬 DB 검색
- [ ] 웹 UI 추가 (FastAPI + 간단한 HTML)

---

## 9. 출력 JSON 스키마 (거절이유 보고서 생성기 연동)

```json
{
  "metadata": {
    "title": "발명 명칭",
    "reference_date": "YYYY-MM-DD",
    "date_type": "priority | filing | unknown",
    "processed_at": "YYYY-MM-DD",
    "total_claims": 15,
    "covered_claims": 12,
    "coverage_rate": 0.80
  },
  "claim_matches": [
    {
      "claim_number": 1,
      "is_independent": true,
      "is_covered": true,
      "primary_reference": {
        "doc_id": "KR20220001234",
        "source": "kipris",
        "title": "배터리 관리 시스템",
        "pub_date": "2022-03-15",
        "similarity_score": 0.872,
        "covers_claims": [1, 2, 3],
        "matched_paragraph": "배터리 팩은 복수의 셀로 구성되며...",
        "paragraph_verified": true
      },
      "secondary_references": []
    }
  ]
}
```

---

*검토 완료: 2026-05-23*
