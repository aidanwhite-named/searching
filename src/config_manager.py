import os
import yaml

DEFAULT_CONFIG = {
    "llm": {
        "agent": "claude",
        "model": "claude-haiku-4-5",
        "api_key": "",
    },
    "search": {
        "kipris_api_key": "",
        "max_results": 20,
    },
    "rag": {
        "embedding_model": "BAAI/bge-m3",
        "vector_db": "qdrant",
        "store_mode": "memory",   # "memory"(세션 인메모리) | "local"(디스크 영구 저장)
        "chunk_size": 512,
        "chunk_overlap": 64,
    },
    "output": {
        "format": "json",
        "dir": "./output",
    },
}

AGENT_DEFAULT_MODELS = {
    "codex":  "gpt-4o-mini",
    "claude": "claude-haiku-4-5",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
}


class ConfigManager:
    def __init__(self, path: str = "config.yaml"):
        self.path = path
        self.config = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            self.config = DEFAULT_CONFIG
            self.save()
            print(f"[config] 기본 설정 파일 생성: {self.path}")
            return DEFAULT_CONFIG
        with open(self.path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        return self._merge(DEFAULT_CONFIG, loaded)

    def _merge(self, base: dict, override: dict) -> dict:
        result = dict(base)
        for k, v in override.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k] = self._merge(result[k], v)
            else:
                result[k] = v
        return result

    def get(self, *keys, default=None):
        val = self.config
        for key in keys:
            if isinstance(val, dict):
                val = val.get(key, default)
            else:
                return default
        return val

    def set(self, *keys, value):
        d = self.config
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True)

    def show(self):
        print(f"\n=== 현재 설정 ({self.path}) ===")
        agent = self.get("llm", "agent")
        model = self.get("llm", "model")
        api_key = self.get("llm", "api_key", default="")
        key_display = f"{api_key[:8]}..." if api_key else "(없음, CLI fallback 사용)"
        mode = "API" if api_key else "CLI fallback"
        print(f"  LLM 에이전트 : {agent}")
        print(f"  모델         : {model}")
        print(f"  API 키       : {key_display}")
        print(f"  통신 모드    : {mode}")
        print(f"  검색 최대 수 : {self.get('search', 'max_results')}")
        print(f"  벡터 DB      : {self.get('rag', 'vector_db')}")
        print(f"  출력 형식    : {self.get('output', 'format')}")
        print()

    def setup_wizard(self):
        print("\n=== 설정 마법사 ===")
        print("Enter를 누르면 현재 값 유지.\n")

        # 에이전트 선택
        current_agent = self.get("llm", "agent")
        agents = list(AGENT_DEFAULT_MODELS.keys())
        print(f"LLM 에이전트 선택 {agents} (현재: {current_agent}): ", end="")
        inp = input().strip().lower()
        if inp and inp in agents:
            self.set("llm", "agent", value=inp)
            # 모델도 기본값으로 리셋
            self.set("llm", "model", value=AGENT_DEFAULT_MODELS[inp])
        agent = self.get("llm", "agent")

        # 모델 입력
        current_model = self.get("llm", "model")
        print(f"모델명 (현재: {current_model}): ", end="")
        inp = input().strip()
        if inp:
            self.set("llm", "model", value=inp)

        # API 키 입력
        current_key = self.get("llm", "api_key", default="")
        key_display = f"{current_key[:8]}..." if current_key else "(없음)"
        print(f"API 키 (현재: {key_display}, 비워두면 CLI fallback): ", end="")
        inp = input().strip()
        if inp:
            self.set("llm", "api_key", value=inp)
        elif not inp and current_key:
            print("  → 기존 API 키 유지")

        # KIPRIS API 키
        current_kipris = self.get("search", "kipris_api_key", default="")
        kipris_display = f"{current_kipris[:8]}..." if current_kipris else "(없음)"
        print(f"KIPRIS API 키 (현재: {kipris_display}): ", end="")
        inp = input().strip()
        if inp:
            self.set("search", "kipris_api_key", value=inp)

        # 벡터 DB 선택
        current_vdb = self.get("rag", "vector_db")
        print(f"벡터 DB [qdrant] (현재: {current_vdb}): ", end="")
        inp = input().strip().lower()
        if inp == "qdrant":
            self.set("rag", "vector_db", value=inp)

        # 출력 형식
        current_fmt = self.get("output", "format")
        print(f"출력 형식 [json|csv] (현재: {current_fmt}): ", end="")
        inp = input().strip().lower()
        if inp in ("json", "csv"):
            self.set("output", "format", value=inp)

        self.save()
        print(f"\n[config] 설정 저장 완료: {self.path}")
        self.show()
