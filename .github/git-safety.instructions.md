---
description: "ALWAYS ACTIVE - Git operation safety rules. Prohibits all write git operations (add, commit, push, merge, checkout). Use for any task that modifies files or could lead to git operations."
applyTo: "**/*"
---

# Git Safety Rules

## CRITICAL: NO GIT WRITE OPERATIONS

These rules are **mandatory and non-negotiable**.

| Command                 | Status                        |
| ----------------------- | ----------------------------- |
| `git add`               | NEVER - absolutely prohibited |
| `git commit`            | NEVER - absolutely prohibited |
| `git push`              | NEVER - absolutely prohibited |
| `git merge`             | NEVER - absolutely prohibited |
| `git checkout <branch>` | NEVER - absolutely prohibited |
| `git status`            | OK - read-only                |
| `git diff`              | OK - read-only                |
| `git log`               | OK - read-only                |

**Why**: The user must retain full control over version control. Automatic git commits can cause conflicts, loss of work, failed pushes, or unintended branches.

## What To Do Instead

1. Make code changes
2. **STOP** - do not run any git commands
3. Tell the user: "Changes are ready. To commit, run: `git add ... && git commit -m '...'`"
4. The user runs git commands manually

## Violation Consequence

Running `git add`, `git commit`, `git push`, `git merge`, or `git checkout` violates the fundamental safety contract of this project.
