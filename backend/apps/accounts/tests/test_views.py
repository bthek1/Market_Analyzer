import pytest
from django.urls import NoReverseMatch, reverse


@pytest.mark.django_db
class TestRegistrationView:
    url = "/api/auth/registration/"

    def test_register_returns_201(self, api_client):
        data = {
            "email": "new@example.com",
            "password1": "securepass123!",
            "password2": "securepass123!",
        }
        response = api_client.post(self.url, data)
        assert response.status_code == 201

    def test_register_returns_access_token(self, api_client):
        data = {
            "email": "new@example.com",
            "password1": "securepass123!",
            "password2": "securepass123!",
        }
        response = api_client.post(self.url, data)
        assert "access" in response.data

    def test_register_duplicate_email_returns_400(self, api_client):
        data = {
            "email": "dup@example.com",
            "password1": "securepass123!",
            "password2": "securepass123!",
        }
        api_client.post(self.url, data)
        response = api_client.post(self.url, data)
        assert response.status_code == 400

    def test_register_password_mismatch_returns_400(self, api_client):
        data = {"email": "x@example.com", "password1": "securepass123!", "password2": "wrong"}
        response = api_client.post(self.url, data)
        assert response.status_code == 400


@pytest.mark.django_db
class TestLoginView:
    url = "/api/auth/login/"

    def test_login_returns_200(self, api_client, user):
        response = api_client.post(self.url, {"email": user.email, "password": "testpass123"})
        assert response.status_code == 200

    def test_login_returns_tokens(self, api_client, user):
        response = api_client.post(self.url, {"email": user.email, "password": "testpass123"})
        assert "access" in response.data
        assert "refresh" in response.data

    def test_login_wrong_password_returns_400(self, api_client, user):
        response = api_client.post(self.url, {"email": user.email, "password": "wrong"})
        assert response.status_code == 400


@pytest.mark.django_db
class TestLogoutView:
    url = "/api/auth/logout/"

    def test_logout_authenticated_returns_200(self, auth_client):
        response = auth_client.post(self.url)
        assert response.status_code == 200

    def test_logout_unauthenticated_returns_200(self, api_client):
        response = api_client.post(self.url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestMeView:
    def test_me_unauthenticated_returns_401(self, api_client):
        url = reverse("accounts-me")
        response = api_client.get(url)
        assert response.status_code == 401

    def test_me_authenticated_returns_200(self, auth_client, user):
        url = reverse("accounts-me")
        response = auth_client.get(url)
        assert response.status_code == 200
        assert response.data["email"] == user.email


@pytest.mark.django_db
class TestOldEndpointsGone:
    def test_token_obtain_pair_url_removed(self):
        with pytest.raises(NoReverseMatch):
            reverse("token_obtain_pair")

    def test_accounts_register_url_removed(self):
        with pytest.raises(NoReverseMatch):
            reverse("accounts-register")
