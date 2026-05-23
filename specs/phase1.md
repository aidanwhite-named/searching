# Phase 1 Spec: CLI 설정 관리자 & LLM 라우터

## 목표
`config.yaml` 기반 설정 관리 및 LLM 라우터 구현.
API 키가 있으면 해당 API 호출, 없으면 로컬 CLI 도구로 subprocess fallback.

---

## 파일 구조

```
D:\Searching\
├── config.yaml          # 사용자 설정 (gitignore 권장)
├── main.py              # CLI 진입점
├── requirements.txt     # 의존성
├── specs/
│   └── phase1.md        # 이 파일
└── src/
    ├── __init__.py
    ├── config_manager.py
    └── llm_router.py
```

---

## config.yaml 스키마

```yaml
llm:
  agent: claude           # claude | gemini | openai
  model: claude-opus-4-7  # 선택된 에이전트의 모델명
  api_key: ""             # 비어있으면 CLI fallback 사용

search:
  kipris_api_key: ""
  max_results: 20

rag:
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
  vector_db: faiss        # faiss | chromadb
  chunk_size: 512
  chunk_overlap: 64

output:
  format: json            # json | csv
  dir: ./output
```

---

## ConfigManager 인터페이스

```python
class ConfigManager:
    def __init__(path: str = "config.yaml")
    def get(self, *keys, default=None) -> Any       # config.get('llm', 'agent')
    def set(self, *keys, value) -> None             # config.set('llm', 'api_key', value=key)
    def save(self) -> None                          # config.yaml에 기록
    def setup_wizard(self) -> None                  # 대화형 CLI 설정
```

---

## LLMRouter 인터페이스

```python
class LLMRouter:
    def __init__(config: ConfigManager)
    def call(self, prompt: str, system: str = None, max_tokens: int = 4096) -> str
    def test_connection(self) -> bool               # "OK" 응답 확인
```

### 라우팅 규칙

| 조건 | 동작 |
|------|------|
| `api_key` 비어있지 않음 | 해당 에이전트 API 직접 호출 |
| `api_key` 비어있음 | subprocess로 CLI 도구 fallback |

### 지원 에이전트 & CLI 명령

| agent | API 클라이언트 | CLI fallback 명령 |
|-------|--------------|-----------------|
| claude | `anthropic` | `claude -p "<prompt>"` |
| gemini | `google-generativeai` | `gemini -p "<prompt>"` |
| openai | `openai` | `gpt "<prompt>"` |

---

## main.py CLI 명령

```
python main.py config           # 현재 설정 출력
python main.py config --setup   # 대화형 설정 마법사
python main.py test             # LLM 연결 테스트
```

---

## 검증 기준

- [x] `config.yaml` 없으면 기본값으로 자동 생성
- [x] `config --setup`으로 에이전트/모델/API키 설정 저장 가능
- [x] API 키 있을 때: 해당 API 정상 호출 (코드 구현 완료)
- [x] API 키 없을 때: subprocess CLI fallback, FileNotFoundError 시 명확한 메시지 출력
- [x] `test` 명령으로 연결 성공/실패 출력

## 구현 완료: 2026-05-23
