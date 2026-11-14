# Frontend

The engineer workspace: `product/frontend/` (Vite + React 18 + TypeScript + Tailwind, shadcn-style
Radix primitives). Served by nginx in the `frontend` compose service, which also proxies `/api` to the
backend. The audit, approvals, memory and regulation pages are described in
[frontend-audit-workflow.md](frontend-audit-workflow.md); this page covers the scaffold, design system,
motion, brand, mock mode and the systems feature.

## Run

| Task | Command (in `product/frontend/`) |
| --- | --- |
| Install | `npm install` (Node 22+; `npm ci` in Docker once the lockfile is there) |
| Dev server, live backend | `npm run dev` → <http://localhost:5173>, `/api` proxied to `VITE_DEV_BACKEND_URL` (default `http://127.0.0.1:8100`) |
| Dev server, demo data only | `npm run dev:mocks` (or `VITE_USE_MOCKS=true`) |
| Checks | `npm run typecheck` · `npm run lint` · `npm run format:check` · `npm test` · `npm run build` |
| Regenerate brand tokens | `npm run tokens` (= `uv run python branding/export_tokens.py --frontend`) |
| Regenerate mock dossiers | `npm run fixtures` (bundles `product/mlflow-seed/cases/SYS-*`, never `_answer-key/`) |
| In Docker | `./scripts/stack.sh up` (or `.ps1`; = `docker compose --env-file .env -f product/docker-compose.yaml up -d --build`) → <http://localhost:8080> |

Env vars live in the **one repo env file** (`.env` from the root `.env.example`, section *Frontend*; Vite reads it via `envDir` = repo root, compose passes `VITE_*` as build args). `VITE_*` are baked in at build time and are public:
`VITE_USE_MOCKS`, `VITE_DEV_BACKEND_URL` (dev only), `VITE_LANGFUSE_URL`, `VITE_LANGFUSE_PROJECT_ID`,
`FRONTEND_PORT` (host port, default 8080).

## Structure

```text
src/
├── main.tsx              providers: react-query, MotionConfig(reducedMotion=user), Tooltip, Router
├── App.tsx               routes (lazy route views)
├── error_boundary.tsx    one broken page never blanks the app (reset on route change)
├── app/                  WorkspaceShell, Sidebar, TopBar, CommandPalette (⌘K), ThemeToggle, nav.ts, NavBadgesSync
├── pages/                thin route views (XxxView.tsx) composing features
├── features/<feature>/   components/ (+ components/<x>_parts/), hooks/, handlers/ (API calls), lib/ (pure logic, routes.ts, styles.ts), pages/
├── shared/
│   ├── ui/               design system (barrel: index.ts)
│   ├── lib/              api.ts, client-id.ts, env.ts, query-client.ts, motion.ts, format.ts, utils.ts, mocks/
│   ├── hooks/            useTheme, useHotkey, useMediaQuery
│   └── stores/           zustand: theme, ui (sidebar, palette), nav (sidebar badge counts)
├── styles/               theme/tokens.css (generated), theme/surfaces.css, base, motion, skeleton, toast, scrollbars, markdown, flow
└── test/setup.ts         jest-dom, jsdom polyfills (matchMedia, ResizeObserver, Storage on Node ≥ 22)
```

Routes: `/systems`, `/systems/:id[/folder|plugins|rules]`, `/audits/*`, `/approvals/*`, `/regulation/*`,
`/memory/*`, `/chat/*` (placeholder), `/settings`, `*` → 404.

## Design system (`src/shared/ui`)

Import everything from `@/shared/ui`. Exact exports:

