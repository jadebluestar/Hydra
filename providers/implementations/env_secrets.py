"""
Environment Secret Provider.

Reads secrets from environment variables / .env file (pydantic-settings
already loaded the .env into os.environ by the time this runs).

In production, replace with a Vault or AWS Secrets Manager provider.
The interface contract is the same — only the source changes.

Why wrap os.environ at all?
  - Consistent error messages when a required secret is missing
  - Easy to mock in tests (inject a FakeSecretProvider)
  - Future: add secret rotation or caching without touching callers
"""

from __future__ import annotations

import os


class EnvironmentSecretProvider:
    def get(self, key: str) -> str:
        """
        Return a required secret.

        Raises KeyError if the variable is not set.
        The message includes the key name so operators know
        exactly which variable is missing at startup.
        """
        value = os.environ.get(key)
        if value is None:
            raise KeyError(
                f"Required secret '{key}' is not set in the environment. "
                f"Add it to your .env file or set it as an environment variable."
            )
        return value

    def get_optional(self, key: str, default: str | None = None) -> str | None:
        """Return an optional secret, falling back to default."""
        return os.environ.get(key, default)
