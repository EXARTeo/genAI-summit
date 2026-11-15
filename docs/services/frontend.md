# Frontend

The engineer workspace: `mnamon/frontend/` (Vite + React 18 + TypeScript + Tailwind, shadcn-style
Radix primitives). Served by nginx in the `frontend` compose service, which also proxies `/api` to the
backend. The audit and regulation pages are described in
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

Sidebar: **Home, Systems, Audits** (badge = open HITL gates), **Regulation, Chat**. There is no Approvals page: gates are decided on the audit page (or from Home / Telegram), and `/approvals` redirects to `/audits`. No Settings page for now (theme toggle in
the top bar and the ⌘K palette). **Agent memory is not shown in the UI at all**: the agents decide what to remember;
the UI shows files (system folders, business rules) and audit artifacts only.

| Route | What |
| --- | --- |
| `/` | Home: what needs me now (decisions waiting, agents at work, recent findings, systems at risk, latest regulation change) |
| `/systems`, `/systems/:id[/status\|obligations\|folder\|plugins\|rules]` | Systems table and system detail; **Status** = the findings register (`features/register`): the system's state per obligation across audits (summary tiles, `FilterBar` facets State / Verdict / Severity / Chapter, history timeline with each audit linked, close with a reason / reopen). The Overview has a Status card and the audit Findings view marks each finding New / Still open / Fixed / Regressed / Accepted risk (with a filter) |
| `/audits`, `/audits/:id[?step=<stage>][&view=findings\|report]` | Audit runs table and the audit run console (`?step=` deep-links and pins a step; `?view=` opens the Findings or Report view) |
| `/regulation[?tab=changes\|sources]` | Regulation-change inbox and sources |
| `/chat`, `/chat/:id`, `/chat?system=&audit=` | Chat with the agents (streaming over AG-UI, tools, sub-agents, approvals, files; the agent map and plan panels beside the composer): see [frontend-chat.md](frontend-chat.md) |
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
The systems mocks serve SYS-001..003 from the real seed dossiers (`fixtures/seed-cases.json`) with versioned,
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

`/`: one glance = what needs me now. Headline ("1 decision waiting for you" / "All clear"), **Waiting for
you** (open gates; the row links to the audit at its gate step, *Review* opens the approval drawer in place),
**Agents at work** (live audits with the current step and progress), **Recent findings** (latest finished audit's
sealed findings, gaps first, link to its Findings view),
**Systems at risk** (open gaps or high risk) and **Latest regulation change**.

## Systems feature (`src/features/systems`)

- **Table** (`/systems`): one stat strip (systems, high risk, awaiting approval, open gaps), filter by text and
  risk class, one row per system (name, id, organisation, role, legal basis, risk class, deployment, last audit
  with live state, gap count).
