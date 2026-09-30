---
description: "Use when planning new features, designing technical solutions, or starting any multi-phase implementation. Covers where plans live (GitHub Issues), issue structure, phase requirements, and completion criteria."
applyTo: "**"
---

# Planning Guidelines

## Where Plans Live

**All feature plans live in GitHub Issues** — not in the repo. There is no `docs/Plans/`
directory; do not create plan markdown files.

- **One issue per feature.** The issue body IS the plan (phases, deliverables, tests).
- **Status = issue state**: open issue -> active/queued work; closed issue -> completed.
- **Phase progress** is tracked with the issue body's task-list checkboxes, plus a comment
  per completed phase recording what was actually built.
- Label plan issues `enhancement` (or `bug` for defect-driven work) and, once the `plan`
  label exists in the repo, `plan` as well so they are easy to list.

```bash
# Create a plan
gh issue create --title "<Feature>: <short title>" --label enhancement --body-file <file>

# Find active plans
gh issue list --label enhancement --state open

# Read a plan
gh issue view <number>

# Record phase completion (append, never rewrite history)
gh issue comment <number> --body "Phase 2 complete: <what was built, deviations, follow-ups>"

# Tick a phase checkbox in the body
gh issue edit <number> --body-file <updated-body-file>

# Close on completion
gh issue close <number> --comment "All phases complete."
```

Write long issue bodies to a scratch file and pass `--body-file`; do not try to inline
multi-line markdown into `--body`.

## Phase Requirements

Each phase must:

- Represent a **self-contained, deployable increment** - the codebase must remain functional after completing it
- Include **specific deliverables** (models, views, APIs, templates, etc.)
- Include **testing requirements** - unit tests and/or integration tests that verify stability
- Be **completable independently** before the next phase begins

## Issue Body Template

```markdown
## Goal

One-paragraph description of the feature and why it is wanted.

## Phase 1: <Short Title>

**Goal**: One-sentence description of what this phase delivers.

**Deliverables**:

- [ ] Item 1
- [ ] Item 2

**Tests**:

- [ ] Test coverage for item 1
- [ ] Test coverage for item 2

**Stability Criteria**: What must pass before this phase is considered complete.

## Phase 2: <Short Title>

...
```

Per-phase notes (deviations, decisions, follow-up items) go in an issue **comment** when the
phase completes, not in the body.

## Rules

- **DO plan in phases** - never design a feature as a single monolithic block
- **DO open the issue first** before starting implementation
- **DO update the issue after every phase** - tick the phase's checkboxes and add a comment
  recording what was actually built (deviations, decisions, follow-up items)
- **DO NOT skip testing requirements** - each phase must have passing tests before the next begins
- **DO NOT create plan files in the repo** - no `docs/Plans/`, no `*_PLAN.md`
- **ON COMPLETION**: close the issue (`gh issue close <number>`) once every phase is done and
  its tests pass. **Close it as part of finishing - do not ask for permission.** An issue
  with every box ticked that is still open is a stale plan, and it makes
  `gh issue list --state open` useless as a view of active work. Before closing, confirm:
  every checkbox ticked (or recorded as deferred with a reason); full suite green and
  `ruff check` clean; deployed and verified against the running system where possible;
  docs updated; and a final comment recording what was built, deferred and left over.
  An unrelated problem the work uncovered goes in a NEW issue - it is never a reason to
  leave the completed one open
- **AT THE END OF EVERY PLAN**: run `ruff check` on all modified files and fix any linting errors; also check the Problems tab and resolve all reported issues before considering the plan complete
- **UPDATE RELEVANT DOCS**: after completing a plan, update any `docs/project_docs/` files (architecture, guides, standards) that describe the changed behaviour - do not leave docs out of sync with the implementation
