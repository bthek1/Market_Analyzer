---
description: "Use when executing test suites, running tests and analyzing results, checking test pass/fail status, measuring coverage progress, or iterating on test generation after a test run."
---

# Test Execution and Analysis Instructions

## Execution Steps

1. **Run full test suite**: `make test-coverage`
2. **Generate coverage report**: extract uncovered lines
3. **Analyze failures**: identify patterns in failing tests
4. **Measure progress**: compare against previous coverage metrics

## Analysis Framework

- **Coverage Gaps**: which functions/branches need tests?
- **Test Quality**: are tests comprehensive or just hitting lines?
- **Failure Patterns**: common causes of test failures
- **Next Actions**: specific tests to generate next

## Success Metrics

- Overall coverage percentage
- Number of uncovered lines reduced
- Test execution speed
- Test reliability (pass/fail ratio)

## Commands

```bash
make test-coverage
pytest . -n 4 --dist=loadscope --color=yes
pytest path/to/test.py -v
coverage report --skip-covered --show-missing
```

## Output Requirements

After running, report:

```
COVERAGE STATUS:
- Current: XX%
- Target: 80%+
- Gap: XX uncovered lines

NEXT ACTIONS:
1. Generate tests for: [specific file/function]
2. Fix failing tests in: [specific area]
3. Improve coverage in: [priority modules]
```

Continue iterating until coverage targets are met.
