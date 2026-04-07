"""Role definitions for the i4g RBAC system.

PRD FR-2 defines six roles with escalating permissions:

* ``researcher`` — anonymized aggregate access only; no PII or raw entity values.
* ``user`` — read-only access to public case summaries.
* ``analyst`` — full case review, annotation, and report generation.
* ``manager`` — engagement management, team oversight, analytics.
* ``admin`` — user management, campaign CRUD, bulk operations.
* ``leo`` — law-enforcement liaison, can access LEO-specific reports.

Admin always has superset permissions.  The hierarchy is::

    researcher < user < analyst < manager < leo ≤ admin
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """User roles for access control."""

    RESEARCHER = "researcher"
    USER = "user"
    ANALYST = "analyst"
    MANAGER = "manager"
    ADMIN = "admin"
    LEO = "leo"


#: Default role assigned when a new user authenticates for the first time.
#: Set to USER (minimal privilege) — admins can promote via User Management.
DEFAULT_ROLE = Role.USER

#: Role hierarchy — each role inherits all permissions of the roles listed.
#: ``admin`` is always a superset of every other role.
ROLE_HIERARCHY: dict[Role, set[Role]] = {
    Role.RESEARCHER: set(),
    Role.USER: {Role.RESEARCHER},
    Role.ANALYST: {Role.RESEARCHER, Role.USER},
    Role.MANAGER: {Role.RESEARCHER, Role.USER, Role.ANALYST},
    Role.LEO: {Role.RESEARCHER, Role.USER, Role.ANALYST, Role.MANAGER},
    Role.ADMIN: {Role.RESEARCHER, Role.USER, Role.ANALYST, Role.MANAGER, Role.LEO},
}


def has_role(user_role: str | Role, required_role: str | Role) -> bool:
    """Check whether *user_role* satisfies *required_role*.

    Returns ``True`` when:

    * The user's role equals the required role, **or**
    * The user's role is ``admin`` (unconditional superuser), **or**
    * The required role is in the user role's hierarchy (inherited roles).

    Args:
        user_role: The role of the authenticated user.
        required_role: The minimum role required for the operation.

    Returns:
        True if the user has sufficient privileges.
    """
    try:
        u = Role(user_role)
        r = Role(required_role)
    except ValueError:
        return False

    if u == r:
        return True
    if u == Role.ADMIN:
        return True
    return r in ROLE_HIERARCHY.get(u, set())


def is_researcher(user: dict[str, str]) -> bool:
    """Return True if the user has only researcher-level access.

    A user with a higher role (e.g. analyst, admin) who *inherits* researcher
    permissions is **not** considered a researcher for access-control purposes.

    Args:
        user: Token dict with at least a ``role`` key.

    Returns:
        True if the role is exactly ``researcher`` with no higher privileges.
    """
    role = user.get("role", "")
    return role == Role.RESEARCHER and not has_role(role, Role.USER)
