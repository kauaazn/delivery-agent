"""Where the API key comes from: the environment, or a masked prompt, and never anywhere else."""
import os
import sys

import pytest

from delivery_agent import auth

KEY = "sk-ant-api03-" + "a" * 90  # shaped like a real key (about 100 characters), but not a real one


class FakeStdin:
    def __init__(self, interactive: bool) -> None:
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


class FakeMsvcrt:
    """The Windows console, typing a scripted string one character at a time."""

    def __init__(self, typed: str) -> None:
        self._chars = iter(typed)

    def getwch(self) -> str:
        return next(self._chars)


def answering(*answers):
    """A stand-in for the prompt that gives each answer in turn."""
    remaining = iter(answers)
    return lambda prompt="": next(remaining)


def fail_if_asked(*_args, **_kwargs):
    raise AssertionError("the key must not be asked for here")


@pytest.fixture(autouse=True)
def no_key_in_the_environment(monkeypatch):
    # set-then-delete makes monkeypatch undo whatever the code under test puts in os.environ
    monkeypatch.setenv(auth.ENV_VAR, "placeholder")
    monkeypatch.delenv(auth.ENV_VAR)


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeStdin(interactive=True))


def test_a_key_already_in_the_environment_is_used_without_asking(monkeypatch):
    monkeypatch.setenv(auth.ENV_VAR, KEY)
    assert auth.ensure_api_key(read_secret=fail_if_asked) is True


def test_nothing_is_asked_when_there_is_no_terminal(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeStdin(interactive=False))
    assert auth.ensure_api_key(read_secret=fail_if_asked) is False
    assert auth.ENV_VAR not in os.environ


def test_in_a_terminal_the_key_is_asked_and_kept_only_in_this_process(terminal, capsys):
    assert auth.ensure_api_key(read_secret=answering(f"  {KEY} \n")) is True
    assert os.environ[auth.ENV_VAR] == KEY  # trimmed
    shown = capsys.readouterr()
    assert KEY not in shown.out + shown.err  # never printed


def test_quotes_around_the_pasted_key_are_dropped(terminal):
    assert auth.ensure_api_key(read_secret=answering(f'"{KEY}"')) is True
    assert os.environ[auth.ENV_VAR] == KEY


def test_an_empty_answer_means_there_is_no_key(terminal):
    assert auth.ensure_api_key(read_secret=answering("   ")) is False
    assert auth.ENV_VAR not in os.environ


def test_two_keys_pasted_together_are_rejected_and_asked_again(terminal, capsys):
    assert auth.ensure_api_key(read_secret=answering(KEY + KEY, KEY)) is True
    assert os.environ[auth.ENV_VAR] == KEY
    shown = capsys.readouterr().out
    assert "two keys" in shown and KEY not in shown


def test_text_that_is_not_an_anthropic_key_is_rejected_with_its_length(terminal, capsys):
    assert auth.ensure_api_key(read_secret=answering("x" * 38, KEY)) is True
    assert "38 characters" in capsys.readouterr().out


def test_a_key_that_was_cut_short_is_rejected_with_its_length(terminal, capsys):
    assert auth.ensure_api_key(read_secret=answering("sk-ant-api03-abc", KEY)) is True
    assert "only 16 characters" in capsys.readouterr().out


def test_it_gives_up_after_three_bad_pastes(terminal):
    assert auth.ensure_api_key(read_secret=answering(*[KEY + KEY] * 3)) is False
    assert auth.ENV_VAR not in os.environ


def test_the_masked_prompt_shows_one_asterisk_per_character_and_never_the_key(monkeypatch, capsys):
    monkeypatch.setattr(auth, "IS_WINDOWS", True)
    # a, b, backspace, c, an arrow key (two codes), a stray control character, d, Enter
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt("ab\bc\xe0H\x16d\r"))
    assert auth.read_masked("key: ") == "acd"
    shown = capsys.readouterr().out
    assert shown == "key: **\b \b**\n"
    assert "acd" not in shown


def test_the_evals_runner_says_how_to_set_a_key_when_there_is_none(monkeypatch, capsys):
    from evals.run import main

    monkeypatch.setattr(sys, "stdin", FakeStdin(interactive=False))
    assert main(["--only", "vegan"]) == 1
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out


def test_the_chat_says_how_to_set_a_key_when_there_is_none(monkeypatch, capsys):
    from delivery_agent.cli import main

    monkeypatch.setattr(sys, "stdin", FakeStdin(interactive=False))
    assert main() == 1
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out
