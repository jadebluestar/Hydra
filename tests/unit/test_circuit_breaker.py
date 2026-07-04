"""Unit tests for the circuit breaker state machine — no Redis required."""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, call, patch

import pytest

from core.exceptions import ServiceUnavailableError
from domain.enums.circuit_state import CircuitState
from gateway.circuit_breaker import (
    FAILURE_THRESHOLD,
    RECOVERY_TIMEOUT_SECONDS,
    CircuitBreaker,
)


def _upstream() -> str:
    return str(uuid.uuid4())


def _make_cb(**kwargs: object) -> tuple[CircuitBreaker, AsyncMock]:
    redis = AsyncMock()
    cb = CircuitBreaker(redis, **kwargs)  # type: ignore[arg-type]
    return cb, redis


# ── check() — state resolution ────────────────────────────────────────────────


class TestCheckClosed:
    async def test_no_open_at_key_returns_closed(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = None
        state = await cb.check(_upstream())
        assert state == CircuitState.CLOSED

    async def test_closed_does_not_raise(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = None
        # Should not raise
        await cb.check(_upstream())


class TestCheckOpen:
    async def test_recent_open_at_raises_503(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = str(time.time())  # just opened, no time elapsed
        with pytest.raises(ServiceUnavailableError):
            await cb.check(_upstream())

    async def test_503_has_correct_status_code(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = str(time.time())
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await cb.check(_upstream())
        assert exc_info.value.status_code == 503

    async def test_503_includes_retry_after(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = str(time.time() - 5)  # opened 5 seconds ago
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await cb.check(_upstream())
        assert "retry_after_seconds" in exc_info.value.details
        assert exc_info.value.details["retry_after_seconds"] > 0

    async def test_retry_after_decreases_as_time_passes(self) -> None:
        cb, redis = _make_cb(recovery_timeout_seconds=30)
        redis.get.return_value = str(time.time() - 10)  # 10s elapsed, 20s remain
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await cb.check(_upstream())
        remaining = exc_info.value.details["retry_after_seconds"]
        assert 18 <= remaining <= 20  # allow slight float drift


class TestCheckHalfOpen:
    async def test_old_open_at_and_probe_claimed_returns_half_open(self) -> None:
        cb, redis = _make_cb()
        # opened well past the recovery timeout
        redis.get.return_value = str(time.time() - RECOVERY_TIMEOUT_SECONDS - 1)
        redis.set.return_value = True  # NX claim succeeded
        state = await cb.check(_upstream())
        assert state == CircuitState.HALF_OPEN

    async def test_probe_set_uses_nx_flag(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = str(time.time() - RECOVERY_TIMEOUT_SECONDS - 1)
        redis.set.return_value = True
        uid = _upstream()
        await cb.check(uid)
        # Verify the probe key was set with NX
        redis.set.assert_awaited_once()
        call_kwargs = redis.set.call_args.kwargs
        assert call_kwargs.get("nx") is True

    async def test_probe_already_claimed_raises_503(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = str(time.time() - RECOVERY_TIMEOUT_SECONDS - 1)
        redis.set.return_value = None  # NX claim failed — another probe in flight
        with pytest.raises(ServiceUnavailableError):
            await cb.check(_upstream())

    async def test_probe_claimed_503_has_zero_retry_after(self) -> None:
        cb, redis = _make_cb()
        redis.get.return_value = str(time.time() - RECOVERY_TIMEOUT_SECONDS - 1)
        redis.set.return_value = None
        with pytest.raises(ServiceUnavailableError) as exc_info:
            await cb.check(_upstream())
        assert exc_info.value.details["retry_after_seconds"] == 0


# ── record_success() ──────────────────────────────────────────────────────────


class TestRecordSuccess:
    async def test_closed_success_is_noop(self) -> None:
        cb, redis = _make_cb()
        await cb.record_success(_upstream(), was_half_open=False)
        redis.delete.assert_not_awaited()

    async def test_half_open_success_deletes_all_cb_keys(self) -> None:
        cb, redis = _make_cb()
        uid = _upstream()
        await cb.record_success(uid, was_half_open=True)
        redis.delete.assert_awaited_once()
        # All three CB keys must be deleted in a single call
        deleted_args = redis.delete.call_args.args
        assert len(deleted_args) == 3

    async def test_half_open_success_deletes_open_at_key(self) -> None:
        cb, redis = _make_cb()
        uid = _upstream()
        await cb.record_success(uid, was_half_open=True)
        deleted = set(redis.delete.call_args.args)
        assert any("open_at" in k for k in deleted)

    async def test_half_open_success_deletes_probe_key(self) -> None:
        cb, redis = _make_cb()
        uid = _upstream()
        await cb.record_success(uid, was_half_open=True)
        deleted = set(redis.delete.call_args.args)
        assert any("probe" in k for k in deleted)

    async def test_half_open_success_deletes_failures_key(self) -> None:
        cb, redis = _make_cb()
        uid = _upstream()
        await cb.record_success(uid, was_half_open=True)
        deleted = set(redis.delete.call_args.args)
        assert any("failures" in k for k in deleted)


# ── record_failure() ──────────────────────────────────────────────────────────


class TestRecordFailureClosed:
    async def test_first_failure_increments_counter(self) -> None:
        cb, redis = _make_cb()
        redis.eval.return_value = 1  # count=1, below threshold
        await cb.record_failure(_upstream(), was_half_open=False)
        redis.eval.assert_awaited_once()

    async def test_below_threshold_does_not_open_circuit(self) -> None:
        cb, redis = _make_cb()
        redis.eval.return_value = FAILURE_THRESHOLD - 1
        await cb.record_failure(_upstream(), was_half_open=False)
        redis.set.assert_not_awaited()

    async def test_at_threshold_opens_circuit(self) -> None:
        cb, redis = _make_cb()
        redis.eval.return_value = FAILURE_THRESHOLD  # exactly at threshold
        await cb.record_failure(_upstream(), was_half_open=False)
        redis.set.assert_awaited_once()  # open_at key written

    async def test_above_threshold_also_opens_circuit(self) -> None:
        cb, redis = _make_cb()
        redis.eval.return_value = FAILURE_THRESHOLD + 2
        await cb.record_failure(_upstream(), was_half_open=False)
        redis.set.assert_awaited_once()

    async def test_open_circuit_sets_open_at_key(self) -> None:
        cb, redis = _make_cb()
        redis.eval.return_value = FAILURE_THRESHOLD
        uid = _upstream()
        await cb.record_failure(uid, was_half_open=False)
        set_args = redis.set.call_args.args
        assert "open_at" in set_args[0]

    async def test_custom_threshold_respected(self) -> None:
        cb, redis = _make_cb(failure_threshold=3)
        redis.eval.return_value = 3  # exactly custom threshold
        await cb.record_failure(_upstream(), was_half_open=False)
        redis.set.assert_awaited_once()

    async def test_below_custom_threshold_no_open(self) -> None:
        cb, redis = _make_cb(failure_threshold=3)
        redis.eval.return_value = 2
        await cb.record_failure(_upstream(), was_half_open=False)
        redis.set.assert_not_awaited()


class TestRecordFailureHalfOpen:
    async def test_half_open_failure_resets_open_at(self) -> None:
        cb, redis = _make_cb()
        uid = _upstream()
        await cb.record_failure(uid, was_half_open=True)
        redis.set.assert_awaited_once()
        set_args = redis.set.call_args.args
        assert "open_at" in set_args[0]

    async def test_half_open_failure_deletes_probe_key(self) -> None:
        cb, redis = _make_cb()
        uid = _upstream()
        await cb.record_failure(uid, was_half_open=True)
        redis.delete.assert_awaited_once()
        assert "probe" in redis.delete.call_args.args[0]

    async def test_half_open_failure_does_not_touch_failure_counter(self) -> None:
        cb, redis = _make_cb()
        await cb.record_failure(_upstream(), was_half_open=True)
        redis.eval.assert_not_awaited()

    async def test_half_open_failure_open_at_value_is_current_time(self) -> None:
        cb, redis = _make_cb()
        before = time.time()
        await cb.record_failure(_upstream(), was_half_open=True)
        after = time.time()
        written_ts = float(redis.set.call_args.args[1])
        assert before <= written_ts <= after


# ── full state machine scenarios ──────────────────────────────────────────────


class TestStateMachineScenarios:
    async def test_5_failures_trip_circuit(self) -> None:
        cb, redis = _make_cb(failure_threshold=5)
        uid = _upstream()
        for i in range(1, 6):
            redis.eval.return_value = i
            await cb.record_failure(uid, was_half_open=False)
        # On the 5th call, open_at should be set
        assert redis.set.await_count == 1

    async def test_closed_success_does_not_reset_failure_counter(self) -> None:
        cb, redis = _make_cb()
        # A success in CLOSED state is intentionally a no-op — the failure
        # counter decays via its own TTL
        await cb.record_success(_upstream(), was_half_open=False)
        redis.delete.assert_not_awaited()
        redis.set.assert_not_awaited()

    async def test_keys_are_upstream_scoped(self) -> None:
        cb, redis = _make_cb()
        uid_a = "upstream-aaa"
        uid_b = "upstream-bbb"
        redis.eval.return_value = 1
        await cb.record_failure(uid_a, was_half_open=False)
        await cb.record_failure(uid_b, was_half_open=False)
        # Each failure call uses a distinct key
        keys_used = [c.args[2] for c in redis.eval.await_args_list]
        assert uid_a in keys_used[0]
        assert uid_b in keys_used[1]
        assert keys_used[0] != keys_used[1]
