import pytest

from delivery_agent.clock import ManualClock
from delivery_agent.shop import Shop


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def shop(clock) -> Shop:
    return Shop(clock=clock)
