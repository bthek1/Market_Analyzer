---
description: "Use when writing Python code, tests, models, views, serializers, or any backend code. Covers character encoding, datetime patterns, prohibited frameworks, and required coding patterns for this project."
applyTo: "**/*.py"
---

# Coding Conventions

## Character Encoding (MANDATORY)

Use **standard ASCII characters only** in all code, docstrings, and comments.

| Use this           | Not this                                | Why                                          |
| ------------------ | --------------------------------------- | -------------------------------------------- |
| `-` (hyphen-minus) | `--` (en dash) or `---` (em dash)       | Prevents RUF001/RUF002/RUF003 linting errors |
| `*` (asterisk)     | `x` (multiplication sign)               | Code portability                             |
| `x` (lowercase x)  | `x` (multiplication sign) in dimensions | Code portability                             |

## Datetime (MANDATORY)

Always use timezone-aware datetimes:

```python
from datetime import UTC, datetime as dt

# Current time - ALWAYS use this:
now = dt.now(UTC)
```

Never use `datetime.now()` without UTC, or `datetime.utcnow()`.

## Testing (MANDATORY)

- **NEVER** use `from django.test import TestCase`
- **NEVER** use `import unittest` or inherit from `unittest.TestCase`
- **NEVER** use `class MyTest(TestCase):`
- **ALWAYS** use `import pytest` and `@pytest.mark.django_db`
- **ALWAYS** use fixture patterns from `rmbase/tests/fixtures.py`

```python
import pytest
from datetime import UTC, datetime as dt

@pytest.mark.django_db
class TestModelName:
    def test_something(self):
        # NO TestCase inheritance
        ...
```

See `.github/instructions/generate-django-tests.instructions.md` and `.github/instructions/test-automation.instructions.md` for full testing guidance.

## Frontend (MANDATORY)

- **NEVER** use HTMX - do not add `hx-*` attributes, `htmx.js` scripts, or any HTMX-based patterns
- All new UI work goes in `frontend/src/` (React + Vite)
- Legacy templates in `pages/` and `templates/` are being refactored into React - do not add to them

## Model Imports

- Import core models from `rmcore.models`
- Import questionnaire models from `rmquestionnaire.models`
- Do **not** import questionnaire types from `rmbase.models`

## End-of-Task Rules

- **NEVER** create summary/explanation markdown files after completing tasks
- **NEVER** create `TASK-COMPLETE.md`, `SUMMARY.md`, or similar files
- **NEVER** create progress tracking files unless explicitly requested
- **DO** update existing documentation if changes affect documented behaviour
