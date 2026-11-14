# Frontend

The engineer workspace: `product/frontend/` (Vite + React 18 + TypeScript + Tailwind, shadcn-style
Radix primitives). Served by nginx in the `frontend` compose service, which also proxies `/api` to the
backend. The audit, approvals and regulation pages are described in
[frontend-audit-workflow.md](frontend-audit-workflow.md); this page covers the scaffold, information
architecture, design rules, motion, brand, mock mode, visual QA and the home and systems features.

## Run

| Task | Command (in `product/frontend/`) |
| --- | --- |
| Install | `npm install` (Node 22+; `npm ci` in Docker once the lockfile is there) |
| Dev server, live backend | `npm run dev` → <http://localhost:5173>, `/api` proxied to `VITE_DEV_BACKEND_URL` (default `http://127.0.0.1:8100`) |
| Dev server, demo data only | `npm run dev:mocks` (or `VITE_USE_MOCKS=true`) |
| Checks | `npm run typecheck` · `npm run lint` · `npm run format:check` · `npm test` · `npm run build` |
| Regenerate brand tokens | `npm run tokens` (= `uv run python branding/export_tokens.py --frontend`) |
| Regenerate mock dossiers | `npm run fixtures` (bundles `product/mlflow-seed/cases/SYS-*`, never `_answer-key/`) |
| Screenshot every route | `npm run shots` (see [Visual QA](#visual-qa)) |
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

## Information architecture

Sidebar: **Home, Systems, Audits, Approvals** (open-gate count), **Regulation, Chat**. No Settings page for now (theme toggle in
the top bar and the ⌘K palette). **Agent memory is not shown in the UI at all**: the agents decide what to remember;
the UI shows files (system folders, business rules) and audit artifacts only.

| Route | What |
| --- | --- |
| `/` | Home: what needs me now (decisions waiting, agents at work, recent findings, systems at risk, latest regulation change) |
| `/systems`, `/systems/:id[/folder\|plugins\|rules]` | Systems table and system detail |
| `/audits`, `/audits/:id[?step=<stage>]` | Audit runs table and the audit run console (`?step=` deep-links and pins a step) |
| `/approvals` | Open HITL gates; opens the approval drawer |
| `/regulation[?tab=changes\|sources]` | Regulation-change inbox and sources |
| `/chat`, `/chat/:id`, `/chat?system=&audit=` | Chat with the agents (streaming over AG-UI, tools, sub-agents, approvals, files): see [frontend-chat.md](frontend-chat.md) |
| `*` | 404 (also `/memory` and `/settings`, which were removed) |

## App shell (`src/app`)

Modelled on magenticx's `agentic_ui` (`src/app/WorkspaceShell.tsx`, `src/features/chat/components/ChatSidebar.tsx`, `src/shared/ui/sidebar.tsx`).

- **Frame + card**: the whole viewport is a tinted frame (`--shell-frame`: zinc-100 mixed with the border colour in light, near-black in dark). The sidebar rail sits directly on it (no border, no own background); the main content is a rounded card beside it (`--shell-card` = `background`, `--shell-card-radius` 1.75rem, 12 px margin top/right/bottom, `border-border/60`, soft drop shadow `--shell-card-shadow`). Below `lg` the card is full-bleed. The card is the scroll container: the `TopBar` (section label, theme toggle; menu + search buttons on mobile) sticks to its top edge, and sticky page elements stick inside it. Main keeps `px-4 py-6 lg:px-8 lg:py-8`; a full-height page (chat) bleeds with matching negative margins and sizes itself `h-[calc(var(--shell-viewport)-var(--topbar-height))]` (`--shell-viewport` = the card's inner height: `100dvh` below `lg`, minus the 12 px margins and border above).
- **Rail**: 16rem open, 4rem collapsed (`--sidebar-width[-collapsed]`), width transition 200 ms linear. Every row is `h-9 rounded-xl px-1.5` with a `size-9` icon box and 18 px icons, rows stacked with no gap; that constant lead centres each icon in the collapsed rail, so **icons stay pinned in place** while only the width animates. Labels are unmounted when collapsed and fade in on expand (`.sidebar-reveal`, 0.2 s after a 0.1 s delay). Icons grow 10 % on hover; hover/press use `--hover-surface[-strong]` (text at 6 / 10 %).
- **Active ("pinned") entry**: a soft pill in the accent colour, `bg-primary/10` + inset 1 px ring `primary/16`, behind a teal icon and medium-weight label; it glides between entries (framer `layoutId`, 220 ms ease-out tween, position only, no spring; instant under reduced motion).
- **Raised card**: the top action (Search, ⌘K) is a card on the frame (`border-border/70`, card colour, `shadow-sm`, `h-10`, 1 px border + `px-[5px]` keep the same 6 px lead); collapsed, it flattens to a plain icon row.
- **Brand row**: logo + name; when collapsed, hovering the logo swaps it for the expand icon (click expands); when open the collapse button sits at the right.
- **Feature slot**: `src/app/sidebarSlot.tsx`. A feature renders `<SidebarExtra>…</SidebarExtra>` anywhere in its page tree and the content is portalled into the scrollable region below the nav (the mobile drawer while open, else the rail; hidden while collapsed). Intended for the chat's conversation list on `/chat` routes.

## Design rules

Reference quality: Linear, Vercel, Raycast. Calm, information-first.

- **Colour**: neutral zinc surfaces (near-black in dark, white / zinc-50 in light). **One accent, teal
  (`primary`)**, used sparingly: primary actions, focus, selection, "live". **Amber (`warning`) only for "needs
  a human"** (open gates, review buttons, LLM assumptions to check). **Red/green only for verdicts** (gap /
  supports, pass / fail). No decorative gradients, glows, glass or background blobs.
- **Type**: Inter, 13 px body (`text-sm`), 11-12 px meta (`text-2xs`, `text-xs`), headings 18-28 px with tight
  tracking. Metrics, ids and durations use `.num` (tabular numbers); ids and versions in mono, durations in sans.
- **Space and shape**: 4/8 px rhythm, content max width `--content-max` (1280 px), 1 px borders for structure
  and soft shadows only for floating layers (popovers, sheets). Radii: 6 (controls), 8 (`rounded-lg`), 10
  (`rounded-xl`, cards), 12 (`rounded-2xl`, dialogs).
- **Components**: text-only page headers (breadcrumbs, title, meta, one primary action); tables over cards for
  tabular data (systems, audits); empty states with one clear action; skeletons shaped like the layout they
  replace.

## Design system (`src/shared/ui`)

Import everything from `@/shared/ui`. Exact exports:

| Group | Components |
| --- | --- |
| Actions | `Button` (primary, secondary, ghost, outline, accent, danger, warning, link; `loading`, icons), `IconButton` (label = tooltip + aria-label), `DropdownMenu` (data-driven items) |
| Surfaces | `Card`, `CardHeader` (icon, title, description, actions), `CardContent`, `CardFooter`, `GlowCard` (a teal hairline slides across the top while an agent works on it), `Dialog`, `Sheet` (side drawer) |
| Status | `Badge` (tones), `StatusPill` (shared status vocabulary; live dot for running / needs approval), `ProgressRing`, `AnimatedNumber`, `AgentThinking` (thin spinner + shimmer label), `Stepper` (vertical/horizontal; `done · active · pending · blocked · needs-approval`), `Timeline` |
| Forms | `Input` (left icon), `Textarea`, `Field` (label, hint, error), `Select`, `Switch`, `FileDropzone` |
| Content | `PageHeader` (breadcrumbs, eyebrow, meta, actions; text only, `icon` is ignored), `Section`, `KeyValue`, `CodeBlock` (yaml/json highlight, copy), `Markdown` (GFM, no raw HTML, optional streaming caret), `DataTable` (client sort, sticky header, skeleton rows), `FileTree` (from flat paths) |
| States | `Skeleton`, `SkeletonText`, `SkeletonCard`, `EmptyState`, `ErrorState` (understands `ApiError`, retry) |
| Misc | `Tabs` (+ `Tabs.List/Trigger/Content`), `Tooltip`, `TooltipProvider`, `Toaster` / `toast` (sonner), `Logo`, `LogoMark` |

Colours are Tailwind tokens backed by CSS variables: `background`, `surface`, `surface-muted`, `text`,
`muted`, `border`, `ring`, `primary(-foreground)`, `accent(-foreground)`, `success`, `warning(-foreground)`,
`danger`, `info`, all with opacity (`bg-primary/10`). Never write hex values in components.

## Motion

CSS half `src/styles/motion.css`, JS half `src/shared/lib/motion.ts` (framer-motion variants). Rules: subtle and
purposeful (150-250 ms, ease-out, 4 px at most), no springs or bounces, never blocks input, everything collapses
under `prefers-reduced-motion` (CSS media query + `MotionConfig reducedMotion="user"`).

| Effect | Use |
| --- | --- |
| `pageTransition` | Route changes (section level, not tab level) in `WorkspaceShell` |
| `staggerList()` + `listItem` | Card grids, lists, timelines |
| `.hover-lift` / `hoverLift` | Clickable cards (`<Card interactive>`): border + soft shadow, no jump |
| `.skeleton` shimmer | `Skeleton*` |
| `.stream-caret` | Streaming text (`<Markdown streaming>`) |
| `checkDraw` / `.check-draw` | Step-complete check in `Stepper` |
| `.approval-pulse` / `approvalPulse` | Anything waiting for a human (needs-approval steps, open gates in the inbox) |
| `AnimatedNumber` | Count-up stats |
| `.agent-orb` (spinner arc), `.live-dot`, `.text-shimmer`, `.glow-border` (sliding top hairline) | Running agent steps and live content |

## Brand and palette

Source of truth: `branding/brand.json` → `branding/export_tokens.py --frontend` →
`src/styles/theme/tokens.css` (`--color-*` hex + `--rgb-*` channels, light/dark, `data-theme` override).
`tests/test_branding.py` fails if the generated file is out of date.

Palette (neutral + teal): zinc surfaces (light `#FAFAFA` / `#FFFFFF`, dark `#09090B` / `#111113`), teal
`primary` = `accent` (#0F766E / dark #2DD4BF), amber `warning` for HITL, `success` / `danger` for verdicts, a
slate `info`. Inter + JetBrains Mono, self-hosted via `@fontsource-variable`.

Theme: light / dark / system, stored in `localStorage['aac.theme']`; `public/theme-init.js` sets
`data-theme` before React loads, so there is no flash.

> **TODO(brand):** the product name *AI Act Copilot* is a working name, and the logo (a teal rounded square with
> a shield-check glyph in `src/shared/ui/logo.tsx`; `branding/logo/logo.svg`, `public/favicon.svg`) is a
> placeholder. Replace both.

## API layer and mock mode

`src/shared/lib/api.ts`: `api.get/post/put/patch/delete` on base `/api` (nginx and the Vite proxy strip it),
`X-Client-Id` = a UUID kept in `localStorage['aac.clientId']` (anonymous, not a login), JSON or `FormData`
bodies, typed `ApiError` (`status`, `code`, `message`, `details`, `requestId`; `isNotFound`, `isRateLimited`,
`isNetwork`). The react-query client does not retry 4xx.

Mock mode (`VITE_USE_MOCKS=true`): `api.ts` calls `mockFetch` instead of `fetch`; the router is lazy-loaded
and adds 180–500 ms latency. **Add mocks by dropping a file in `src/shared/lib/mocks/handlers/` that exports
`routes: MockRoute[]`** (`{method, path: '/v1/x/:id/files/*path', handler}`); it is picked up automatically.
The systems mocks serve SYS-001..004 from the real seed dossiers (`fixtures/seed-cases.json`) with versioned,
writable files. Fixture timestamps go through `mocks/time.ts` (`mockTime`), which shifts them so the newest lands
a few minutes before page load: mock events read "x minutes ago", never "in x minutes" (`formatRelative` also
shows any future timestamp as "just now").

## Visual QA

`npm run shots` (`scripts/shots.mjs`) starts Vite in mock mode on a free port (never 5173 if a dev server is
running there), opens every route with Playwright Chromium (falls back to Edge) and writes
`.shots/<name>--<dark|light>--<desktop|mobile>.png` (1440×900 and 390×844; git-ignored). Interactions are
scripted for the approval drawer. Flags: `--only=<name part>`, `--theme=dark`,
`--size=desktop`, `--full` (full-page). First run: `npx playwright install chromium`. Look at the PNGs after
every visual change.

## Home (`src/features/home`)

`/`: one glance = what needs me now. Headline ("1 decision waiting for you" / "All clear"), **Needs your
decision** (open gates, *Review* opens the approval drawer in place), **Agents at work** (live audits with the
current step and progress), **Recent findings** (latest finished audit: verdict, metric, link to the step),
**Systems at risk** (open gaps or high risk) and **Latest regulation change**.

## Systems feature (`src/features/systems`)

- **Table** (`/systems`): one stat strip (systems, high risk, awaiting approval, open gaps), filter by text and
  risk class, one row per system (name, id, organisation, role, legal basis, risk class, deployment, last audit
  with live state, gap count).
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
    hard / soft / policy; **Add rule** appends the rule as a bullet to the chosen plugin's
    `data/business-rules.md` (under a "… added in the UI" heading that parses back with the same kind), saved as
    a new file version with the *Why* as the version reason.

API used: `GET /v1/systems`, `GET /v1/systems/{id}`, `GET .../files`, `GET .../files/{path}?format=json[&version=]`,
`GET .../files/{path}/versions`, `GET .../events`, `PUT .../files/{path}` (multipart, or JSON `{content, reason}` for an added rule).

## How to add a feature

1. `src/features/<name>/lib/types.ts` (mirror the backend schema) and `lib/routes.ts` (UI paths + API paths).
2. `handlers/<name>.ts`: plain functions calling `api.*`. `hooks/`: react-query wrappers with a key factory.
3. `components/` built only from `@/shared/ui` + tokens; heavy sub-parts in `components/<x>_parts/`.
4. A thin `src/pages/<Name>View.tsx`, a lazy route in `App.tsx`, a nav entry in `src/app/nav.ts` only if it is
   a top-level destination (badge counts via `useNavBadges`); otherwise put it in context (a tab or a sheet).
5. Mocks in `src/shared/lib/mocks/handlers/<name>.ts`; tests next to the code (`*.test.ts[x]`).
   `src/routes.test.tsx` renders every route in mock mode and fails on any `console.error`: add new routes there,
   and add them to `SHOTS` in `scripts/shots.mjs`.

## Docker

`Dockerfile`: `node:22.11.0-alpine3.20` builds (`npm ci`), `nginxinc/nginx-unprivileged:1.27.3-alpine`
serves `dist/` on 8080 (non-root, read-only root fs, no capabilities). `nginx.conf`: SPA fallback, immutable
`/assets/`, no-cache `index.html` and `theme-init.js`, `/healthz`, `/api/` → `http://backend:8000/` with
WebSocket upgrade, no buffering (AG-UI/SSE) and 1 h timeouts; the backend name is resolved per request so the
UI starts before the backend.
