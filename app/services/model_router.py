from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Literal


Complexity = Literal["cheap", "default", "strong"]


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str
    tier: Complexity
    reason: str


AGENT_MODEL_RULES: Dict[str, Dict[Complexity, str]] = {
    "supervisor": {
        "cheap": "local-heuristic",
        "default": "deepseek-chat",
        "strong": "gpt-4.1",
    },
    "learning": {
        "cheap": "local-heuristic",
        "default": "gemini-2.5-flash",
        "strong": "gpt-4.1",
    },
    "ppt": {
        "cheap": "local-heuristic",
        "default": "gemini-2.5-flash",
        "strong": "claude-sonnet-4.5",
    },
    "frontier": {
        "cheap": "local-heuristic",
        "default": "deepseek-chat",
        "strong": "gemini-2.5-pro",
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