- **Detail** (`/systems/:id/:tab`), tabs in the URL:
  - *Overview*: system card (`KeyValue`), last audit (`GlowCard` + `ProgressRing`), declared metrics,
    organisation thresholds (flagged as policy, not law), folder activity ledger (`Timeline`).
  - *Obligations* (`ObligationsTab`, read-only): the latest audit's `obligation_map` artifact joined with the
    system's current sealed findings (`GET /v1/systems/{id}/findings?current=true`): obligation (article + id),
    applies?, why (+ decided by), in force from (in force / not yet), verification mode, latest verdict and a
    *Stale* badge. Table on wide screens, one card per obligation on phones.
  - *Folder*: `FileTree` of `/systems/<id>/`, preview by type (YAML/JSON `CodeBlock`, Markdown, CSV
    `DataTable`, PDF/binary placeholder), version list (click to view an old version), upload `FileDropzone`
    into a chosen folder (each upload = a new version).
  - *Plugins*: where the engineer configures a **plugin**, the wrapper around one model (how the audit agent
    calls it). See [Plugins tab](#plugins-tab) below.
  - *Business rules*: bullets of each plugin's `data/business-rules.md` grouped by plugin and typed
    hard / soft / policy; **Add rule** appends the rule as a bullet to the chosen plugin's
    `data/business-rules.md` (under a "… added in the UI" heading that parses back with the same kind), saved as
    a new file version with the *Why* as the version reason.

API used: `GET /v1/systems`, `GET /v1/systems/{id}`, `GET .../files`, `GET .../files/{path}?format=json[&version=]`,
`GET .../files/{path}/versions`, `GET .../events`, `PUT .../files/{path}` (multipart, or JSON `{content, reason}` for an added rule).

### Register a system and risk classification (plan 02)

- **Register a system** (`/systems/new`, `features/onboarding`, page `RegisterSystemView`; button on the
  Systems table): five steps on the shared `Stepper` for the PM, documents only (no models, no pipeline):
  *Identity* (id proposed as the next free `SYS-NNN`, checked against `SYSTEM_ID_PATTERN` and the ids in use;
  name, organisation; how you got it: `in_house` / `as_is` / `modified`, the Art. 25 role hint), *Purpose*
  (what it does, intended purpose, decision it informs, human oversight, profiling yes / no / not sure),
  *Deployment and people* (countries, users, status, affected persons, vulnerable groups, switches for
  `interacts_with_persons`, `generates_synthetic_content`, `emotion_recognition`, `biometric`, and a safety
  component of an Annex I product with its law), *Documents* (dropzone; `.md/.txt/.yaml/.json` are marked
  *Read*, others *Stored, not read*), *Review* (each section with *Edit*). *Auto fill* fills the demo's
  Candidate Shortlister (parse, score, shortlist; profiling, so high risk under Annex III 4(a)) and its `system-specification.md`. **Create** = `POST /v1/systems {id, name, status: "draft",
  data: {card}}` → `PUT .../files/system-card.yaml` (`risk_class: unclassified`, `provenance: declared_by_pm`)
  → one `PUT .../files/docs/<name>` per document, in that order (a retry after a failed upload does not
  re-create the system). The success screen links to *Open and classify* (Overview) and *Hand over to the AI
  engineer: build the pipeline* (the Plugins tab's "No pipeline yet" state). Pure helpers in
  `onboarding/lib/wizard.ts` (tested).
- **Risk classification** (`features/classification`): a *Risk classification* card at the top of the
  Overview (`ClassificationPanel`): none → *Classify risk*; running → three-step progress (pre-checks,
  classifier, verify + Iris; estimated from the clock) with elapsed time, polling every 2 s; proposed → the
  summary (class, route, legal basis, role, classifier confidence, Iris agrees / disagrees with p, its
  probabilities in a tooltip), a *Needs a careful human review* banner with the reasons and verifier
  problems, the reasoning, Art. 6(3) assessment, Annex III areas considered, Art. 5 screening, transparency
  and GPAI, counter-arguments and what would change the answer, open questions (who to ask), next steps, key
  dates and citations (*Non-binding guidance* / *Draft* badges), with **Approve** (shows the card keys it
  writes; optional note) and **Reject** (reason required, ≤ 2,000 chars; the next run reads it); approved /
  stale / rejected → the summary with *Re-classify* (`previousId` = the stale or rejected run) and the full
  proposal on demand; failed → *Retry*. **Oumi Iris per claim** (`result.iris_claims` / `iris_summary`,
  missing on older runs → hidden; helpers `irisFor`, `groupClaims`, `collapseGroups`, `irisSummaryOf` in
  `lib/iris.ts`, tested): an `IrisChip` (*Iris ✓ 93%* success / *Iris ✗ 12%* warning, danger on a strong
  disagreement / *Iris —* not run; the percent is Iris's support for the agent's answer, the tooltip shows the
  exact statement and "Agent: yes · Iris P(yes) = 0.93", the aria-label spells the verdict out) next to each
  Annex III and Art. 5 row (by `provision_id`), the Art. 6(3) condition and profiling, each Art. 50 provision,
  the AI Act role and each counter-argument (`counter:<n>`); the *Independent check (Iris)* cell adds "N of M
  claims agree" with *See the checks* (expands the proposal and scrolls to the section); the section
  *Independent checks (Oumi Iris)* lists strong disagreements first (danger accent), then the claims grouped
  (Annex III, Art. 5, Art. 6(3), Art. 50, Role, Annex I, Assumptions, Counter-arguments; disagreements first),
  each with the agent's Yes/No, Iris's P(yes) bar and the chip; over six agreeing claims it collapses to the
  disagreements + six, *Show all N*. *History* opens a sheet with every run and its append-only events.
  The header shows a *proposed* / *stale* dot next to the risk badge (`ClassificationDot`). The Obligations
  tab, when no audit has an obligation map yet, previews `GET /v1/systems/{id}/obligations`: from the approved
  (or stale) classification, else from the card's declared class (seeded systems); an unclassified card keeps
  the "No obligation map yet" state (`ObligationsPreview`). Rows are read in camelCase (`ClassificationOut`) or snake_case;
  the `result` is the agents' snake_case `ClassificationResult` (`lib/types.ts`). Mocks
  (`mocks/handlers/classifications.ts`, `onboarding.ts`): SYS-001 approved then stale (RC-2026.11.15-1 on
  AIA.6.3), SYS-002 a `needs_human` proposal (13 Iris claims, one strong disagreement), SYS-003 unclassified, a registered CV Parser gets the
  Art. 6(3)(a) proposal after ~9 s (high risk 4(a) after a rejection).

API used: `POST /v1/systems`, `GET|POST /v1/systems/{id}/classifications`, `POST .../classifications/{cid}/decision`,
`GET /v1/systems/{id}/obligations`.

### Plugins tab

A plugin is the wrapper around one model of the system ([agent context § 3](../architecture/agent-context.md#3-plugins-how-to-reach-a-model-what-it-is-what-it-should-do)).
Backend API: [backend § Plugins](backend-systems.md#plugins). Mock mode mirrors every route, including adding
and removing graph steps.

- **The engineer builds the graph here.** The PM registers a system with its documents only, so a new system
  has no pipeline: the *System graph* section shows a "No pipeline yet" empty state. **Add a model** opens the
  plugin form for a model that is not in the graph yet; **Add a step** adds a box that is not a model (an
  upstream system or a human review, `POST .../plugins/components`). Both connect the box with **Comes after** /
  **Goes to** pickers over the existing boxes (`upstream` / `downstream`; saving a plugin sends them on
  `PUT .../plugins/{name}`, and its placement is recomputed). A box is removed from its panel (**Remove**,
  `DELETE .../plugins/components/{id}`); its edges go with it, its plugin files stay.
- **Graph:** the system graph from `architecture.yaml` (`GET /v1/systems/{id}/plugins`): components and edges,
  e.g. SYS-001 CV parser → CV ranker → recruiter review. The API marks each node `configured` and `testable`;
  clicking a model opens its plugin form, clicking another step opens the step dialog.
- **Form:** clicking a model node opens the plugin form (`GET .../plugins/defaults?component=`). Every field shows
  its **default in grey**, from the graph and the local MLflow registry (model version, task from the
  description, input fields and output type / label / score fields from the signature, the gateway REST path,
  `env://MODEL_GATEWAY_TOKEN`, rps 5, timeout 10 s, 500 requests). The engineer overrides only what differs; an
  empty field saves the default (`PUT .../plugins/{name}`). A model that is not in the graph can be added as a
  standalone plugin; saving links it into `architecture.yaml`.
- **Folder tab hides `plugins/`:** the card is still `plugins/<name>/plugin.yaml` (the agents read it), but it is
  edited here, not as raw YAML.
- **Start audit** gets a plugin picker: an audit tests one plugin and sends it as `data.target_plugin`; without
  a pick the pipeline tests the decision model.

## Audit findings, report, pins and retry (`src/features/audits`)

- **View tabs** on the audit page: *Pipeline* (the graph canvas), *Findings*, *Report* (`?view=`).
- **Pins** (`AuditPins`): kb, dossier, config, model version and seeds from `audit.pins` (backend column,
  copied from `data.pins`), falling back to `data.kbVersion` / card version.
- **Findings** (`FindingsPanel`, `findings_parts/SealedFindingCard`): `GET /v1/audits/{id}/findings`; falls
  back to the audit's `finding` artifacts (shown as *Not sealed*) when the table is empty. Per finding: verdict
  (plan 01 vocabulary), severity, gap id, *Sealed* badge with hash, *Stale* / *Superseded*, article + obligation id,
  reasoning, the three judges side by side (rule, Gemini, Iris; *Disagree · needs a human*), critic note,
  counter-arguments, would-change-if, metrics, evidence (path, sha256, MLflow run link via `VITE_MLFLOW_URL`,
  default `http://localhost:5500`), citations at their kb_version and the annotation thread
  (`AnnotationThread`: contest / accept risk / remediation planned / comment). No edit controls. A focused re-run
  shows its `delta_report` artifact on top (`DeltaReportCard`: old → new verdict per obligation, metric deltas,
  reason).
- **Report** (`ReportPanel`, model in `lib/report.ts`): incomplete-audit report (the pipeline's, or derived from a
  failed audit's stage and error), management summary with traffic lights (derived from the findings when the
  pipeline wrote none), engineer report, bias & fairness, Annex IV draft, gap list and evidence register (the
  report's own, else derived from the sealed findings). **Export PDF** (`lib/print.ts`) opens the report in a print
  window with the app CSS inlined (light theme) and calls the browser's print, so "Save as PDF" makes the file.
- **Retry**: a `failed` audit shows *Retry* (`POST /v1/audits/{id}/retry`); the pipeline re-runs the failed step.

## Regulation extras (`src/features/regulation`)

**Simulate change** (`SimulateChangeDialog`, demo): find / replace on reg-memory's mirrored Art. 6 guideline page
(`PUT /v1/regulation/demo/mirror` with `check: true`), so a real RegChange lands in the inbox. Change cards show the
judge's `running` (polls every 3 s) and `failed` states, per affected system the obligations touched, the findings
marked stale, the judge's counter-argument and links to the re-run audit and its delta report.

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

### Scenarios gate: partial approval

The approval drawer of the `scenarios` gate is a checklist (`features/approvals/components/ScenarioChecklist.tsx`). Rows the decision model flagged `not_relevant` start unchecked; unchecking a row asks for an optional reason. Approving sends `edits: {approved_scenarios: [ids], excluded: {id: reason}}` (`scenarioEdits` in `approvals/lib/approvals.ts`; `{}` when every scenario is checked). Only the checked scenarios go on; the scenarios artifact then shows the excluded ones with their reasons. Zero checked disables Approve (use Request changes).
