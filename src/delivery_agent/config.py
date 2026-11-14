"""Runtime settings, read from environment variables. Keys are never hardcoded."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "claude-opus-5-5"


@dataclass(frozen=True)
class Settings:
    model: str = DEFAULT_MODEL
    max_steps: int = 8
    enable_fallbacks: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            model=os.environ.get("AGENT_MODEL", DEFAULT_MODEL),
            max_steps=int(os.environ.get("AGENT_MAX_STEPS", cls.max_steps)),
            enable_fallbacks=os.environ.get("ENABLE_FALLBACKS", "1").lower() not in {"0", "false", "no"},
        )
