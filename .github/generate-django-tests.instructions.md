---
description: "Use when generating Django pytest tests for models, views, serializers, or utility functions. Covers test structure, required patterns, coverage requirements, and what to test for each Django component type."
applyTo: "**/tests/test_*.py"
---

# Django Test Generation Instructions

## MANDATORY: pytest Only

- NEVER use `from django.test import TestCase`
- NEVER use `import unittest`
- NEVER inherit from `TestCase`
- ALWAYS use `@pytest.mark.django_db` for database access
- ALWAYS use `from datetime import UTC, datetime as dt` and `dt.now(UTC)` for current time

## Test Structure Template

```python
import pytest
from datetime import UTC, datetime as dt
from django.urls import reverse

from rmcore.factories import ClientFactory
# Import the specific model/view/serializer being tested


@pytest.mark.django_db
class TestModelName:
    def test_creation_valid_data(self):
        instance = ModelFactory()
        assert instance.pk is not None

    def test_str_representation(self):
        instance = ModelFactory()
        assert str(instance) != ""

    def test_validation_invalid_data(self):
        with pytest.raises(Exception):
            Model.objects.create(required_field=None)


@pytest.mark.django_db
class TestViewName:
    def test_get_success(self, auth_client):
        response = auth_client.get(reverse("view-name"))
        assert response.status_code == 200

    def test_post_valid_data(self, auth_client):
        data = {"field": "value"}
        response = auth_client.post(reverse("view-name"), data, format="json")
        assert response.status_code == 201

    def test_permission_denied_unauthenticated(self, client):
        response = client.get(reverse("view-name"))
        assert response.status_code in (401, 403)
```

## Coverage Requirements

- **Models**: test all fields, methods, relationships, validation, `__str__`
- **Views**: test all HTTP methods, permissions, success/error cases, pagination
- **Serializers**: test serialization, deserialization, validation, nested objects
- **Utilities**: test all functions with various input types, edge cases, None inputs

## Naming Convention

```
test_[function/method]_[scenario]

Examples:
  test_create_client_valid_data
  test_get_appointment_not_found
  test_serializer_missing_required_field
```

## Fixtures

Use fixtures from `rmbase/tests/fixtures.py`. Common patterns:

```python
def test_something(self, auth_client, practice):
    # auth_client: authenticated DRF test client
    # practice: a Practice instance
```

## Mock External Services

```python
from unittest.mock import patch

@patch("crms.cliniko.models.requests.get")
def test_with_mocked_api(self, mock_get):
    mock_get.return_value.json.return_value = {"data": []}
    # test body
```
