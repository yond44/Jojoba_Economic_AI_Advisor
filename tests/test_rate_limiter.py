"""Unit tests for the in-memory rate limiter."""
from src.middleware import rate_limiter


def setup_function():
    rate_limiter._requests.clear()


def test_allows_requests_under_limit():
    for _ in range(5):
        allowed, _wait = rate_limiter._is_allowed("client-a")
        assert allowed


def test_blocks_after_limit():
    for _ in range(rate_limiter.RATE_LIMIT):
        rate_limiter._is_allowed("client-b")
    allowed, wait_time = rate_limiter._is_allowed("client-b")
    assert not allowed
    assert wait_time >= 1


def test_clients_are_isolated():
    for _ in range(rate_limiter.RATE_LIMIT):
        rate_limiter._is_allowed("client-c")
    allowed, _ = rate_limiter._is_allowed("client-d")
    assert allowed
