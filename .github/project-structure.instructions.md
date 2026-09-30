---
description: "Use when adding new Django apps, DRF views/serializers/services, frontend routes, API hooks, Zustand stores, or understanding the project layout. Covers the full monorepo structure, naming conventions, file placement rules, and data-flow patterns for this Django + DRF + React project."
applyTo: "**/*"
---

# Django + DRF + React Project Structure

## Monorepo Layout

```
/
├── backend/                    Django REST API (Python 3.13)
│   ├── core/                   Project config (settings, URLs, Celery)
│   │   ├── settings/
│   │   │   ├── base.py         Shared settings (DB, auth, Celery, JWT, installed apps)
│   │   │   ├── dev.py          Debug=True, CORS allow-all
│   │   │   ├── prod.py         HTTPS, allowed hosts, static files
│   │   │   └── test.py         SQLite, fast password hasher
│   │   ├── celery.py           Celery app (auto-discovers tasks.py in all apps)
│   │   ├── urls.py             Top-level URL router
│   │   └── wsgi.py / asgi.py
│   ├── apps/                   One Django app per domain
│   │   ├── accounts/           Auth (CustomUser, JWT endpoints)
│   │   ├── companies/          Company/Sector CRUD + yfinance ingestion
│   │   ├── llm_analysis/       Ollama LLM workflows (10 agent kinds, SSE)
│   │   ├── knowledge_graph/    Self-expanding concept graph
│   │   ├── codegraph/          Read-only API over the graphify code graph (no models)
│   │   ├── redis_monitor/      Read-only Redis introspection (no models)
│   │   ├── tasks/              Celery Beat schedule management
│   │   └── embeddings/         PLANNED — RAG pipeline (not yet built)
│   ├── conftest.py             Root pytest fixtures
│   ├── manage.py
│   └── pyproject.toml          Dependencies (uv), pytest + ruff config
├── frontend/                   React SPA (TypeScript, Vite)
│   └── src/
│       ├── api/                Axios client + endpoint functions + query keys
│       ├── components/         React components (ui/, layout/, feature folders)
│       ├── hooks/              Custom hooks — business logic only, no JSX
│       ├── routes/             TanStack Router file-based routes
│       ├── schemas/            Zod validation schemas (one file per domain)
│       ├── store/              Zustand stores (one file per concern)
│       ├── types/              TypeScript types matching API response shapes
│       └── lib/                Utilities: cn(), date wrappers
├── docs/                       Knowledge base — kept in sync with code
├── models/                     HuggingFace model weights cache (gitignored)
├── justfile                    Task runner
└── docker-compose.yml
```

---

## Backend Structure

### Rule: one app per domain

Each Django app in `apps/` owns a single business domain.
Never put logic from one domain into another app's files.

```
apps/
├── accounts/         → auth, user management
├── companies/        → companies, sectors, price/financial ingestion
├── llm_analysis/     → LLM workflows and their run history
├── knowledge_graph/  → concept graph expansion
├── codegraph/        → the graphify code graph, read-only
├── redis_monitor/    → Redis introspection, read-only
└── tasks/            → Celery Beat schedules
```

**Code navigation aid.** `graphify` indexes this repo into `graphify-out/graph.json`
(gitignored, rebuilt by a post-commit hook). `graphify affected "<symbol>"` gives the
transitive blast radius of a change and `graphify explain "<symbol>"` gives call sites
with `file:line`. **Backend only** — it does not resolve `tsconfig.json` `@/` path
aliases, so the TypeScript call graph is essentially absent (73% of TS nodes isolated).
Use grep for frontend questions.

**Not every app needs models.** A read-only app that projects an external source
(`codegraph` reads a JSON artefact, `redis_monitor` reads Redis) has no `models.py`
and no migrations — but still keeps the same layering: `services.py` owns all
access and normalisation, `views.py` stays HTTP-only.

### File responsibilities within each app

| File | What goes here | What does NOT go here |
|---|---|---|
| `models.py` | Django models, model methods, `Meta` | Business logic, HTTP concerns |
| `serializers.py` | DRF serializers, field validation | Business logic, ORM queries |
| `services.py` | Business logic, ORM queries, external calls | HTTP concerns, serializers |
| `views.py` | HTTP plumbing only (auth, parse, delegate to services) | Business logic |
| `urls.py` | URL patterns for this app only | — |
| `tasks.py` | Celery async tasks (call into services) | Business logic |
| `admin.py` | Django admin registrations | — |
| `tests/` | pytest tests, one file per layer | — |

### View conventions

Always use class-based views. No function-based views.

```python
from rest_framework.views import APIView
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

# Simple action → APIView
class DocumentSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SearchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        results = services.search_similar_chunks(
            query=serializer.validated_data["query"],
            top_k=serializer.validated_data.get("top_k", 5),
        )
        return Response(SearchResultSerializer(results, many=True).data)

# CRUD resource → generics.*
class DocumentListCreateView(generics.ListCreateAPIView):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        doc = serializer.save()
        tasks.ingest_document.delay(str(doc.pk))
```

