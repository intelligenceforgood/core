"""Role definitions for the i4g RBAC system.

PRD FR-2 defines four roles with escalating permissions:

* ``user`` — read-only access to public case summaries.
* ``analyst`` — full case review, annotation, and report generation.
* ``admin`` — user management, campaign CRUD, bulk operations.
* ``leo`` — law-enforcement liaison, can access LEO-specific reports.

Admin always has superset permissions.  The hierarchy is::

    user < analyst < leo ≤ admin
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """User roles for access control."""

    USER = "user"
    ANALYST = "analyst"
    ADMIN = "admin"
    LEO = "leo"


#: Default role assigned when a new user authenticates for the first time.
DEFAULT_ROLE = Role.ANALYST

#: Role hierarchy — each role inherits all permissions of the roles listed.
#: ``admin`` is always a superset of every other role.
ROLE_HIERARCHY: dict[Role, set[Role]] = {
    Role.USER: set(),
    Role.ANALYST: {Role.USER},
    Role.LEO: {Role.USER, Role.ANALYST},
    Role.ADMIN: {Role.USER, Role.ANALYST, Role.LEO},
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
