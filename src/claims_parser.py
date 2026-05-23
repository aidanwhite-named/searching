import re
from dataclasses import dataclass, field


@dataclass
class ClaimNode:
    number: int
    text: str
    parents: list = field(default_factory=list)
    children: list = field(default_factory=list)

    @property
    def is_independent(self) -> bool:
        return len(self.parents) == 0


# ── 청구항 번호 헤더 패턴 ──────────────────────────────────────────────────────

# 한국어: "청구항 1", "[청구항 1]"
_KR_CLAIM_HEADER = re.compile(r"^\s*\[?청구항\s+(\d+)\]?\s*$", re.MULTILINE)

# 영어: "1." (줄 시작)
_EN_CLAIM_HEADER = re.compile(r"^\s*(\d+)\.\s+\S", re.MULTILINE)

# ── 종속 관계 패턴 ─────────────────────────────────────────────────────────────

# 한국어 범위: "청구항 1 내지 (청구항) 3"
_KR_RANGE = re.compile(r"청구항\s+(\d+)\s*내지\s*청구항?\s+(\d+)")

# 한국어 나열: "청구항 1 또는 (청구항) 3" / "청구항 1, 2 또는 3"
_KR_LIST = re.compile(r"청구항\s+([\d,\s]+(?:또는\s*\d+)?)\s*에\s*(?:있어서|따른|의)")

# 한국어 단일 종속
_KR_SINGLE = re.compile(r"청구항\s+(\d+)\s*에\s*(?:있어서|따른|의)")

# 영어 범위: "claims 1-3" / "claims 1 to 3" / "claims 1 through 3"
_EN_RANGE = re.compile(r"claims?\s+(\d+)\s*(?:-|to|through)\s*(\d+)", re.IGNORECASE)

# 영어 나열: "claim 1 or 3" / "claim 1, 2, or 3"
_EN_LIST = re.compile(r"claims?\s+([\d,\s]+(?:or\s*\d+)?)\s*,?\s*wherein", re.IGNORECASE)

# 영어 단일: "claim 1, wherein" / "claim 1, further"
_EN_SINGLE = re.compile(r"claim\s+(\d+)\s*,", re.IGNORECASE)


def _extract_numbers_from_list(raw: str) -> list[int]:
    """'1, 2 또는 3' 또는 '1, 2, or 3' 같은 문자열에서 번호 목록 추출."""
    return [int(n) for n in re.findall(r"\d+", raw)]


def _expand_range(start: int, end: int) -> list[int]:
    return list(range(min(start, end), max(start, end) + 1))


def _find_parents(claim_text: str) -> list[int]:
    """청구항 본문에서 인용하는 부모 번호 목록 추출."""

    # 한국어 범위 (내지)
    m = _KR_RANGE.search(claim_text)
    if m:
        return _expand_range(int(m.group(1)), int(m.group(2)))

    # 영어 범위 (- / to / through)
    m = _EN_RANGE.search(claim_text)
    if m:
        return _expand_range(int(m.group(1)), int(m.group(2)))

    # 한국어 나열
    m = _KR_LIST.search(claim_text)
    if m:
        nums = _extract_numbers_from_list(m.group(1))
        if nums:
            return nums

    # 영어 나열
    m = _EN_LIST.search(claim_text)
    if m:
        nums = _extract_numbers_from_list(m.group(1))
        if nums:
            return nums

    # 한국어 단일
    m = _KR_SINGLE.search(claim_text)
    if m:
        return [int(m.group(1))]

    # 영어 단일
    m = _EN_SINGLE.search(claim_text)
    if m:
        return [int(m.group(1))]

    return []


class ClaimsParser:
    def parse(self, claims_markdown: str) -> dict:
        """청구범위 Markdown을 파싱하여 {번호: ClaimNode} 딕셔너리 반환."""
        segments = self._split_into_segments(claims_markdown)
        if not segments:
            return {}

        nodes: dict[int, ClaimNode] = {}
        for num, text in segments:
            parents = _find_parents(text)
            nodes[num] = ClaimNode(number=num, text=text.strip(), parents=parents)

        # children 역방향 채우기
        for num, node in nodes.items():
            for p in node.parents:
                if p in nodes:
                    nodes[p].children.append(num)

        return nodes

    def _split_into_segments(self, text: str) -> list[tuple[int, str]]:
        """텍스트를 (번호, 본문) 리스트로 분리. 한국어/영어 자동 감지."""
        # 한국어 헤더 우선 시도
        kr_matches = list(_KR_CLAIM_HEADER.finditer(text))
        if kr_matches:
            return self._extract_segments(text, kr_matches)

        # 영어 헤더 시도
        en_matches = list(_EN_CLAIM_HEADER.finditer(text))
        if en_matches:
            return self._extract_segments(text, en_matches)

        return []

    def _extract_segments(self, text: str, matches: list) -> list[tuple[int, str]]:
        segments = []
        for i, m in enumerate(matches):
            num = int(m.group(1))
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
            segments.append((num, body))
        return segments

    def render_tree(self, nodes: dict) -> str:
        """의존성 트리를 CLI 출력용 문자열로 렌더링."""
        if not nodes:
            return "(청구항 파싱 결과 없음)"
        lines = []
        rendered: set[int] = set()
        roots = [n for n in nodes.values() if n.is_independent]
        for root in roots:
            lines.append(f"  [{root.number}] 독립항")
            rendered.add(root.number)
            self._render_children(nodes, root.number, lines, depth=1, rendered=rendered)
        return "\n".join(lines)

    def _render_children(self, nodes: dict, parent_num: int, lines: list, depth: int, rendered: set):
        node = nodes.get(parent_num)
        if not node:
            return
        for child_num in node.children:
            if child_num in rendered:
                continue
            child = nodes.get(child_num)
            if not child:
                continue
            rendered.add(child_num)
            indent = "  " + "  " * depth
            parent_label = ", ".join(str(p) for p in child.parents)
            lines.append(f"{indent}└─ [{child.number}] → {parent_label}")
            self._render_children(nodes, child_num, lines, depth + 1, rendered)
