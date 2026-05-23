# Phase 2 Spec: PDF 전처리 & 청구항 의존성 파서

## 목표
특허 PDF를 입력받아 Markdown으로 변환하고, 기준일(우선권/출원일)과
청구항 의존성 트리를 추출하여 이후 Phase에서 사용할 구조화 데이터를 생성.

---

## 파일 구조 추가분

```
src/
├── pdf_parser.py          # PDF → Markdown (opendataloader-pdf)
├── patent_preprocessor.py # 기준일 추출 + 청구범위 섹션 슬라이싱
└── claims_parser.py       # 청구항 의존성 트리 파서
```

---

## PDFParser 인터페이스

```python
class PDFParser:
    def parse(self, pdf_path: str) -> str   # PDF → Markdown 전문 반환
```

### 동작
- `opendataloader_pdf.convert(format="markdown", reading_order="xycut")` 사용
- 다단(Multi-column) 레이아웃 → xycut 알고리즘으로 읽기 순서 보정
- 임시 디렉터리에 .md 파일 생성 후 읽어서 문자열 반환

---

## PatentPreprocessor 인터페이스

```python
class PatentPreprocessor:
    def process(self, pdf_path: str) -> PatentData
```

```python
@dataclass
class PatentData:
    reference_date: str        # "YYYY-MM-DD", 검색 컷오프
    date_type: str             # "priority" | "filing"
    claims_markdown: str       # 청구범위 섹션 원문 Markdown
    full_markdown: str         # 전체 Markdown (명세서 포함)
    title: str                 # 발명 명칭
```

### 기준일 추출 우선순위
1. 우선권 주장일 (`우선권주장`, `Priority Date`, `filed ...`)
2. 출원일 (`출원일`, `Filing Date`, `Application Date`)

### 청구범위 섹션 슬라이싱
- 한국어: `청구범위` ~ 다음 `##` 헤더 사이 추출
- 영어: `CLAIMS?` ~ 다음 `##` 헤더 사이 추출
- 슬라이싱 실패 시 전체 Markdown fallback (경고 출력)

---

## ClaimsParser 인터페이스

```python
class ClaimsParser:
    def parse(self, claims_markdown: str) -> dict[int, ClaimNode]
```

```python
@dataclass
class ClaimNode:
    number: int
    text: str                  # 청구항 전문
    parents: list[int]         # 직접 인용하는 청구항 번호 리스트
    children: list[int]        # 이 청구항을 인용하는 청구항 번호 리스트
    is_independent: bool       # parents가 비어 있으면 True
```

### 파싱 지원 형식

| 구분 | 한국어 예시 | 영어 예시 |
|------|------------|---------|
| 독립항 번호 | `청구항 1` | `1.` |
| 단일 종속 | `청구항 1에 있어서` | `claim 1, wherein` |
| 선택 종속 | `청구항 1 또는 3에 있어서` | `claim 1 or 3, wherein` |
| 범위 종속 | `청구항 1 내지 3 중 어느 하나에 있어서` | `any one of claims 1-3` |

---

## main.py 신규 명령

```
python main.py parse <pdf_path>   # 특허 PDF 파싱 결과 출력
```

출력 예시:
```
=== 특허 파싱 결과 ===
  발명 명칭  : 차세대 배터리 관리 시스템
  기준일     : 2022-03-15 (priority)
  청구항 수  : 15개 (독립항 3개, 종속항 12개)

  의존성 트리:
  [1] 독립항
    └─ [2] → 1
    └─ [3] → 2
  [4] 독립항
    └─ [5] → 4
    └─ [6] → 4 or 5
```

---

## 검증 기준

- [x] PDF → Markdown 변환 성공 (opendataloader-pdf, xycut 읽기 순서)
- [x] 청구범위 섹션 정확히 슬라이싱 (한/영 패턴, fallback 경고)
- [x] 우선권 주장일 있으면 해당 날짜 추출, 없으면 출원일
- [x] 독립항/종속항 번호 및 의존 관계 정확히 파싱 (한국어/영어)
- [x] 범위 종속항 (`내지`, `1-3`) 모든 부모 번호로 확장
- [x] `python main.py parse <pdf>` 명령 등록 완료
- [x] 다중 부모 종속항 트리 렌더링 중복 방지 (rendered 집합)

## 구현 완료: 2026-05-23
