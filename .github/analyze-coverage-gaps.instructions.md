---
description: "Use when analyzing test coverage reports, identifying coverage gaps, prioritizing which files to test next, or finding the highest impact areas for test generation."
---

# Coverage Gap Analysis Instructions

When asked to analyze coverage, follow this process:

## Analysis Tasks

1. **Parse coverage data** - identify files with <80% coverage
2. **Prioritize by impact** - focus on critical business logic first
3. **Identify patterns** - look for similar untested code that can be batch-generated
4. **Suggest next targets** - recommend specific files/functions to test next

## Priority Matrix

- **High Priority**: Models, core business logic, API endpoints
- **Medium Priority**: Utilities, helpers, managers
- **Low Priority**: Configuration, migrations, static files

## Commands

```bash
make test-coverage
coverage report --skip-covered --show-missing
pytest . --cov --cov-report=term-missing
```

## Output Format

Provide a ranked list of files to target next:

```
NEXT TEST TARGETS (by priority):
1. path/to/critical/file.py - Missing: model validation, edge cases
2. path/to/important/views.py - Missing: error handling, permissions
3. path/to/utility.py - Missing: boundary conditions, null handling
```

Focus on files that will maximize coverage improvement with minimal effort.