### Serializer conventions

```python
from rest_framework import serializers
from .models import Document

class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ["id", "title", "source", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

    def validate_title(self, value):
        # Validation logic lives in the serializer
        if len(value.strip()) < 3:
            raise serializers.ValidationError("Title must be at least 3 characters.")
        return value.strip()
```

Never use `JsonResponse`. Always use DRF's `Response`.
Never raise raw `Http404` — use `get_object_or_404` or let DRF handle it.

### URL registration

Each app owns its own `urls.py`, included from `core/urls.py`:

```python
# core/urls.py
urlpatterns = [
    path("api/token/",         TokenObtainPairView.as_view()),
    path("api/token/refresh/", TokenRefreshView.as_view()),
    path("api/accounts/",      include("apps.accounts.urls")),
    path("api/embeddings/",    include("apps.embeddings.urls")),
    path("api/chat/",          include("apps.chat.urls")),
    path("api/researcher/",    include("apps.researcher.urls")),
]
```

All endpoints start with `/api/`.

### Auth model

```python
# ALWAYS use get_user_model() — never import User directly
from django.contrib.auth import get_user_model
User = get_user_model()   # → accounts.CustomUser

# AUTH_USER_MODEL = "accounts.CustomUser"  (set in base.py)
# CustomUser uses email as USERNAME_FIELD, UUID primary key, no username field
```

### Settings split

```
core/settings/
├── base.py    → installed apps, middleware, DB, auth, Celery, JWT, static files
├── dev.py     → DEBUG=True, CORS allow-all, sqlite optional
├── prod.py    → HTTPS, ALLOWED_HOSTS, whitenoise
└── test.py    → DJANGO_SETTINGS_MODULE used by pytest
```

`DJANGO_SETTINGS_MODULE` is set via `pyproject.toml` `[tool.pytest.ini_options]`.

### Primary keys

Always use UUID primary keys for all models:

```python
import uuid
from django.db import models

id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
```

### N+1 prevention

Always use `select_related` / `prefetch_related` in views and services:

```python
# Good
Chunk.objects.select_related("document").filter(...)

# Bad — causes N+1
for chunk in Chunk.objects.all():
    print(chunk.document.title)   # separate query per chunk
```

---

## Frontend Structure

### File placement rules

| Directory | What goes here |
|---|---|
| `src/api/` | Axios client, endpoint functions, query keys, QueryClient instance |
| `src/components/ui/` | shadcn/ui components (generated, never edit directly) |
| `src/components/<feature>/` | Feature-specific components (e.g., `rag/`, `chat/`) |
| `src/components/layout/` | Shell, nav bar, sidebar |
| `src/hooks/` | Custom hooks with business logic, no JSX |
| `src/routes/` | TanStack Router file-based route files |
| `src/schemas/` | Zod validation schemas (one file per domain) |
| `src/store/` | Zustand stores (one file per concern) |
| `src/types/` | TypeScript types from API contracts |
| `src/lib/` | `cn()` utility, `date.ts` wrappers |

### State management rules

| State type | Tool |
|---|---|
| Server data (API responses) | TanStack Query — `useQuery`, `useMutation`, `useInfiniteQuery` |
| Global / UI state | Zustand store in `src/store/` |
| Local component state | `useState` / `useReducer` |

**Critical: never put server-fetched data in Zustand.**

### API layer

All HTTP calls go through the Axios instance in `src/api/client.ts`:

```typescript
// src/api/client.ts
import axios from "axios";

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
});

// Attach JWT token on every request
client.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Silent 401 refresh — retry original request once
client.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401 && !error.config._retry) {
      error.config._retry = true;
      const refresh = localStorage.getItem("refresh_token");
      const { data } = await axios.post("/api/token/refresh/", { refresh });
      localStorage.setItem("access_token", data.access);
      error.config.headers.Authorization = `Bearer ${data.access}`;
      return client(error.config);
    }
    return Promise.reject(error);
  }
);

export default client;
```

### Query keys

Centralize all TanStack Query keys in `src/api/queryKeys.ts`:

```typescript
export const queryKeys = {
  documents: {
    all:    ["documents"] as const,
    detail: (id: string) => ["documents", id] as const,
    chunks: (id: string) => ["documents", id, "chunks"] as const,
  },
  search: {
    results: (query: string) => ["search", query] as const,
  },
};
```

### Mutation pattern

Mutations must invalidate relevant queries on success:

```typescript
const mutation = useMutation({
  mutationFn: (data: CreateDocumentRequest) => api.createDocument(data),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
  },
});
```

### Zustand store pattern

```typescript
// src/store/auth.ts
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

interface AuthState {
  isAuthenticated: boolean;
  setAuthenticated: (value: boolean) => void;
}

export const useAuthStore = create<AuthState>()(
  immer((set) => ({
    isAuthenticated: false,
    setAuthenticated: (value) =>
      set((s) => { s.isAuthenticated = value; }),
  }))
);
```

