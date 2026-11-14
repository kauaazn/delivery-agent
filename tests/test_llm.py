"""llm.py is the only place that builds Claude requests, so the rules about them live here."""
from delivery_agent.llm import FALLBACK_BETA, call_claude
from fakes import FakeClaude, text

MESSAGES = [{"role": "user", "content": "oi"}]


def ask(fake, **kwargs):
    return call_claude(fake, model=kwargs.pop("model", "claude-opus-5-5"), system="s", tools=[], messages=MESSAGES, **kwargs)


def test_the_default_request_uses_the_stable_endpoint():
    fake = FakeClaude(text("ok"))
    ask(fake)
    (request,) = fake.requests
    assert request["_endpoint"] == "stable"
    assert request["max_tokens"] >= 1024


def test_the_request_has_no_parameters_that_opus_5_5_rejects():
    fake = FakeClaude(text("ok"))
    ask(fake)
    (request,) = fake.requests
    for rejected in ("temperature", "top_p", "top_k", "tool_choice", "thinking"):
        assert rejected not in request


def test_the_effort_is_set_explicitly():
    fake = FakeClaude(text("ok"))
    ask(fake)
    assert fake.requests[0]["output_config"] == {"effort": "medium"}


def test_fallbacks_use_the_beta_endpoint_with_the_default_fallback():
    fake = FakeClaude(text("ok"))
    ask(fake, fallbacks=True)
    (request,) = fake.requests
    assert request["_endpoint"] == "beta"
    assert request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == "default"


def test_haiku_never_gets_fallbacks():
    fake = FakeClaude(text("ok"))
    ask(fake, model="claude-haiku-5-5", fallbacks=True)
    (request,) = fake.requests
    assert request["_endpoint"] == "stable" and "fallbacks" not in request
