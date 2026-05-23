# 설치 및 시작 가이드

## 사전 요구사항

| 항목 | 버전 | 비고 |
|------|------|------|
| Python | 3.11+ | `python --version`으로 확인 |
| Java JRE | 11+ | opendataloader-pdf가 Java CLI를 내부 호출 |
| LLM CLI 또는 API 키 | — | `claude`, `gemini`, `gpt` 중 하나 또는 해당 API 키 |

---

## 1. 의존성 설치

```bash
pip install -r requirements.txt
```

> **한국어 특허 위주라면 임베딩 모델 변경을 권장합니다.**
> `config.yaml`의 `rag.embedding_model` 값을
> `paraphrase-multilingual-MiniLM-L12-v2` 로 변경하세요.

---

## 2. 초기 설정

```bash
python main.py config --setup
```

대화형 마법사가 실행됩니다. 아래 항목을 입력하세요:

| 항목 | 예시 | 비고 |
|------|------|------|
| LLM 에이전트 | `claude` | claude / gemini / openai |
| 모델명 | `claude-opus-4-7` | 에이전트별 모델 확인 필요 |
| API 키 | `sk-ant-...` | 비워두면 로컬 CLI 사용 |
| KIPRIS API 키 | `...` | 없으면 KIPRIS 검색 skip |
| 벡터 DB | `faiss` | faiss 또는 chromadb |
| 출력 형식 | `json` | json 또는 csv |

---

## 3. LLM 연결 확인

```bash
python main.py test
```

`API 키 없음` 상태면 로컬 CLI(`claude -p "..."`)를 시도합니다.
Claude CLI 설치: https://github.com/anthropics/anthropic-sdk-python

---

## 4. 특허 분석 실행

### 빠른 시작 (전체 자동)

```bash
python main.py match 특허.pdf --out report.json
```

### 단계별 실행 (중간 결과 저장/재사용)

```bash
# 청구항 파싱 확인
python main.py parse 특허.pdf

# 1차 외부 DB 검색
python main.py search 특허.pdf --out search.json

# 2차 로컬 RAG
python main.py rag 특허.pdf --results search.json --out rag.json

# 최종 매칭 & 출력
python main.py match 특허.pdf --rag-results rag.json --out report.json
```

---

## 5. config.yaml 구조

```yaml
llm:
  agent: claude           # claude | gemini | openai
  model: claude-opus-4-7  # 에이전트별 모델명
  api_key: ""             # 비워두면 로컬 CLI 사용

search:
  kipris_api_key: ""      # KIPRIS Open API 키 (없으면 skip)
  max_results: 20         # DB당 최대 검색 수

rag:
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
  # 한국어 특허: paraphrase-multilingual-MiniLM-L12-v2 권장
  vector_db: faiss        # faiss | chromadb
  chunk_size: 512
  chunk_overlap: 64

output:
  format: json            # json | csv
  dir: ./output
```

---

## 6. 자주 묻는 문제

**Q. `opendataloader-pdf` 실행 오류**
- Java가 설치되어 있는지 확인: `java -version`
- JRE 11 이상 필요

**Q. 임베딩 모델 첫 실행이 느림**
- 첫 실행 시 HuggingFace에서 모델을 자동 다운로드합니다 (~90MB)
- 이후 `.cache/huggingface/`에 캐시되어 빠릅니다

**Q. KIPRIS 검색 결과 없음**
- KIPRIS API 키는 https://www.kipris.or.kr 에서 신청
- 키 없으면 KIPRIS는 자동으로 skip됩니다

**Q. 할루시네이션 검증 실패 (`paragraph_verified: false`)**
- 문서 전문이 캐시에 없을 때 발생 (abstract만 저장된 경우)
- `--no-llm` 옵션으로 단락 추출 단계를 생략할 수 있습니다
