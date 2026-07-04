from __future__ import annotations

import re


def slugify(text: str) -> str:
    """
    Convert arbitrary text into a URL-safe slug.

    Rules:
      - Lowercase
      - Alphanumeric and hyphens only
      - No leading or trailing hyphens
      - Max 63 characters (DNS label length limit — useful for subdomains)

    Examples:
        slugify("Acme Corp Ltd")  → "acme-corp-ltd"
        slugify("Hello, World!")  → "hello-world"
        slugify("  spaced  ")     → "spaced"
    """
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:63]


_VALID_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")


def is_valid_slug(slug: str) -> bool:
    """Return True if slug matches the expected format (3-63 chars)."""
    return bool(_VALID_SLUG_RE.match(slug))
