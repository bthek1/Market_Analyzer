---
description: "Use when improving test coverage, generating tests, running coverage analysis, finding test gaps, or asked to write tests for Django models, views, serializers, or utilities. Covers pytest patterns, coverage targets, and iterative test generation."
---

# Test Automation Instructions

## Core Rules

- **Never ask for user input** - make decisions autonomously
- **Generate tests immediately** based on code analysis
- **Run tests automatically** after generation
- **Iterate continuously** - analyze coverage gaps and generate more tests
- **MANDATORY**: Use pytest ONLY - NEVER Django TestCase or unittest.TestCase

## Workflow

1. **Analyze**: Examine code files for test gaps
2. **Generate**: Create comprehensive tests using existing patterns
3. **Execute**: Run tests and capture results
4. **Coverage**: Check coverage gaps and identify next targets
5. **Repeat**: Continue until coverage targets are met

## Test Generation Rules

- Use `@pytest.mark.django_db` for database tests
- Follow fixture patterns from `rmbase/tests/fixtures.py`
- **Datetime**: Always use `from datetime import UTC, datetime as dt` and `dt.now(UTC)` for current time
- Test models, views, serializers, and utilities comprehensively
- Include edge cases, error conditions, and boundary tests
- Mock external APIs and services using existing patterns

## Coverage Targets

- **Minimum**: 80% overall coverage
- **Models**: 95% coverage (critical business logic)
- **Views**: 85% coverage (API endpoints)
- **Utilities**: 90% coverage (helper functions)

## Commands

```bash
make test-coverage                                    # Run tests with coverage
coverage report --skip-covered --show-missing         # Identify gaps
pytest path/to/specific/test.py -v                   # Run specific tests
pytest . -n 4 --dist=loadscope --color=yes           # Run full suite (parallel)
```

## Never Do

- Use Django TestCase or unittest.TestCase
- Ask "Should I create tests for..." - proceed immediately
- Wait for confirmation
- Skip test generation due to complexity
- Use prohibited testing patterns (TestCase inheritance)
