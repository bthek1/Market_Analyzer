---
description: "Use when extracting test patterns from existing test files, understanding how tests are structured in this codebase, identifying fixture usage, mock patterns, or assertion styles before generating new tests."
---

# Test Pattern Recognition Instructions

When analyzing existing tests to understand patterns, examine:

## Pattern Analysis Tasks

1. **Fixture Patterns**: how are test fixtures created and used?
2. **Mock Patterns**: how are external services mocked?
3. **Assertion Patterns**: what assertions are commonly used?
4. **Test Organization**: how are test classes and methods structured?
5. **Data Setup**: how is test data created and managed?

## Key Files to Examine

- `rmbase/tests/fixtures.py` - shared fixtures
- `rmcore/factories.py` - Factory Boy patterns for core models
- `rmbase/factories.py` - Factory Boy patterns for rmbase models
- `rmquestionnaire/factories.py` - Factory Boy patterns for questionnaires
- Any existing `test_*.py` files in the relevant app

## Extract These Patterns

### Model Testing Pattern

```python
@pytest.mark.django_db
class TestModelName:
    def test_creation(self):
        instance = ModelFactory()
        assert instance.pk is not None
```

### View Testing Pattern

```python
@pytest.mark.django_db
class TestViewName:
    def test_endpoint_success(self, auth_client):
        response = auth_client.get(reverse("view-name"))
        assert response.status_code == 200
```

### Datetime Pattern (MANDATORY)

```python
from datetime import UTC, datetime as dt

created_at = dt.now(UTC)
```

## Apply Discovered Patterns

After extracting patterns, apply them consistently when generating new tests for similar code structures.
