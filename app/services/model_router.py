from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Literal


Complexity = Literal["cheap", "default", "strong"]


BASE_DIR = Path(__file__).resolve().parents[2]


def load_local_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_env()


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    tier: Complexity
    reason: str


AGENT_MODEL_RULES: Dict[str, Dict[Complexity, str]] = {
    "supervisor": {
        "cheap": "deepseek-v4-flash",
        "default": "deepseek-v4-flash",
        "strong": "deepseek-v4-flash",
    },
    "learning": {
        "cheap": "deepseek-v4-flash",
        "default": "deepseek-v4-flash",
        "strong": "deepseek-v4-flash",
    },
    "ppt": {
        "cheap": "local-heuristic",
        "default": "gemini-2.5-flash",
        "strong": "claude-sonnet-4.5",
    },
    "frontier": {
        "cheap": "deepseek-v4-flash",
        "default": "deepseek-v4-flash",
        "strong": "deepseek-v4-flash",
    },
}


def choose_model(agent_id: str, complexity: Complexity = "default", needs_file: bool = False, uses_rag: bool = False) -> ModelChoice:
    tier: Complexity = complexity
    if needs_file or uses_rag and complexity == "cheap":
        tier = "default"

    model = AGENT_MODEL_RULES.get(agent_id, AGENT_MODEL_RULES["supervisor"]).get(tier, "local-heuristic")
    provider = "local"
    if model.startswith("gpt"):
        provider = "openai" if os.getenv("OPENAI_API_KEY") else "local"
    elif model.startswith("gemini"):
        provider = "gemini" if os.getenv("GEMINI_API_KEY") else "local"
    elif model.startswith("claude"):
        provider = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "local"
    elif model.startswith("deepseek"):
        provider = "deepseek" if os.getenv("DEEPSEEK_API_KEY") else "local"

    if provider == "local":
        model = "local-heuristic"

    return ModelChoice(provider=provider, model=model, tier=tier, reason=f"{agent_id}:{tier}")


class LocalHeuristicModel:
    def summarize(self, prompt: str, max_items: int = 5) -> str:
        sentences = [part.strip() for part in prompt.replace("\n", "。").split("。") if part.strip()]
        return "；".join(sentences[:max_items]) or "暂无可总结内容。"


local_model = LocalHeuristicModel()


class DeepSeekClient:
    base_url = "https://api.deepseek.com/chat/completions"

    def __init__(self) -> None:
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, system: str, user: str, temperature: float = 0.2, max_tokens: int = 1200) -> str:
        if not self.available:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"DeepSeek API error {exc.code}: {body}") from exc
        return data["choices"][0]["message"]["content"].strip()

    def chat_json(self, system: str, user: str, temperature: float = 0.2, max_tokens: int = 1800) -> Dict:
        content = self.chat(system, user, temperature=temperature, max_tokens=max_tokens)
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned.removeprefix("json").strip()
        return json.loads(cleaned)


deepseek_client = DeepSeekClient()
