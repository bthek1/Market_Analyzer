---
name: feedback-conventions
description: Key project conventions and rules confirmed by the CLAUDE.md and completed work
metadata:
  type: feedback
---

## No git write operations
Never run `git add`, `git commit`, `git push`, `git merge`, or `git checkout <branch>`. Tell user what to commit and let them run it manually.

**Why:** Explicit git safety rule in CLAUDE.md.
**How to apply:** After any code change, describe what to stage/commit but don't run git write commands.

## Pytest only — no unittest/TestCase
Always use `@pytest.mark.django_db` and plain pytest classes. Never import from `django.test` or `unittest`.

**Why:** CLAUDE.md mandate; project is 100% pytest-based.
**How to apply:** All new backend tests follow pytest fixture pattern with `@pytest.mark.django_db`.

## No markdown summary files after tasks
Never create `TASK-COMPLETE.md`, `SUMMARY.md`, progress tracker files, etc. unless explicitly requested.

**Why:** CLAUDE.md end-of-task rule.
**How to apply:** After completing any task, do not generate any new `.md` files unless the user asks.

## Plans live in GitHub Issues, not in the repo
Multi-phase features get a GitHub issue whose body is the phased plan. Open issue = active, closed issue = done. `docs/Plans/` no longer exists — never create plan markdown files.

**Why:** CLAUDE.md planning convention (changed 2026-09-16 from `docs/Plans/In_progress/` → `Completed/` markdown files to GitHub Issues).
**How to apply:** Before implementing, `gh issue create --title "<Feature>: ..." --label enhancement --body-file <scratch file>`. Tick phase checkboxes + comment what was built after each phase, then `gh issue close <n>` on completion. See `.github/planning.instructions.md`.

## Run ruff check at end of every plan
**Why:** CLAUDE.md end-of-plan rule.
**How to apply:** Always run `just be-lint` as the final step before marking a backend plan complete.

## Frontend is for rendering only — all computed values come from the backend
The frontend should only render data returned by the API. Aggregations, filtering, hierarchy building, derived metrics, and any other non-trivial data transformations must be implemented as backend API endpoints (views/services), not in hooks or components.

**Why:** The user's explicit architectural rule. Client-side computation like `useMarketHierarchy` (assembles sector→industry→company tree from 3 separate fetches) is the anti-pattern to avoid.
**How to apply:** If a hook or component is doing `map/filter/reduce` across API data to compute a derived value, that logic belongs in a backend `services.py` function exposed through a dedicated endpoint. Frontend hooks should only call API functions and pass data to components.

## permission_classes must be a tuple, not a bare class or list
Always write `permission_classes = (IsAuthenticated,)` — never `permission_classes = IsAuthenticated` (bare class) or `[IsAuthenticated]` (list).

**Why:** DRF iterates `permission_classes` to instantiate each permission. A bare class raises `TypeError: 'BasePermissionMetaclass' object is not iterable`. The project convention is the tuple form.
**How to apply:** Every `APIView`, `generics.*`, and `ModelViewSet` subclass must use a tuple with a trailing comma.

## Never edit files directly on prod via SSH
Never use SSH to patch files on the prod server (e.g. `sed -i` on deploy.sh). All changes must be made locally and pushed through git so prod self-updates via the deploy pipeline.

**Why:** Direct prod edits get overwritten by the next `git pull`, create uncommitted local state on prod that blocks future pulls, and bypass the normal review/deploy flow.
**How to apply:** If a prod file needs fixing, edit it locally, tell the user to commit and push, and let the CI/CD pipeline deploy it.
