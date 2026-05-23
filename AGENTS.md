# Behavioral guidelines to reduce common LLM coding mistakes.

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.
- No features beyond what was asked.
- No abstractions for single-use code.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

---

# [Project] 특허 선행기술조사 및 거절논리 매칭 시스템

## 1. 프로젝트 개요

너는 특허청 심사관 수준의 도메인 지식을 갖춘 수석 파이썬(Python) 개발자야.
이 프로젝트는 대상 특허(PDF)를 입력받아, 1차 외부 DB 검색(키워드+CPC)과 2차 로컬 RAG(의미 검색)를 거쳐, 청구항별로 진보성을 타격할 수 있는 최적의 선행문헌 단락을 핀셋 매칭해주는 시스템이야.
최종 출력물(JSON/CSV)은 기존 '거절이유 보고서 생성 프로그램'의 입력값으로 사용될 예정이야.

**현재 상태: 모든 Phase(1~5) 구현 완료. CLI + 웹 대시보드 모두 동작.**

---

## 2. 시스템 아키텍처 및 기술 스택

### A. 구동 환경 및 UI

* **CLI:** `python main.py <command> [options]` — 서브커맨드: `config`, `test`, `parse`, `search`, `rag`, `match`
* **웹 대시보드:** `python server.py` — FastAPI + `uvicorn`, 포트 8001, `web/` 디렉토리에 프론트엔드(index.html, app.js, style.css)
* **설정:** `config.yaml` 파일 및 `python main.py config --setup` 마법사로 관리

### B. LLM 통신 모듈 (`src/llm_router.py`)

* **지원 에이전트:** `codex` (기본), `claude`, `gemini`, `openai`
* **API Key 우선:** `config.yaml`의 `llm.api_key`가 있으면 해당 API 직접 호출
* **CLI Fallback:** API 키 없으면 `subprocess`로 로컬 CLI 도구 호출
  * codex: `["codex", "-p", prompt]`
  * claude: `["claude", "-p", prompt]`
  * gemini: `["gemini", "-p", prompt]`
  * openai: `["gpt", prompt]`

### C. 설정 관리 (`src/config_manager.py`)

* `config.yaml` 파싱, deep-merge, 기본값 폴백
* 현재 활성 설정: `agent: claude`, `model: claude-opus-4-7`, `vector_db: qdrant`
* LLM 기본 모델: `codex→gpt-5-codex`, `claude→claude-opus-4-7`, `gemini→gemini-2.0-flash`, `openai→gpt-4o`

### D. 외부 검색 프로바이더 (`providers/`)

* `base_provider.py`: `BaseProvider` ABC + `SearchResult` 데이터클래스
* `kipris_provider.py`: KIPRIS Open API (한국 특허)
* `epo_provider.py`: EPO OPS API (유럽 특허, Espacenet)
* `openalex_provider.py`: OpenAlex API (학술 문헌, 무료)
* 환경변수 우선: `KIPRIS_API_KEY`, `EPO_OPS_KEY`, `EPO_OPS_SECRET`, `OPENALEX_EMAIL`
* `.env` 파일 지원 (`python-dotenv`)

### E. 데이터 전처리 (`src/`)

* **PDF 파싱:** `src/pdf_parser.py` + `src/patent_preprocessor.py` — `opendataloader-pdf` 사용, 청구범위 마크다운 추출
* **날짜 추출:** 우선권 주장일 → 출원일 순으로 기준일(cut-off) 결정 (`PatentData.reference_date`)
* **청구항 파서:** `src/claims_parser.py` — 의존성 트리(ClaimNode), 독립항/종속항 구조 파싱

### F. 로컬 RAG 파이프라인

* **청킹:** `src/chunker.py` — `RecursiveCharacterTextSplitter`, `Chunk` 데이터클래스
  * `chunk_type`: `"abstract"` | `"summary"` | `"claim"` | `"independent_claim"` | `"sub_claim"`
* **임베딩:** `src/embedder.py` — `sentence-transformers`, 기본 모델 `BAAI/bge-m3` (dimension: 1024)
* **벡터 DB:** `src/vector_store.py` — **Qdrant** (로컬 embedded 또는 `QDRANT_URL` 환경변수로 원격 연결)
  * 로컬 저장 경로: `.cache/qdrant_db/db/`
  * FAISS/ChromaDB는 사용하지 않음
* **리랭커:** `src/reranker.py` — RAG 결과 재정렬
* **RAG 파이프라인:** `src/rag_pipeline.py` — 인덱스 구축 + 청구항별 유사 청크 검색

### G. 매칭 & 출력

* **쿼리 생성:** `src/query_generator.py` — LLM으로 키워드/CPC/Boolean 쿼리 생성
* **검색 파이프라인:** `src/search_pipeline.py` — 외부 DB 검색 오케스트레이션
* **매처:** `src/matcher.py` — 허용 오차 밴드(5%p) + Set Cover 최적화
* **할루시네이션 검증:** `src/hallucination_checker.py` — 원문 Exact Match 검증
* **출력 포매터:** `src/output_formatter.py` — JSON/CSV 변환 및 저장
* **문서 캐시:** `src/document_cache.py` — 다운로드 문서 로컬 캐싱

