# Frontend

The engineer workspace: `mnamon/frontend/` (Vite + React 18 + TypeScript + Tailwind, shadcn-style
Radix primitives). Served by nginx in the `frontend` compose service, which also proxies `/api` to the
backend. The audit, approvals and regulation pages are described in
[frontend-audit-workflow.md](frontend-audit-workflow.md); this page covers the scaffold, information
architecture, design rules, motion, brand, mock mode, visual QA and the home and systems features.

## Run

| Task | Command (in `mnamon/frontend/`) |
| --- | --- |
| Install | `npm install` (Node 22+; `npm ci` in Docker once the lockfile is there) |
| Dev server, live backend | `npm run dev` → <http://localhost:5173>, `/api` proxied to `VITE_DEV_BACKEND_URL` (default `http://127.0.0.1:8100`) |
| Dev server, demo data only | `npm run dev:mocks` (or `VITE_USE_MOCKS=true`) |
| Checks | `npm run typecheck` · `npm run lint` · `npm run format:check` · `npm test` · `npm run build` |
| Regenerate brand tokens | `npm run tokens` (= `uv run python branding/export_tokens.py --frontend`) |
| Regenerate mock dossiers | `npm run fixtures` (bundles `mnamon/mlflow-seed/cases/SYS-*`, never `_answer-key/`) |
| Screenshot every route | `npm run shots` (see [Visual QA](#visual-qa)) |
| In Docker | `./scripts/stack.sh up` (or `.ps1`; = `docker compose --env-file .env -f mnamon/docker-compose.yaml up -d --build`) → <http://localhost:8080> |

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
├── styles/               theme/{tokens (generated), semantic, shape, components}.css, base, misc, motion, skeleton, toast, scrollbars, markdown, flow (see Theming)
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
- **Top bar slot**: `src/app/topbarSlot.tsx`. A page renders `<TopbarExtra>…</TopbarExtra>` and the content replaces the top bar's section label (and the mobile search button); the menu button and theme toggle stay. Used by the chat for its header row (agent picker, subject, actions).

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
| Files | `FileChip` (`composer` · `message` · `row`; `FileAction` extra actions), `fileKindIcon`, `ImageGrid` (in-message thumbnails → lightbox), `ImageLightbox` (zoom, ←/→, download), `FilePreviewPanel` (modal preview by kind) + `FilePreviewBody` (inline), `downloadPreviewFile`, `PreviewFile` |

**Files and images** (ports of magenticx's attachment UX, one implementation for chat, the system folder and audits).
Data in, callbacks out: a surface hands `FileChip` / `ImageGrid` its files and handlers, and the preview a `PreviewFile`
(`{id, name, mime, size, load: () => Promise<Blob>}`), so nothing in `shared/` knows the API. Pure helpers live in
`src/shared/lib/files.ts` (`classifyFile` → kind / previewable / label / language by MIME then extension, `guessMime`,
`formatFileSize`, `fileSubtitle`, `parseCsv`, `blobFromBase64`, `downloadName`, `triggerBrowserDownload`) and
`src/shared/hooks/useFileBlob.ts` (`useFileBlob`, `useObjectUrl`). The lightbox and the preview are Radix Dialogs (focus trap,
Escape that closes only them, focus return) moving with `panelBackdrop` / `panelContent` from `motion.ts` on `bg-scrim-strong`.
PDF frames get an object URL forced to `application/pdf`, DOCX is converted by mammoth (lazy) into a script-less sandboxed
frame coloured from our tokens, SVG is never previewed.

Colours are Tailwind tokens backed by CSS variables (see Theming): `background`, `foreground` (= `text`),
`surface` (+ `-raised`, `-sunken`; `surface-muted` = `sunken`), `muted`, `border`, `ring`,
`primary|accent|success|warning|danger|info` each with `-foreground`, `chart-1..5`, all with opacity
(`bg-primary/10`); plus full-colour component tokens `hover(-strong)`, `shell-frame`, `shell-card`, `topbar`,
`scrim` (+ `scrim-strong` for the lightbox and preview), `switch-thumb`. Never write hex, `rgb()`, or Tailwind palette colours (`white`, `black`, `zinc-*`) in
components.

## Theming

Organised like magenticx `agentic_ui` (`src/styles/theme/`): four layers, imported in this order by `src/index.css`
(the single entry point; one file per concern after them, Tailwind last).

| Layer | File | Holds | Change it for |
| --- | --- | --- | --- |
| 1. Brand palette | `theme/tokens.css` (**generated**, do not edit) | `--color-*` (hex) + `--rgb-*` (channels) for light, dark and `prefers-color-scheme` | Nothing: edit `branding/brand.json` and regenerate |
| 2. Semantic | `theme/semantic.css` | Roles as `R G B` channels: `--background`, `--foreground`, `--surface(-raised/-sunken)`, `--muted-foreground`, `--border`, `--ring`, `--primary`, `--accent`, status + `-foreground`, `--chart-1..5`, `--hover-surface(-strong)`, `--selection`, `--focus-ring*` | Re-mapping a role (e.g. raised surfaces, chart order) |
| 3. Shape | `theme/shape.css` | Radii (`--radius-sm..2xl`), shadows (`--shadow-sm/soft/pop`, light + dark), layout sizes (`--content-max`, `--topbar-height`, `--sidebar-width*`), easing and durations | Corners, depth, spacing of the shell |
| 4. Components | `theme/components.css` | `--shell-frame/card/card-radius/card-shadow`, `--topbar-bg`, `--nav-active-*`, `--scrim`, `--switch-thumb`, `--toast-*`, `--skeleton-*`, `--scrollbar-*`, `--flow-*` | One component's look |

- `tailwind.config.ts` reads **only** these vars (colours, radii, shadows, widths); components use Tailwind
  classes or, for inline styles / SVG / charts, `color('primary', 0.2)` from `src/shared/lib/consts/ui.ts`.
- Repeated class recipes live in `src/shared/lib/consts/ui.ts` (`INTERACTIVE_SURFACE`, `INTERACTIVE_SURFACE_QUIET`,
  `RAISED_ON_FRAME`): plain Tailwind strings, so `cn()` can still merge them.
- Dark mode: `data-theme="light|dark"` on `<html>` (set before paint by `public/theme-init.js`, then by
  `src/shared/stores/theme.ts`); Tailwind `dark:` matches `[data-theme="dark"]`. Layers 2-4 derive from the palette,
  so only layers 1, 3 and 4 have dark overrides.
- Optional brand keys (no rename needed): add `success_foreground`, `danger_foreground`, `info_foreground` or
  `chart_1`..`chart_5` to both palettes in `brand.json` and they override the fallbacks in `semantic.css`.

**Re-theme the whole app (light + dark):** edit the colours in `branding/brand.json`, then run
`npm run tokens` in `mnamon/frontend/` (= `uv run python branding/export_tokens.py --frontend` from the repo
root). Vite hot-reloads the result; `tests/test_branding.py` fails if `tokens.css` is stale.

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

Palette (Mnamon, from `branding/source/color-palette.pdf`): parchment light theme (`#F4F1EA` page, `#FBF9F4`
cards, `#E9E3D6` wells) and ink dark theme (`#13171F` / `#1D2330`); terra `primary` (light terra-deep `#9E4A17`,
dark `#D2773A` with ink text), lex `accent` and `info` (light `#2F5F80`, dark `#7FB0D1`), ochre `warning` for HITL,
`success` / `danger` for verdicts; every pair is WCAG AA (`tests/test_branding.py`). Fonts: EB Garamond for the
wordmark and page titles (`h1`), Inter for everything else, JetBrains Mono for code, all self-hosted via
`@fontsource-variable`.

Theme: light / dark / system, stored in `localStorage['aac.theme']`; `public/theme-init.js` sets
`data-theme` before React loads, so there is no flash.

Brand: **Mnamon**, the AI Act Governance Copilot. `src/shared/ui/logo.tsx` draws the mark (`LogoMark`, striped;
`solid` for tiny sizes) from the `--logo-lex` / `--logo-terra` tokens, so it follows the theme, plus the MNAMON
`Wordmark`; `PRODUCT_NAME` / `PRODUCT_DESCRIPTOR` mirror `brand.json`. `public/favicon.svg`, `favicon.ico` and
`apple-touch-icon.png` are copies of `branding/logo/`.

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
