"""Where the API key comes from. The program never stores it: not in code, not in files, not on the command line."""
from __future__ import annotations

import getpass
import os
import sys
from typing import Callable

ENV_VAR = "ANTHROPIC_API_KEY"
IS_WINDOWS = os.name == "nt"
MAX_TRIES = 3


def read_masked(prompt: str) -> str:
    """Read a secret from the terminal, showing one '*' per character: a paste is visible, the key is not.

    On Windows this reads the console key by key. Elsewhere it falls back to getpass, which shows nothing.
    """
    if not IS_WINDOWS:
        return getpass.getpass(prompt)
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    typed: list[str] = []
    while True:
        char = msvcrt.getwch()
        if char in ("\r", "\n"):
            break
        if char == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        if char in ("\x00", "\xe0"):  # arrow and function keys arrive as two codes: skip the second one
            msvcrt.getwch()
        elif char == "\b":  # backspace
            if typed:
                typed.pop()
                sys.stdout.write("\b \b")
        elif ord(char) >= 32:  # ignore any other control character
            typed.append(char)
            sys.stdout.write("*")
        sys.stdout.flush()
    sys.stdout.write("\n")
    return "".join(typed)


def problem_with(key: str) -> str | None:
    """A mistake that is easy to spot without calling the API: the key pasted twice, or some other text."""
    if any(char.isspace() for char in key):
        return "The key has spaces in it."
    if key.count("sk-ant-") > 1:
        return "That looks like two keys pasted together."
    if not key.startswith("sk-ant-"):
        return f"That is {len(key)} characters and does not start with sk-ant-, so it is not an Anthropic API key."
    if len(key) < 40:
        return f"That is only {len(key)} characters; a full key has about 100."
    return None


def ensure_api_key(
    prompt: str = "Paste your Anthropic API key once and press Enter (you will only see asterisks): ",
    read_secret: Callable[[str], str] = read_masked,
) -> bool:
    """Make sure ANTHROPIC_API_KEY is available to this process.

    If it is already in the environment, nothing happens. Otherwise, in an interactive terminal, the key is asked
    for with a masked prompt and kept in this process's memory only. Returns False when there is no key (not an
    interactive terminal, an empty answer, or too many bad pastes), so the caller can explain how to set one.
    """
    if os.environ.get(ENV_VAR):
        return True
    if not sys.stdin.isatty():
        return False
    for _ in range(MAX_TRIES):
        key = read_secret(prompt).strip().strip("\"'").strip()
        if not key:
            return False
        problem = problem_with(key)
        if problem is None:
            os.environ[ENV_VAR] = key
            return True
        print(f"{problem} Paste it just once and press Enter.")
    return False
