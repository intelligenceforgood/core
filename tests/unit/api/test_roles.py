"""Unit tests for the Role enum and role checking logic."""

import pytest

from i4g.api.roles import DEFAULT_ROLE, ROLE_HIERARCHY, Role, has_role


class TestRoleEnum:
    """Verify the Role enum values match PRD FR-2."""

    def test_role_values(self):
        assert Role.USER.value == "user"
        assert Role.ANALYST.value == "analyst"
        assert Role.ADMIN.value == "admin"
        assert Role.LEO.value == "leo"

    def test_default_role_is_user(self):
        """New users get minimal privilege (user role)."""
        assert DEFAULT_ROLE == Role.USER

    def test_role_from_string(self):
        assert Role("admin") == Role.ADMIN
        assert Role("analyst") == Role.ANALYST

    def test_invalid_role_string_raises(self):
        with pytest.raises(ValueError):
            Role("superuser")

    def test_role_hierarchy_admin_has_all(self):
        assert ROLE_HIERARCHY[Role.ADMIN] == {Role.USER, Role.ANALYST, Role.LEO}

    def test_role_hierarchy_analyst_has_user(self):
        assert ROLE_HIERARCHY[Role.ANALYST] == {Role.USER}

    def test_role_hierarchy_user_has_none(self):
        assert ROLE_HIERARCHY[Role.USER] == set()


class TestHasRole:
    """Verify the ``has_role()`` function correctly checks role hierarchy."""

    def test_same_role_always_passes(self):
        for role in Role:
            assert has_role(role.value, role.value) is True

    def test_admin_satisfies_all_roles(self):
        for role in Role:
            assert has_role("admin", role.value) is True

    def test_analyst_satisfies_user(self):
        assert has_role("analyst", "user") is True

    def test_analyst_does_not_satisfy_admin(self):
        assert has_role("analyst", "admin") is False

    def test_user_does_not_satisfy_analyst(self):
        assert has_role("user", "analyst") is False

    def test_leo_satisfies_analyst(self):
        assert has_role("leo", "analyst") is True

    def test_leo_satisfies_user(self):
        assert has_role("leo", "user") is True

    def test_leo_does_not_satisfy_admin(self):
        assert has_role("leo", "admin") is False

    def test_invalid_user_role_returns_false(self):
        assert has_role("doesnotexist", "admin") is False

    def test_invalid_required_role_returns_false(self):
        assert has_role("admin", "doesnotexist") is False

    def test_role_enum_values_accepted(self):
        assert has_role(Role.ADMIN, Role.ANALYST) is True

    def test_string_and_enum_mixed(self):
        assert has_role("admin", Role.LEO) is True
        assert has_role(Role.USER, "analyst") is False
