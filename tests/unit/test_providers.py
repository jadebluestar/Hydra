"""
Unit tests for concrete provider implementations.

JWT and mock-email tests are pure Python.
Argon2 tests are async because hash/verify are offloaded to thread pools.

Argon2 parameters are reduced for speed in tests. The default 64 MB
memory cost takes 80ms+ per call. Setting memory_cost=256 (256 KiB)
runs in ~2ms — close to instantaneous for test purposes, still
exercising all the same code paths.
"""

import time

import pytest

from core.exceptions import UnauthorizedError
from providers.implementations.argon2_hasher import Argon2Hasher
from providers.implementations.env_secrets import EnvironmentSecretProvider
from providers.implementations.jwt_hs256 import HS256JWTProvider
from providers.implementations.mock_email import MockEmailProvider

# ── JWT Provider ──────────────────────────────────────────────────────────────


class TestHS256JWTProvider:
    """
    Tests share a single provider instance since it reads settings once
    at construction time.
    """

    @pytest.fixture(autouse=True)
    def provider(self) -> HS256JWTProvider:
        self._provider = HS256JWTProvider()
        return self._provider

    def test_encode_returns_string(self) -> None:
        token = self._provider.encode({"sub": "user-123"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_encode_produces_three_part_jwt(self) -> None:
        token = self._provider.encode({"sub": "user-123"})
        parts = token.split(".")
        assert len(parts) == 3, "JWT must have header.payload.signature"

    def test_decode_returns_original_sub(self) -> None:
        token = self._provider.encode({"sub": "user-abc"})
        payload = self._provider.decode(token)
        assert payload["sub"] == "user-abc"

    def test_decode_payload_contains_standard_claims(self) -> None:
        token = self._provider.encode({"sub": "user-123"})
        payload = self._provider.decode(token)
        assert "exp" in payload
        assert "iat" in payload
        assert "jti" in payload
        assert payload["type"] == "access"

    def test_jti_is_unique_per_token(self) -> None:
        t1 = self._provider.encode({"sub": "user-123"})
        t2 = self._provider.encode({"sub": "user-123"})
        p1 = self._provider.decode(t1)
        p2 = self._provider.decode(t2)
        assert p1["jti"] != p2["jti"]

    def test_tampered_token_raises_unauthorized(self) -> None:
        token = self._provider.encode({"sub": "user-123"})
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(UnauthorizedError):
            self._provider.decode(tampered)

    def test_garbage_string_raises_unauthorized(self) -> None:
        with pytest.raises(UnauthorizedError):
            self._provider.decode("not.a.token")

    def test_empty_string_raises_unauthorized(self) -> None:
        with pytest.raises(UnauthorizedError):
            self._provider.decode("")

    def test_exp_is_in_the_future(self) -> None:
        token = self._provider.encode({"sub": "user-123"})
        payload = self._provider.decode(token)
        assert payload["exp"] > time.time()

    def test_additional_payload_claims_are_preserved(self) -> None:
        token = self._provider.encode({"sub": "user-123", "org_id": "org-abc"})
        payload = self._provider.decode(token)
        assert payload["org_id"] == "org-abc"


# ── Argon2 Hasher ─────────────────────────────────────────────────────────────


class TestArgon2Hasher:
    @pytest.fixture(autouse=True)
    def hasher(self) -> Argon2Hasher:
        # Low memory_cost so tests run fast — same code paths, just cheaper params
        self._hasher = Argon2Hasher(time_cost=1, memory_cost=256, parallelism=1)
        return self._hasher

    async def test_hash_returns_string(self) -> None:
        result = await self._hasher.hash("secret123")
        assert isinstance(result, str)

    async def test_hash_output_looks_like_argon2(self) -> None:
        result = await self._hasher.hash("secret123")
        assert result.startswith("$argon2id$")

    async def test_same_password_produces_different_hashes(self) -> None:
        # Each hash gets a random salt — identical inputs produce different outputs
        h1 = await self._hasher.hash("secret123")
        h2 = await self._hasher.hash("secret123")
        assert h1 != h2

    async def test_verify_correct_password_returns_true(self) -> None:
        hashed = await self._hasher.hash("correct-horse-battery-staple")
        assert await self._hasher.verify("correct-horse-battery-staple", hashed) is True

    async def test_verify_wrong_password_returns_false(self) -> None:
        hashed = await self._hasher.hash("correct-horse-battery-staple")
        assert await self._hasher.verify("wrong-password", hashed) is False

    async def test_verify_does_not_raise_on_mismatch(self) -> None:
        hashed = await self._hasher.hash("password")
        result = await self._hasher.verify("wrong", hashed)  # must not raise
        assert result is False

    async def test_needs_rehash_false_for_current_params(self) -> None:
        hashed = await self._hasher.hash("password")
        # Hashed with the same hasher — params are current, no rehash needed
        assert await self._hasher.needs_rehash(hashed) is False

    async def test_needs_rehash_true_for_old_params(self) -> None:
        # Simulate a hash created with weaker parameters
        old_hasher = Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1)
        old_hash = await old_hasher.hash("password")
        # Current hasher has higher memory_cost=256 — old hash needs upgrade
        assert await self._hasher.needs_rehash(old_hash) is True


# ── Mock Email Provider ───────────────────────────────────────────────────────


class TestMockEmailProvider:
    @pytest.fixture(autouse=True)
    def provider(self) -> MockEmailProvider:
        self._provider = MockEmailProvider()
        return self._provider

    async def test_send_returns_none(self) -> None:
        result = await self._provider.send(
            to="alice@example.com",
            subject="Welcome",
            body_text="Hello Alice",
        )
        assert result is None

    async def test_send_accepts_html_body(self) -> None:
        # Must not raise
        await self._provider.send(
            to="alice@example.com",
            subject="Welcome",
            body_text="Hello",
            body_html="<p>Hello</p>",
        )

    async def test_send_requires_keyword_args(self) -> None:
        # Positional args should fail — ensures callers don't swap to/subject
        with pytest.raises(TypeError):
            await self._provider.send(  # type: ignore[call-arg]
                "alice@example.com", "Welcome", "Hello"
            )


# ── Environment Secret Provider ───────────────────────────────────────────────


class TestEnvironmentSecretProvider:
    @pytest.fixture(autouse=True)
    def provider(self) -> EnvironmentSecretProvider:
        self._provider = EnvironmentSecretProvider()
        return self._provider

    def test_get_returns_existing_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_TEST_SECRET", "super-secret")
        assert self._provider.get("MY_TEST_SECRET") == "super-secret"

    def test_get_raises_key_error_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_SECRET", raising=False)
        with pytest.raises(KeyError, match="MISSING_SECRET"):
            self._provider.get("MISSING_SECRET")

    def test_get_optional_returns_value_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPT_SECRET", "value")
        assert self._provider.get_optional("OPT_SECRET") == "value"

    def test_get_optional_returns_none_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPT_SECRET", raising=False)
        assert self._provider.get_optional("OPT_SECRET") is None

    def test_get_optional_returns_default_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPT_SECRET", raising=False)
        assert self._provider.get_optional("OPT_SECRET", default="fallback") == "fallback"

    def test_get_error_message_includes_key_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IMPORTANT_SECRET", raising=False)
        with pytest.raises(KeyError, match="IMPORTANT_SECRET"):
            self._provider.get("IMPORTANT_SECRET")
