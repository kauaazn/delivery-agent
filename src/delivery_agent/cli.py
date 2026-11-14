"""Terminal chat with the assistant:  python -m delivery_agent"""
from __future__ import annotations

import json

from .agent import Agent
from .auth import ensure_api_key
from .config import Settings
from .prompts import SYSTEM_PROMPT
from .shop import Shop


def ask_confirmation(tool_name: str, args: dict) -> bool:
    print(f"\n  The assistant wants to run: {tool_name} {json.dumps(args, ensure_ascii=False)}")
    return input("  Confirm? [y/N] ").strip().lower() in {"y", "yes", "s", "sim"}


def main() -> int:
    settings = Settings.from_env()
    if not ensure_api_key():
        print("ANTHROPIC_API_KEY is not set.")
        print('PowerShell:  $env:ANTHROPIC_API_KEY = "<your key>"')
        return 1

    import anthropic  # imported here so the tests need neither a key nor network

    agent = Agent(
        anthropic.Anthropic(),
        Shop(),
        model=settings.model,
        system=SYSTEM_PROMPT,
        confirm=ask_confirmation,
        max_steps=settings.max_steps,
        fallbacks=settings.enable_fallbacks,
    )
    print(f"Delivery assistant ({settings.model}). Type 'exit' to quit.\n")
    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if user_text.lower() in {"exit", "quit", "sair"}:
            return 0
        if not user_text:
            continue
        try:
            print(f"assistant> {agent.chat(user_text)}\n")
        except anthropic.APIError as exc:
            print(f"[Claude API error] {exc}\n")
