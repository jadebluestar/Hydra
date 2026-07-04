"""
RoutePath value object.

A route path is the prefix used by the gateway's trie matcher to route
inbound requests to a registered upstream. It has specific invariants:

  - Must start with '/'
  - Must not contain '//' (double slash — likely a typo)
  - Trailing slashes are normalized away ('/users/' → '/users')
  - The root path '/' is the only valid single-slash path

These constraints prevent misconfigured routes from matching more than
intended. A route at '/api' should not accidentally match '/apple'.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutePath:
    """
    A validated, normalized API route path prefix.

    Examples:
        RoutePath("/users")          → value = "/users"
        RoutePath("/users/")         → value = "/users"   (normalized)
        RoutePath("/api/v1/widgets") → value = "/api/v1/widgets"
    """

    value: str

    def __post_init__(self) -> None:
        raw = self.value.strip()

        if not raw:
            raise ValueError("Route path cannot be empty")

        if not raw.startswith("/"):
            raise ValueError(
                f"Route path must start with '/': {raw!r}"
            )

        if "//" in raw:
            raise ValueError(
                f"Route path must not contain '//': {raw!r}"
            )

        # Normalize: strip trailing slash, but preserve root "/"
        normalized = raw.rstrip("/") or "/"
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"RoutePath({self.value!r})"

    @property
    def segments(self) -> list[str]:
        """
        Split the path into its segments.
        RoutePath("/api/v1/users").segments → ["api", "v1", "users"]
        """
        return [s for s in self.value.split("/") if s]

    def is_prefix_of(self, other: str) -> bool:
        """
        Return True if this path is a prefix of the given string.
        Used by the trie matcher to determine if a route matches an
        inbound request path.

        RoutePath("/api").is_prefix_of("/api/users")  → True
        RoutePath("/api").is_prefix_of("/apikeys")    → False
        """
        # Must match at a segment boundary, not mid-segment
        if self.value == "/":
            return True
        return other == self.value or other.startswith(self.value + "/")
