import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestCustomUser:
    def test_create_user_with_email(self):
        user = User.objects.create_user(email="user@example.com", password="pass1234")
        assert user.email == "user@example.com"
        assert user.check_password("pass1234")
        assert user.is_active
        assert not user.is_staff
        assert not user.is_superuser

    def test_username_field_is_email(self):
        assert User.USERNAME_FIELD == "email"

    def test_uuid_primary_key(self):
        user = User.objects.create_user(email="uuid@example.com", password="pass1234")
        assert user.pk is not None
        assert str(user.pk) == str(user.id)

    def test_str_returns_email(self):
        user = User.objects.create_user(email="str@example.com", password="pass1234")
        assert str(user) == "str@example.com"

    def test_create_user_without_email_raises(self):
        with pytest.raises(ValueError):
            User.objects.create_user(email="", password="pass1234")
