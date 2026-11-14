"""Run the evaluation scenarios against the real Claude API and score them.

    python -m evals.run                        all scenarios
    python -m evals.run --only vegan           scenarios whose id contains "vegan"
    python -m evals.run --model claude-haiku-5-5

It spends real tokens: the estimate is printed at the end. The scoring code itself is covered by
offline tests (tests/test_evals.py), so what this run measures is the model's behaviour.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from delivery_agent.agent import Agent
from delivery_agent.clock import ManualClock
from delivery_agent.config import DEFAULT_MODEL, Settings
from delivery_agent.prompts import SYSTEM_PROMPT
from delivery_agent.shop import Shop

SCENARIOS_FILE = Path(__file__).with_name("scenarios.json")
# USD per million tokens (input, output), from the Claude API model table.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
EXPECTATION_KEYS = {"tools_called", "tools_not_called", "args_contain", "orders_total", "order_status"}


# --- measuring tokens -------------------------------------------------------------------------


class _Counted:
    def __init__(self, target: Any, meter: Meter) -> None:
        self._target = target
        self._meter = meter

    def create(self, **kwargs):
        response = self._target.create(**kwargs)
        usage = getattr(response, "usage", None)
        self._meter.calls += 1
        self._meter.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self._meter.output_tokens += getattr(usage, "output_tokens", 0) or 0
        return response


class Meter:
    """Wraps a Claude client and adds up the tokens it uses, on both endpoints."""

    def __init__(self, client: Any) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.messages = _Counted(client.messages, self)
        self.beta = SimpleNamespace(messages=_Counted(client.beta.messages, self))


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost in USD, or None when the model's price is not known."""
    if model not in PRICES:
        return None
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


# --- scoring ----------------------------------------------------------------------------------


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _matches(expected: Any, actual: Any) -> bool:
    """Does what the model sent satisfy what the scenario expects?"""
    if isinstance(expected, list):
        return isinstance(actual, list) and {_canonical(e) for e in expected} <= {_canonical(a) for a in actual}
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and float(actual) == float(expected)
    return str(actual).strip().lower() == str(expected).strip().lower()


def tool_calls_from(messages: list[dict]) -> list[tuple[str, dict]]:
    """Every tool call the model made, in order, read from the conversation."""
    calls = []
    for message in messages:
        if message["role"] != "assistant" or not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if getattr(block, "type", None) == "tool_use":
                calls.append((block.name, dict(block.input)))
    return calls


def check(expect: dict, calls: list[tuple[str, dict]], shop: Shop) -> list[str]:
    """Compare what happened with what the scenario expects. Returns the failures (empty = pass)."""
    failures = []
    names = [name for name, _ in calls]
    for tool in expect.get("tools_called", []):
        if tool not in names:
            failures.append(f"expected a call to {tool}")
    for tool in expect.get("tools_not_called", []):
        if tool in names:
            failures.append(f"{tool} should not have been called")
    for tool, wanted in expect.get("args_contain", {}).items():
        attempts = [args for name, args in calls if name == tool]
        if not any(all(_matches(value, args.get(key)) for key, value in wanted.items()) for args in attempts):
            failures.append(f"no call to {tool} had arguments containing {wanted}")
    if "orders_total" in expect and shop.order_count != expect["orders_total"]:
        failures.append(f"expected {expect['orders_total']} order(s) in the shop, found {shop.order_count}")
    for order_id, status in expect.get("order_status", {}).items():
        actual = shop.order_status(order_id)["status"]
        if actual != status:
            failures.append(f"order {order_id} should be {status}, but is {actual}")
    return failures


# --- running ----------------------------------------------------------------------------------


def load_scenarios(path: Path = SCENARIOS_FILE) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_shop(setup: dict | None) -> Shop:
    """A fresh shop, with the orders (and the elapsed time) a scenario starts from."""
    setup = setup or {}
    clock = ManualClock()
    shop = Shop(clock=clock)
    for order in setup.get("orders", []):
        shop.place_order([tuple(pair) for pair in order["items"]], order["zone"], order["customer_name"])
    clock.advance(setup.get("advance_minutes", 0))
    return shop