---

## 3. 핵심 알고리즘

**① 1차 검색 쿼리 생성 (Semantic to Boolean):**
청구항 분석 → 키워드 + 동의어 + CPC/IPC 코드 조합 하이브리드 검색식 생성 (KIPRIS/EPO/OpenAlex용)

**② 종속항 의존성 그래프 (Dependency Tree):**
청구항 부모-자식 관계 파싱. 종속항 검색 시 부모 항의 문헌 상태 상속.

**③ 최적 인용문헌 채택 알고리즘 (Set Cover & Minimum Citation):**
- 허용 오차 밴드: 최고 유사도 대비 5%p 이내 문헌은 동일 후보군
- 전역 최적화: 더 많은 종속항을 커버하는 문헌에 가중치 부여 (누더기 거절 방지)
- 재사용 우선: Primary Reference 내 종속항 특징 로컬 RAG로 먼저 탐색
- 최대 인용 수: 기본 2개 (예외 3개)

**④ 할루시네이션 검증기 (Exact Match):**
LLM 매칭 단락이 원본 텍스트에 정확히 존재하는지 Python 문자열 검색으로 검증. 실패 시 재시도.

---

## 4. 파일 구조

```
D:\Searching\
├── main.py                    # CLI 진입점 (config/test/parse/search/rag/match)
├── server.py                  # FastAPI 웹 대시보드 서버 (포트 8001)
├── config.yaml                # 실제 사용 설정 (agent: claude)
├── config.yaml.example        # 설정 예시
├── .env.example               # 환경변수 예시
├── requirements.txt
├── CLAUDE.md                  # Claude Code용 프로젝트 지시사항 (이 파일과 내용 동기화 필요)
├── providers/
│   ├── base_provider.py       # BaseProvider ABC + SearchResult
│   ├── kipris_provider.py     # KIPRIS (한국 특허)
│   ├── epo_provider.py        # EPO OPS (유럽 특허)
│   └── openalex_provider.py   # OpenAlex (학술)
├── src/
│   ├── config_manager.py      # YAML 설정 로드/저장/마법사
│   ├── llm_router.py          # API/CLI Fallback 라우터
│   ├── pdf_parser.py          # opendataloader-pdf 래퍼
│   ├── patent_preprocessor.py # PDF → PatentData (기준일, 청구항)
│   ├── claims_parser.py       # 청구항 의존성 트리 파싱
│   ├── query_generator.py     # LLM 기반 검색식 생성
│   ├── search_pipeline.py     # 외부 DB 검색 오케스트레이션
│   ├── document_cache.py      # 문서 로컬 캐시
│   ├── chunker.py             # 문서 청킹 (Chunk 데이터클래스)
│   ├── embedder.py            # sentence-transformers 임베딩
│   ├── vector_store.py        # Qdrant 벡터 DB 래퍼
│   ├── reranker.py            # 결과 리랭킹
│   ├── rag_pipeline.py        # RAG 인덱스 구축 + 검색
│   ├── matcher.py             # Set Cover 매칭 알고리즘
│   ├── hallucination_checker.py # Exact Match 검증
│   └── output_formatter.py   # JSON/CSV 출력
└── web/
    ├── index.html
    ├── app.js
    └── style.css
```

---

## 5. 실행 방법

```bash
# 설정 확인 및 변경
python main.py config
python main.py config --setup

# LLM 연결 테스트
python main.py test

# PDF 파싱 (청구항 의존성 트리 확인)
python main.py parse <patent.pdf> [--claims]

# 1차 외부 DB 검색
python main.py search <patent.pdf> [--db kipris,epo,openalex] [--max 10] [--out results.json]

# 2차 로컬 RAG 검색
python main.py rag <patent.pdf> [--results results.json] [--top-k 5] [--out rag.json]

# 최종 매칭 + 출력 (전체 파이프라인)
python main.py match <patent.pdf> [--rag-results rag.json] [--tolerance 0.05] [--max-refs 2] [--format json|csv] [--out report.json] [--no-llm]

# 웹 대시보드
python server.py  # http://127.0.0.1:8001
```

---

## 6. 알려진 주의사항

* `search_pipeline.py`가 `python-dotenv`를 사용함 — `requirements.txt`에 `python-dotenv>=1.0.0` 추가 필요
* 벡터 DB는 Qdrant만 지원. FAISS/ChromaDB 코드는 없음
* 웹 서버는 threading 방식으로 분석 작업 실행 (멀티 프로세스 아님)
* `config_manager.py`의 `DEFAULT_CONFIG`는 `codex`를 기본 에이전트로 지정하지만, 실제 `config.yaml`은 `claude`로 설정됨
* CLAUDE.md (Claude Code용)와 이 파일의 내용을 함께 업데이트할 것
