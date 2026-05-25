# 설치 및 실행 가이드

## 사전 요구사항

| 항목 | 버전 | 확인 방법 |
|------|------|-----------|
| Python | **3.11** | `python --version` |
| Java JRE | 11 이상 | `java -version` (PDF 파싱에 필요) |
| LLM | CLI 또는 API 키 | `gemini`, `claude`, `gpt` 중 하나 |

> ⚠️ Python 3.14는 일부 패키지와 충돌합니다. **반드시 3.11을 사용하세요.**

---

## 1. 처음 설치 (최초 1회)

### 1-1. venv 생성

```bat
cd D:\Searching
python -m venv .venv
```

### 1-2. 패키지 설치

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 첫 설치 시 `torch`, `sentence-transformers` 등 대용량 패키지가 설치됩니다 (수분 소요).

### 1-3. 초기 설정 (선택)

```bat
.venv\Scripts\python.exe main.py config --setup
```

설정 마법사가 실행됩니다. 아래 항목을 입력하세요:

| 항목 | 예시 | 비고 |
|------|------|------|
| LLM 에이전트 | `gemini` | gemini / claude / openai |
| 모델명 | `gemini-2.5-flash` | 에이전트별 모델 확인 필요 |
| API 키 | `AIza...` | 비워두면 로컬 CLI 사용 |
| KIPRIS API 키 | `...` | 없으면 KIPRIS 검색 skip |
| 출력 형식 | `json` | json 또는 csv |

---

## 2. 실행 방법

### 방법 A — 웹 대시보드 (추천)

```bat
start.bat
```

또는 터미널에서:

```bat
.venv\Scripts\python.exe server.py
```

브라우저에서 **http://127.0.0.1:8001** 접속

> 서버 시작 후 임베딩/리랭커 모델 로드까지 **20~40초** 소요됩니다 (이후 요청은 빠름).

---

### 방법 B — CLI

venv를 활성화하거나, `.venv\Scripts\python.exe`를 직접 사용합니다.

```bat
:: venv 활성화 (선택)
.venv\Scripts\activate

:: 설정 확인
python main.py config

:: LLM 연결 테스트
python main.py test

:: PDF 청구항 파싱
python main.py parse 특허.pdf --claims

:: 전체 파이프라인 한 번에
python main.py match 특허.pdf --out report.json

:: 단계별 실행
python main.py search 특허.pdf --out search.json
python main.py rag 특허.pdf --results search.json --out rag.json
python main.py match 특허.pdf --rag-results rag.json --out report.json
```

---

## 3. config.yaml 구조

```yaml
llm:
  agent: gemini           # gemini | claude | openai
  model: gemini-2.5-flash
  api_key: ""             # 비워두면 로컬 CLI 사용

search:
  kipris_api_key: ""      # KIPRIS Open API 키 (없으면 skip)
  epo_ops_key: ""         # EPO OPS 키
  epo_ops_secret: ""
  max_results: 20

rag:
  embedding_model: BAAI/bge-m3   # 다국어 임베딩 (1024dim)
  vector_db: qdrant
  store_mode: memory             # memory | local
  chunk_size: 512
  chunk_overlap: 64

output:
  format: json            # json | csv
  dir: ./output
```

---

## 4. 모델 다운로드 안내

최초 서버 실행 시 HuggingFace에서 모델을 자동 다운로드합니다.

| 모델 | 용도 | 크기 |
|------|------|------|
| `BAAI/bge-m3` | 임베딩 | ~570MB |
| `BAAI/bge-reranker-v2-m3` | 리랭킹 | ~570MB |

- 다운로드 위치: `C:\Users\<사용자>\.cache\huggingface\hub\`
- **최초 1회만** 다운로드, 이후 로컬 캐시에서 로드

---

## 5. 자주 묻는 문제

**Q. 서버가 시작은 됐는데 요청이 안 받아짐**
- 임베딩/리랭커 모델 로딩 중입니다. 20~40초 기다린 후 새로고침하세요.

**Q. `opendataloader-pdf` 오류**
- Java가 설치되어 있는지 확인: `java -version`
- JRE 11 이상 필요

**Q. KIPRIS 검색 결과 없음**
- KIPRIS API 키: https://www.kipris.or.kr 에서 신청
- 키 없으면 자동으로 skip됩니다

**Q. 할루시네이션 검증 실패 (`paragraph_verified: false`)**
- 문서 전문이 캐시에 없을 때 발생
- `--no-llm` 옵션으로 단락 추출 단계 생략 가능

**Q. Python 버전 충돌**
- `.venv`는 Python 3.11 고정 환경입니다
- 전역에 다른 Python 버전이 설치되어 있어도 영향 없음