def run_scenario(scenario: dict, client: Any, *, model: str = DEFAULT_MODEL, fallbacks: bool = False) -> dict:
    shop = build_shop(scenario.get("setup"))
    meter = Meter(client)
    asked: list[str] = []

    def confirm(name: str, args: dict) -> bool:
        asked.append(name)
        return scenario.get("confirm", True)

    agent = Agent(meter, shop, model=model, system=SYSTEM_PROMPT, confirm=confirm, fallbacks=fallbacks)
    answers = [agent.chat(message) for message in scenario["user"]]
    calls = tool_calls_from(agent.messages)
    failures = check(scenario.get("expect", {}), calls, shop)
    return {
        "id": scenario["id"], "passed": not failures, "failures": failures,
        "tools": [name for name, _ in calls], "answer": answers[-1], "confirmations_asked": asked,
        "calls": meter.calls, "input_tokens": meter.input_tokens, "output_tokens": meter.output_tokens,
    }


def run_scenario_safely(scenario: dict, client: Any, **kwargs: Any) -> dict:
    """Like run_scenario, but an exception (API error, rejected request...) becomes a failed result."""
    try:
        return run_scenario(scenario, client, **kwargs)
    except Exception as exc:  # a crash is a result worth reporting, not the end of the whole run
        return {
            "id": scenario["id"], "passed": False, "failures": [f"crashed: {type(exc).__name__}: {exc}"],
            "tools": [], "answer": "", "confirmations_asked": [], "calls": 0, "input_tokens": 0, "output_tokens": 0,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the delivery agent against the scenarios.")
    parser.add_argument("--only", help="run only scenarios whose id contains this text")
    parser.add_argument("--model", default=None, help=f"model to evaluate (default: AGENT_MODEL or {DEFAULT_MODEL})")
    parser.add_argument("--no-fallbacks", action="store_true", help="do not use the server-side refusal fallback")
    parser.add_argument("--json", metavar="FILE", help="also write the full results to this JSON file")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.")
        print('PowerShell:  $env:ANTHROPIC_API_KEY = "<your key>"')
        return 1

    import anthropic  # imported here so the offline tests need neither a key nor network

    settings = Settings.from_env()
    model = args.model or settings.model
    fallbacks = settings.enable_fallbacks and not args.no_fallbacks
    scenarios = [s for s in load_scenarios() if not args.only or args.only in s["id"]]
    if not scenarios:
        print("No scenario matches --only.")
        return 1

    client = anthropic.Anthropic()
    results = []
    print(f"Model: {model}   scenarios: {len(scenarios)}\n")
    for scenario in scenarios:
        result = run_scenario_safely(scenario, client, model=model, fallbacks=fallbacks)
        results.append(result)
        verdict = "PASS" if result["passed"] else "FAIL"
        print(f"{verdict}  {result['id']:<22} tools: {' -> '.join(result['tools']) or '(none)'}")
        for failure in result["failures"]:
            print(f"        - {failure}")

    passed = sum(r["passed"] for r in results)
    tokens_in = sum(r["input_tokens"] for r in results)
    tokens_out = sum(r["output_tokens"] for r in results)
    cost = estimate_cost(model, tokens_in, tokens_out)
    print(f"\nPassed {passed}/{len(results)} ({passed / len(results):.0%})")
    print(f"Tokens: {tokens_in:,} in, {tokens_out:,} out" + (f"   estimated cost: US$ {cost:.2f}" if cost is not None else ""))
    if fallbacks and any(f.startswith("crashed") for r in results for f in r["failures"]):
        print("\nSome scenarios crashed. If the errors mention the fallback parameter, retry with --no-fallbacks.")
    if args.json:
        Path(args.json).write_text(json.dumps({"model": model, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