| Group | Components |
| --- | --- |
| Actions | `Button` (primary, secondary, ghost, outline, accent, danger, warning, link; `loading`, icons), `IconButton` (label = tooltip + aria-label), `DropdownMenu` (data-driven items) |
| Surfaces | `Card`, `CardHeader` (icon, title, description, actions), `CardContent`, `CardFooter`, `GlowCard` (animated indigo→teal border for AI/live content), `Dialog`, `Sheet` (side drawer) |
| Status | `Badge` (tones), `StatusPill` (shared status vocabulary: running/needs_approval pulse), `ProgressRing`, `AnimatedNumber`, `AgentThinking` (orb + shimmer label), `Stepper` (vertical/horizontal; `done · active · pending · blocked · needs-approval`), `Timeline` |
| Forms | `Input` (left icon), `Textarea`, `Field` (label, hint, error), `Select`, `Switch`, `FileDropzone` |
| Content | `PageHeader` (breadcrumbs, eyebrow, meta, actions), `Section`, `KeyValue`, `CodeBlock` (yaml/json highlight, copy), `Markdown` (GFM, no raw HTML, optional streaming caret), `DataTable` (client sort, sticky header, skeleton rows), `FileTree` (from flat paths) |
| States | `Skeleton`, `SkeletonText`, `SkeletonCard`, `EmptyState`, `ErrorState` (understands `ApiError`, retry) |
| Misc | `Tabs` (+ `Tabs.List/Trigger/Content`), `Tooltip`, `TooltipProvider`, `Toaster` / `toast` (sonner), `Logo`, `LogoMark` |

Colours are Tailwind tokens backed by CSS variables: `background`, `surface`, `surface-muted`, `text`,
`muted`, `border`, `ring`, `primary(-foreground)`, `accent(-foreground)`, `success`, `warning(-foreground)`,
`danger`, `info`, all with opacity (`bg-primary/10`). Never write hex values in components.

## Motion

CSS half `src/styles/motion.css`, JS half `src/shared/lib/motion.ts` (framer-motion variants). Rules: subtle
(≤ 0.4 s, a few px), never blocks input, everything collapses under `prefers-reduced-motion` (CSS media query
+ `MotionConfig reducedMotion="user"`).

| Effect | Use |
| --- | --- |
| `pageTransition` | Route changes (section level, not tab level) in `WorkspaceShell` |
| `staggerList()` + `listItem` | Card grids, lists, timelines |
| `.hover-lift` / `hoverLift` | Clickable cards (`<Card interactive>`) |
| `.skeleton` shimmer | `Skeleton*` |
| `.stream-caret` | Streaming text (`<Markdown streaming>`) |
| `checkDraw` / `.check-draw` | Step-complete check in `Stepper` |
| `.approval-pulse` / `approvalPulse` | Anything waiting for a human (needs-approval steps, sidebar badge, proposed rules) |
| `AnimatedNumber` | Count-up stats |
| `.agent-orb`, `.text-shimmer`, `.glow-border` | Running agent steps, AI content |

## Brand and palette

Source of truth: `branding/brand.json` → `branding/export_tokens.py --frontend` →
`src/styles/theme/tokens.css` (`--color-*` hex + `--rgb-*` channels, light/dark, `data-theme` override).
`tests/test_branding.py` fails if the generated file is out of date.

