"""Unit tests for the sliding window rate limiter."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from core.exceptions import RateLimitError
from gateway.rate_limiter import check_rate_limit


def _redis(eval_return: int = 1) -> AsyncMock:
    r = AsyncMock()
    r.eval.return_value = eval_return
    return r


class TestCheckRateLimit:
    async def test_under_limit_does_not_raise(self) -> None:
        redis = _redis(eval_return=1)  # 1 request recorded, limit not reached
        await check_rate_limit(
            redis,
            api_key_id="key-abc",
            route_id="route-xyz",
            limit=10,
        )
        redis.eval.assert_awaited_once()

    async def test_over_limit_raises_rate_limit_error(self) -> None:
        redis = _redis(eval_return=-1)  # Lua script returned -1 = over limit
        with pytest.raises(RateLimitError):
            await check_rate_limit(
                redis,
                api_key_id="key-abc",
                route_id="route-xyz",
                limit=5,
            )

    async def test_zero_limit_is_noop(self) -> None:
        redis = _redis()
        await check_rate_limit(
            redis,
            api_key_id="key-abc",
            route_id="route-xyz",
            limit=0,
        )
        redis.eval.assert_not_awaited()

    async def test_negative_limit_is_noop(self) -> None:
        redis = _redis()
        await check_rate_limit(
            redis,
            api_key_id="key-abc",
            route_id="route-xyz",
            limit=-1,
        )
        redis.eval.assert_not_awaited()

    async def test_rate_limit_error_includes_limit_in_details(self) -> None:
        redis = _redis(eval_return=-1)
        with pytest.raises(RateLimitError) as exc:
            await check_rate_limit(
                redis,
                api_key_id="key-abc",
                route_id="route-xyz",
                limit=100,
            )
        assert exc.value.details["limit"] == 100

    async def test_key_includes_api_key_id_and_route_id(self) -> None:
        redis = _redis()
        api_key_id = "key-" + str(uuid.uuid4())
        route_id = "route-" + str(uuid.uuid4())

        await check_rate_limit(
            redis,
            api_key_id=api_key_id,
            route_id=route_id,
            limit=10,
        )

        called_key = redis.eval.call_args.args[2]  # KEYS[1] is the 3rd positional arg
        assert api_key_id in called_key
        assert route_id in called_key

    async def test_different_routes_get_different_keys(self) -> None:
        redis = _redis()
        api_key_id = "key-abc"
        route_a = "route-aaa"
        route_b = "route-bbb"

        await check_rate_limit(redis, api_key_id=api_key_id, route_id=route_a, limit=10)
        await check_rate_limit(redis, api_key_id=api_key_id, route_id=route_b, limit=10)

        calls = redis.eval.call_args_list
        key_a = calls[0].args[2]
        key_b = calls[1].args[2]
        assert key_a != key_b

    async def test_different_api_keys_get_different_keys(self) -> None:
        redis = _redis()
        route_id = "route-xyz"
        key_a = "key-aaa"
        key_b = "key-bbb"

        await check_rate_limit(redis, api_key_id=key_a, route_id=route_id, limit=10)
        await check_rate_limit(redis, api_key_id=key_b, route_id=route_id, limit=10)

        calls = redis.eval.call_args_list
        rl_key_a = calls[0].args[2]
        rl_key_b = calls[1].args[2]
        assert rl_key_a != rl_key_b

    async def test_lua_receives_correct_numkeys(self) -> None:
        redis = _redis()
        await check_rate_limit(redis, api_key_id="k", route_id="r", limit=5)
        # Second positional arg to eval() is numkeys
        numkeys = redis.eval.call_args.args[1]
        assert numkeys == 1

    async def test_lua_receives_limit_as_argv1(self) -> None:
        redis = _redis()
        await check_rate_limit(redis, api_key_id="k", route_id="r", limit=42)
        # args: (script, numkeys, key, limit, now_ms, window_ms, req_id)
        limit_arg = redis.eval.call_args.args[3]  # ARGV[1]
        assert limit_arg == "42"

    async def test_positive_return_value_not_at_limit_does_not_raise(self) -> None:
        # Any positive return means count was under limit
        for count in [1, 5, 99]:
            redis = _redis(eval_return=count)
            await check_rate_limit(redis, api_key_id="k", route_id="r", limit=100)