Always use `immer` middleware. One file per concern.

### Zod + React Hook Form pattern

```typescript
// src/schemas/document.ts
import { z } from "zod";

export const uploadDocumentSchema = z.object({
  title: z.string().min(3, "Title must be at least 3 characters"),
  file:  z.instanceof(File).optional(),
});
export type UploadDocumentSchema = z.infer<typeof uploadDocumentSchema>;
```

```tsx
// In component
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { uploadDocumentSchema, type UploadDocumentSchema } from "@/schemas/document";

const form = useForm<UploadDocumentSchema>({
  resolver: zodResolver(uploadDocumentSchema),
});
```

### TanStack Router route conventions

File-based routes under `src/routes/`. Nested routes use dot notation:

| File | Route |
|---|---|
| `index.tsx` | `/` |
| `login.tsx` | `/login` |
| `rag.tsx` | `/rag` (layout) |
| `rag.documents.tsx` | `/rag/documents` |
| `rag.search.tsx` | `/rag/search` |
| `rag.chat.tsx` | `/rag/chat` |

Loaders pre-fetch data before render:

```typescript
export const Route = createFileRoute("/rag/documents")({
  loader: () => queryClient.ensureQueryData({
    queryKey: queryKeys.documents.all,
    queryFn:  api.listDocuments,
  }),
  component: DocumentsPage,
});
```

### Import alias

Always use `@/` (resolves to `src/`). Never use relative `../../` imports across feature boundaries.

```typescript
// Good
import { cn } from "@/lib/utils";
import { useDocuments } from "@/hooks/useDocuments";

// Bad
import { cn } from "../../../lib/utils";
```

### Styling rules

- **Tailwind CSS v4:** CSS-first config via `@import "tailwindcss"` in `src/index.css`. No `tailwind.config.js`.
- **shadcn/ui:** install via `npx shadcn@latest add <component>`. Never edit generated files in `src/components/ui/`.
- Use `cn()` from `src/lib/utils.ts` for all conditional class merging.

---

## Endpoint Naming Conventions

| Pattern | Example |
|---|---|
| List + Create | `GET/POST /api/companies/companies/` |
| Retrieve + Update + Delete | `GET/PATCH/DELETE /api/knowledge/concepts/<id>/` |
| Sub-resource list | `GET /api/companies/companies/<id>/prices/` |
| Action on resource | `POST /api/knowledge/concepts/<id>/expand/` |
| Standalone action | `POST /api/llm/react/`, `GET /api/codegraph/graph/` |
| Auth tokens | `POST /api/token/`, `POST /api/token/refresh/` |

---

## Adding a New Feature — Checklist

### Backend

1. Create (or reuse) the app under `apps/<domain>/`
2. Define model in `models.py` with UUID PK
3. Run `just be-makemigrations <app>` + `just be-migrate`
4. Write serializer in `serializers.py`
5. Put business logic in `services.py`
6. Write class-based view in `views.py` — delegate to services
7. Add URL pattern in `urls.py`
8. Include in `core/urls.py` under `/api/<domain>/`
9. Write tests in `tests/`
10. Update the architecture notes in `CLAUDE.md` and any affected file under `docs/project_docs/`

### Frontend

1. Add Zod schema in `src/schemas/<domain>.ts`
2. Add TypeScript types in `src/types/<domain>.ts`
3. Add query key constants in `src/api/queryKeys.ts`
4. Add API functions in `src/api/<domain>.ts`
5. Extract business logic into a custom hook in `src/hooks/use<Feature>.ts`
6. Build components in `src/components/<feature>/`
7. Create route file in `src/routes/<path>.tsx` and add it to `NAV_LINKS` in `AppShell.tsx`
8. Write tests under `__tests__/` beside the component or route
9. Update `docs/UI/ui-structure.md` — page tree, the page's own section, and the component inventory

---

## Environment Variables

### Backend (`.env`)

```
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql+psycopg://appuser:apppassword@localhost:5434/appdb
CELERY_BROKER_URL=redis://localhost:6379/0
ANTHROPIC_API_KEY=sk-ant-...
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=analysis-assistant
OLLAMA_EMBED_MODEL=nomic-embed-text
```

### Frontend (`.env`)

```
VITE_API_BASE_URL=http://localhost:8004
```

All frontend env vars must be prefixed with `VITE_` and accessed via `import.meta.env.VITE_*`.

---

## Task Runner Quick Reference

```bash
just dev              # Start all services (DB, Redis, backend, frontend, Celery)
just db-up            # Start only DB + Redis in Docker
just be-dev           # Django dev server (runs migrations first)
just be-test          # Backend pytest suite
just be-makemigrations [app]  # Generate migrations
just be-migrate       # Apply migrations
just be-lint          # ruff check
just be-fmt           # ruff format
just be-celery        # Start Celery worker locally
just fe-dev           # Vite dev server
just fe-test          # Frontend Vitest suite
just fe-build         # Production build
```