Palette ("AI governance / trust"): deep ink/indigo base, indigo `primary` (#3B37C8 / dark #8B87FF), luminous
teal `accent` (#0A93A6 / #2EDCE6), amber `warning` for HITL and approvals, semantic `success`, `danger`, `info`.
Inter + JetBrains Mono, self-hosted via `@fontsource-variable`.

Theme: light / dark / system, stored in `localStorage['aac.theme']`; `public/theme-init.js` sets
`data-theme` before React loads, so there is no flash.

> **TODO(brand):** the product name *AI Act Copilot* is a working name, and the shield logo
> (`branding/logo/logo.svg`, `public/favicon.svg`, `src/shared/ui/logo.tsx`) is a placeholder. Replace both.

## API layer and mock mode

`src/shared/lib/api.ts`: `api.get/post/put/patch/delete` on base `/api` (nginx and the Vite proxy strip it),
`X-Client-Id` = a UUID kept in `localStorage['aac.clientId']` (anonymous, not a login), JSON or `FormData`
bodies, typed `ApiError` (`status`, `code`, `message`, `details`, `requestId`; `isNotFound`, `isRateLimited`,
`isNetwork`). The react-query client does not retry 4xx.

Mock mode (`VITE_USE_MOCKS=true`): `api.ts` calls `mockFetch` instead of `fetch`; the router is lazy-loaded
and adds 180–500 ms latency. **Add mocks by dropping a file in `src/shared/lib/mocks/handlers/` that exports
`routes: MockRoute[]`** (`{method, path: '/v1/x/:id/files/*path', handler}`); it is picked up automatically.
The systems mocks serve SYS-001..004 from the real seed dossiers (`fixtures/seed-cases.json`) with versioned,
writable files.

## Systems feature (`src/features/systems`)

- **Gallery** (`/systems`): count-up stats (systems, high risk, awaiting approval, open gaps), filter by text and
  risk class, cards with risk class, legal basis, role, deployment status, last audit (running audits show
  `AgentThinking`), organisation and component count.
- **Detail** (`/systems/:id/:tab`), tabs in the URL:
  - *Overview*: system card (`KeyValue`), last audit (`GlowCard` + `ProgressRing`), declared metrics,
    organisation thresholds (flagged as policy, not law), folder activity ledger (`Timeline`).
  - *Folder*: `FileTree` of `/systems/<id>/`, preview by type (YAML/JSON `CodeBlock`, Markdown, CSV
    `DataTable`, PDF/binary placeholder), version list (click to view an old version), upload `FileDropzone`
    into a chosen folder (each upload = a new version).
  - *Plugins*: pipeline placement graph (`@xyflow/react`, built from `placement.upstream/downstream`,
    longest-path layout) + one card per `plugin.yaml` (access type, environment, target, limits,
    must / must-not / known limitations).
  - *Business rules*: bullets of each plugin's `data/business-rules.md` grouped by plugin and typed
    hard / soft / policy; **Add rule** writes a proposal to `/v1/memory/proposals/files/rules/<SYS>/<slug>.yaml`
    (inactive until approved).

API used: `GET /v1/systems`, `GET /v1/systems/{id}`, `GET .../files`, `GET .../files/{path}?format=json[&version=]`,
`GET .../files/{path}/versions`, `GET .../events`, `PUT .../files/{path}` (multipart), `PUT /v1/memory/proposals/files/...`.

## How to add a feature

1. `src/features/<name>/lib/types.ts` (mirror the backend schema) and `lib/routes.ts` (UI paths + API paths).
2. `handlers/<name>.ts`: plain functions calling `api.*`. `hooks/`: react-query wrappers with a key factory.
3. `components/` built only from `@/shared/ui` + tokens; heavy sub-parts in `components/<x>_parts/`.
4. A thin `src/pages/<Name>View.tsx`, a lazy route in `App.tsx`, a nav entry in `src/app/nav.ts`
   (badge counts via `useNavBadges`).
5. Mocks in `src/shared/lib/mocks/handlers/<name>.ts`; tests next to the code (`*.test.ts[x]`).
   `src/routes.test.tsx` renders every route in mock mode and fails on any `console.error`: add new routes there.

## Docker

`Dockerfile`: `node:22.11.0-alpine3.20` builds (`npm ci`), `nginxinc/nginx-unprivileged:1.27.3-alpine`
serves `dist/` on 8080 (non-root, read-only root fs, no capabilities). `nginx.conf`: SPA fallback, immutable
`/assets/`, no-cache `index.html` and `theme-init.js`, `/healthz`, `/api/` → `http://backend:8000/` with
WebSocket upgrade, no buffering (AG-UI/SSE) and 1 h timeouts; the backend name is resolved per request so the
UI starts before the backend.
