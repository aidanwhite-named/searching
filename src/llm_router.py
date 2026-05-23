import subprocess
from src.config_manager import ConfigManager


class LLMRouter:
    # CLI fallback 명령 템플릿
    _CLI_COMMANDS = {
        "claude": lambda p: ["claude", "-p", p],
        "gemini": lambda p: ["gemini", "-p", p],
        "openai": lambda p: ["gpt", p],
    }

    def __init__(self, config: ConfigManager):
        self.agent = config.get("llm", "agent")
        self.model = config.get("llm", "model")
        self.api_key = config.get("llm", "api_key", default="") or ""

    @property
    def mode(self) -> str:
        return "api" if self.api_key else "cli"

    def call(self, prompt: str, system: str = None, max_tokens: int = 4096) -> str:
        if self.api_key:
            return self._call_api(prompt, system, max_tokens)
        return self._call_cli(prompt)

    def test_connection(self) -> bool:
        try:
            resp = self.call("Respond with the single word OK and nothing else.")
            ok = "OK" in resp
            status = "성공" if ok else f"실패 (응답: {resp[:80]})"
            print(f"[test] {self.agent} ({self.mode}) 연결 {status}")
            return ok
        except Exception as e:
            print(f"[test] 연결 실패: {e}")
            return False

    # ── API 라우팅 ──────────────────────────────────────────────────────────────

    def _call_api(self, prompt: str, system: str, max_tokens: int) -> str:
        dispatch = {
            "claude": self._claude_api,
            "gemini": self._gemini_api,
            "openai": self._openai_api,
        }
        handler = dispatch.get(self.agent)
        if handler is None:
            raise ValueError(f"지원하지 않는 에이전트: {self.agent}")
        return handler(prompt, system, max_tokens)

    def _claude_api(self, prompt: str, system: str, max_tokens: int) -> str:
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")
        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        response = client.messages.create(**kwargs)
        return response.content[0].text

    def _gemini_api(self, prompt: str, system: str, max_tokens: int) -> str:
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("pip install google-generativeai")
        genai.configure(api_key=self.api_key)
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        model = genai.GenerativeModel(self.model)
        response = model.generate_content(
            full_prompt,
            generation_config={"max_output_tokens": max_tokens},
        )
        return response.text

    def _openai_api(self, prompt: str, system: str, max_tokens: int) -> str:
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai")
        client = OpenAI(api_key=self.api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    # ── CLI fallback ────────────────────────────────────────────────────────────

    def _call_cli(self, prompt: str) -> str:
        builder = self._CLI_COMMANDS.get(self.agent)
        if builder is None:
            raise ValueError(f"CLI fallback 미지원 에이전트: {self.agent}")
        cmd = builder(prompt)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                f"CLI 도구 '{cmd[0]}'를 찾을 수 없습니다. "
                f"설치 여부를 확인하거나 config에서 API 키를 입력하세요."
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"CLI fallback 오류 (종료코드 {result.returncode}):\n{result.stderr.strip()}"
            )
        return result.stdout.strip()
