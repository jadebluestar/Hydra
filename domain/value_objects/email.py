"""
Email value object.

A value object is immutable and has equality by value, not identity:
    Email("a@b.com") == Email("a@b.com")    → True
    Email("a@b.com") is Email("a@b.com")    → False (two distinct objects)

This makes value objects safe to use as dictionary keys, set members,
and comparison operands without surprising identity-vs-equality bugs.

Email normalizes on construction (lowercase, strip whitespace), so
Email("  A@B.COM  ") and Email("a@b.com") are equal. This prevents
duplicate users created with the same email in different cases.

Why not just use `str`?
  A plain string gives you no validation guarantee. By the time you're
  five layers deep in a service, you don't know if the string was already
  validated. An Email value object IS a guarantee — if you hold one,
  it was validated at construction time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# RFC 5321 / 5322 simplified pattern. The full RFC regex is impractical.
# We rely on pydantic's email-validator at the HTTP layer for thorough checks;
# this pattern catches obviously malformed values in the domain layer.
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


@dataclass(frozen=True)
class Email:
    """
    A validated, normalized email address.

    frozen=True means the object is immutable after construction. Any attempt
    to assign to its fields raises FrozenInstanceError. This ensures the
    invariant (format is valid) can never be violated after the object exists.
    """

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()

        if not normalized:
            raise ValueError("Email address cannot be empty")

        if not _EMAIL_RE.match(normalized):
            raise ValueError(f"Invalid email address: {self.value!r}")

        # Frozen dataclasses disallow direct attribute assignment.
        # object.__setattr__ bypasses this guard — the only legitimate
        # use case is normalizing the value in __post_init__.
        object.__setattr__(self, "value", normalized)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Email({self.value!r})"

    @property
    def domain(self) -> str:
        """The domain portion: 'alice@example.com' → 'example.com'"""
        return self.value.split("@")[1]

    @property
    def local_part(self) -> str:
        """The local portion: 'alice@example.com' → 'alice'"""
        return self.value.split("@")[0]
