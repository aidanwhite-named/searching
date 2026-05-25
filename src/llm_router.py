import os
import shutil
import subprocess
import sys

from src.config_manager import ConfigManager


def _resolve(name: str) -> str:
    """
    CLI 실행 파일의 전체 경로를 확정한다.
    서버 subprocess 환경에서 PATH가 달라도 안전하도록,
    모듈 로드 시점(서버 기동 시)에 경로를 한 번만 탐색해 캐싱.
    Windows: .cmd 우선 탐색 → 없으면 이름 그대로 반환.
    """
    # .cmd 확장자 우선 (Windows npm CLI)
    found = shutil.which(name + ".cmd") or shutil.which(name)
    return found or name


# 모듈 로드 시 한 번만 경로 탐색
_RESOLVED: dict[str, str] = {
    "codex":  _resolve("codex"),
    "claude": _resolve("claude"),
    "gemini": _resolve("gemini"),
    "gpt":    _resolve("gpt"),
}


class LLMRouter:
    def __init__(self, config: ConfigManager):
        self.agent   = config.get("llm", "agent")
        self.model   = config.get("llm", "model")
        self.api_key = config.get("llm", "api_key", default="") or ""

    @property
    def mode(self) -> str:
        return "api" if self.api_key else "cli"

    # ── 공개 API ──────────────────────────────────────────────────────

    def call(self, prompt: str, system: str = None, max_tokens: int = 4096, timeout: int = 120) -> str:
        if self.api_key:
            return self._call_api(prompt, system, max_tokens)
        return self._call_cli(prompt, timeout=timeout)

    def test_connection(self) -> bool:
        try:
            resp = self.call("Respond with the single word OK and nothing else.")
            ok = "OK" in resp
            status = "success" if ok else f"failed (response: {resp[:80]})"
            print(f"[test] {self.agent} ({self.mode}) connection {status}")
            return ok
        except Exception as e:
            print(f"[test] connection failed: {e}")
            return False

    # ── API 모드 ──────────────────────────────────────────────────────

    def _call_api(self, prompt: str, system: str, max_tokens: int) -> str:
        dispatch = {
            "claude": self._claude_api,
            "gemini": self._gemini_api,
            "openai": self._openai_api,
        }
        handler = dispatch.get(self.agent)
        if handler is None:
            raise ValueError(f"API mode not supported for agent: {self.agent}")
        return handler(prompt, system, max_tokens)

    def _claude_api(self, prompt, system, max_tokens):
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")
        client = anthropic.Anthropic(api_key=self.api_key)
        kwargs = {"model": self.model, "max_tokens": max_tokens,
                  "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        return client.messages.create(**kwargs).content[0].text

    def _gemini_api(self, prompt, system, max_tokens):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("pip install google-generativeai")
        genai.configure(api_key=self.api_key)
        model = genai.GenerativeModel(self.model)
        full = f"{system}\n\n{prompt}" if system else prompt
        return model.generate_content(
            full, generation_config={"max_output_tokens": max_tokens}
        ).text

    def _openai_api(self, prompt, system, max_tokens):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai")
        client = OpenAI(api_key=self.api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return client.chat.completions.create(
            model=self.model, messages=messages, max_tokens=max_tokens
        ).choices[0].message.content

    # ── CLI fallback 모드 ─────────────────────────────────────────────

    def _build_cmd(self, prompt: str) -> tuple[list[str], bytes | None]:
        """
        (cmd, stdin_bytes) 반환.
        stdin_bytes가 None이 아니면 프롬프트를 stdin으로 전달 (Windows 명령줄 길이 제한 우회).
        """
        exe = _RESOLVED.get(self.agent)
        if not exe:
            raise ValueError(f"CLI fallback not supported for agent: {self.agent}")

        if self.agent == "gemini":
            # 프롬프트를 stdin으로 전달 → Windows WinError 206(명령줄 너무 김) 방지
            # -p ""  : 비대화형 모드 활성화. stdin 내용이 실제 프롬프트로 사용됨.
            # --approval-mode yolo: 도구 실행 자동 승인 (subprocess 환경에서 대기 방지)
            return [exe, "--approval-mode", "yolo", "-p", ""], prompt.encode("utf-8")
        if self.agent == "claude":
            return [exe, "-p", prompt], None
        if self.agent in ("openai", "gpt"):
            cmd = [exe, "-m", self.model, "-p", prompt] if self.model else [exe, "-p", prompt]
            return cmd, None
        # codex
        return [exe, "-p", prompt], None

    def _call_cli(self, prompt: str, timeout: int = 120) -> str:
        cmd, stdin_bytes = self._build_cmd(prompt)

        # PATH를 현재 프로세스에서 그대로 상속시켜 subprocess에 전달
        env = os.environ.copy()
        # Gemini CLI 색상 감지 경고 제거 및 비대화형 환경 명시
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("NO_COLOR", "1")

        # 홈 디렉토리에서 실행 — 프로젝트 폴더(CLAUDE.md 등)를 읽지 않도록.
        # Gemini/Claude CLI가 작업 디렉토리의 컨텍스트 파일을 로드해 엉뚱한 응답을
        # 내놓는 문제를 방지한다.
        cwd = os.path.expanduser("~")

        # Windows: .cmd 파일은 반드시 cmd.exe /c 를 통해 실행해야 함
        if sys.platform == "win32":
            comspec = env.get("COMSPEC", "cmd.exe")
            run_kwargs = {
                "args":  [comspec, "/c"] + cmd,
                "shell": False,
                "env":   env,
                "cwd":   cwd,
            }
        else:
            run_kwargs = {"args": cmd, "shell": False, "env": env, "cwd": cwd}

        try:
            result = subprocess.run(
                **run_kwargs,
                input=stdin_bytes,
                capture_output=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                f"CLI tool '{cmd[0]}' was not found. "
                f"설치 여부 확인: {self.agent}"
            )

        # Windows 한국어 환경(CP949)·UTF-8 모두 안전하게 디코딩
        def _decode(b: bytes | None) -> str:
            if not b:
                return ""
            for enc in ("utf-8", "cp949", "euc-kr"):
                try:
                    return b.decode(enc)
                except UnicodeDecodeError:
                    continue
            return b.decode("utf-8", errors="replace")

        stdout = _decode(result.stdout)
        stderr = _decode(result.stderr)

        if result.returncode != 0:
            raise RuntimeError(
                f"CLI 오류 (exit {result.returncode}):\n{stderr.strip()}"
            )
        # 정상 종료인데 stdout이 비어있으면 stderr를 노출 (디버깅용)
        if not stdout.strip() and stderr.strip():
            print(f"[llm_router] 빈 응답 — stderr: {stderr.strip()[:300]}")
        return stdout.strip()
