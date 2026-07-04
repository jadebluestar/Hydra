"""
Organization member roles.

Roles are coarse-grained identifiers. The fine-grained access control is
handled by the Permission system — a Role is just a named bundle of Permissions.

We use StrEnum (Python 3.11+) so that role values ARE strings.
This means:
  - Role.OWNER == "owner"         → True
  - Pydantic serializes Role.OWNER as "owner" automatically
  - SQLAlchemy stores "owner" in the database column directly
  - No .value access needed for comparison or storage

Role hierarchy (highest to lowest access):
    OWNER > ADMIN > MEMBER > VIEWER
"""

from enum import StrEnum


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
