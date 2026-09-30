import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

User = get_user_model()

EMAIL = "loadtest@example.com"


@pytest.fixture
def loadtest_env(monkeypatch):
    monkeypatch.setenv("LOADTEST_EMAIL", EMAIL)
    monkeypatch.setenv("LOADTEST_PASSWORD", "first-secret")
    return monkeypatch


@pytest.mark.django_db
class TestEnsureLoadtestUser:
    def test_creates_a_non_staff_user(self, loadtest_env):
        call_command("ensure_loadtest_user")

        user = User.objects.get(email=EMAIL)
        assert user.check_password("first-secret")
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser

    def test_is_idempotent_and_follows_the_password_in_the_environment(self, loadtest_env):
        call_command("ensure_loadtest_user")
        loadtest_env.setenv("LOADTEST_PASSWORD", "rotated-secret")
        call_command("ensure_loadtest_user")

        assert User.objects.filter(email=EMAIL).count() == 1
        user = User.objects.get(email=EMAIL)
        assert user.check_password("rotated-secret")
        assert not user.is_staff

    def test_refuses_an_existing_staff_account_rather_than_demoting_it(self, loadtest_env):
        User.objects.create_user(email=EMAIL, password="theirs", is_staff=True)

        with pytest.raises(CommandError, match="staff"):
            call_command("ensure_loadtest_user")

        user = User.objects.get(email=EMAIL)
        assert user.is_staff, "a refusal must leave the account untouched"
        assert user.check_password("theirs")

    def test_refuses_an_address_that_is_not_a_loadtest_account(self, loadtest_env):
        """Otherwise a mistyped LOADTEST_EMAIL would silently reset a real user's password."""
        User.objects.create_user(email="analyst@example.com", password="theirs")
        loadtest_env.setenv("LOADTEST_EMAIL", "analyst@example.com")

        with pytest.raises(CommandError, match="loadtest"):
            call_command("ensure_loadtest_user")

        assert User.objects.get(email="analyst@example.com").check_password("theirs")

    def test_requires_a_password(self, loadtest_env):
        loadtest_env.delenv("LOADTEST_PASSWORD")

        with pytest.raises(CommandError, match="LOADTEST_PASSWORD"):
            call_command("ensure_loadtest_user")
        assert not User.objects.filter(email=EMAIL).exists()
