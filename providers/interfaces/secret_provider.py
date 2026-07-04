"""
Secret Provider interface.

Defines the contract for reading application secrets. Implementations:
  - EnvironmentSecretProvider (Milestone 4): reads from os.environ / .env
  - VaultProvider             (future):      reads from HashiCorp Vault
  - AWSSecretsManagerProvider (future):      reads from AWS Secrets Manager

Why abstract this?
  In development, secrets come from .env files.
  In production, they should come from a secrets manager — never baked
  into the image or stored in source control.

  With this interface, the application code (AuthService, JWTProvider) is
  written once. Switching from .env to Vault in production is a one-line
  change at the dependency injection point, not a refactor.

Secret reads are synchronous because:
  - Environment variables are in-memory (nanosecond reads)
  - Vault/AWS providers cache secrets at startup; reads return from cache
  Async would add overhead with no benefit for cached values.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretProvider(Protocol):
    def get(self, key: str) -> str:
        """
        Get a required secret by name.

        Raises:
            KeyError: If the secret is not configured. Fail-fast is
                      intentional — a missing secret is always a bug.
        """
        ...

    def get_optional(self, key: str, default: str | None = None) -> str | None:
        """
        Get an optional secret by name.

        Returns default if the secret is not set.
        Use for optional feature flags and non-critical configuration.
        """
        ...
