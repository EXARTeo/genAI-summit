# Frontend chat (port of magenticx `agentic_ui`)

`/chat` and `/chat/:conversationId` in `mnamon/frontend/` are a port of the chat in
[magenticx](https://github.com/konstantinosmpouros/magenticx) `magenticx/agentic_ui/src/` (`features/chat`,
`features/inference`, `features/attachments`, `app/useChatWorkspace`, `pages/ChatView`), talking to our
backend (ported from magenticx's `dialogue_bridge`). Same behaviour and UX, restyled to our design system
(`@/shared/ui`, neutral + teal, amber only for "needs a human", our motion rules).

## What is where

```text
src/pages/ChatView.tsx                   route view: <SidebarExtra><ChatSidebar/></SidebarExtra> + <ChatWorkspace HeaderSlot={TopbarExtra}/>
src/features/chat/
├── lib/
│   ├── types.ts          backend DTOs (conversations, messages, attachments, runs, frames, search, tasks)
│   ├── timeline.ts       AG-UI event log → run timeline (magenticx features/inference/timeline.ts, condensed)
│   ├── hitl.ts           HITL interrupt + ask_user parsing (magenticx features/inference/hitl.ts)
│   ├── runState.ts       frame → live run fold (magenticx features/inference/runState.ts)
│   ├── branches.ts       edit/retry branches: visible path, siblings, selection
│   ├── attachments.ts    upload guards (25 MB / file and message, 10 files), base64 read (kinds: shared lib/files.ts)
│   ├── slashCommands.ts  /new /rename /pin /archive /retry /stop /agent /search
│   ├── sidebarList.ts    conversation list logic: pinned order, paged Chats, search grouping, titles
│   ├── sidebarMotion.ts  list row / section motion (magenticx sidebarMotion.ts, tweens, no springs)
│   ├── cotTitle.ts, toolPresentation.ts   CoT block titles and per-tool step titles/icons (magenticx ports)
│   ├── streamScroll.ts   stick-to-bottom state while streaming (magenticx streamScroll.ts)
│   ├── tableExport.ts, codeExport.ts, download.ts, messageFormat.ts   copy/download helpers, clock/usage format
│   ├── transport.ts      run WebSocket with subscribe/since replay + reconnect (mock bus in mock mode)
│   ├── routes.ts         UI + API paths
│   ├── mockRuns.ts       mock mode: conversation store + scripted AG-UI runs
│   └── mockRoutes.ts     mock REST routes (registered by shared/lib/mocks/handlers/chat.ts)
├── handlers/chat.ts      api.* calls
├── hooks/
│   ├── runStore.ts       live runs app-wide (zustand), socket lifecycle, cache patching on terminal frames
│   ├── useChat.ts        the controller: visible branch, active run, send/edit/retry/stop/decide/answer/rate
│   ├── useComposer.ts    draft + attachments with read progress (a failed read stays as a red chip)
│   ├── useAttachmentActions.tsx   a sent file's bytes, Download, "Save to <system> folder" for the shared chip / preview
│   ├── useSidebarUi.ts   section fold state (localStorage) + the chat search panel's open state (zustand)
│   └── useConversations.ts, keys.ts   react-query (paged Chats, pinned, archived, detail, search, agents, subject)
└── components/
    ├── ChatWorkspace.tsx   page: header, body, composer slot (or takeover), empty-chat greeting, drop zone, shortcuts, preview
    ├── ChatHeader.tsx, AgentPicker.tsx   header row in the top bar: agent picker (search + list), title, subject link, ⋯ actions
    ├── ChatSidebar.tsx     New chat + Search chats rows, folding Pinned / Chats sections (Chats paged on scroll),
    │                       Archived footer row; rows: title only, active highlight + accent bar, spinner while working
    ├── sidebar_parts/      ConversationRow (⋯: Rename inline, Pin, Archive, Delete), SidebarSection, ChatSearchPanel
    │                       (cmdk dialog, Ctrl/⌘+Shift+S), ArchivedChatsDialog, NewChatIcon
    ├── ChatBody.tsx, ChatMessage.tsx   message list (stick-to-bottom), user bubble (+ inline edit), agent answer
    ├── ChatComposer.tsx    "Message {agent}…" card: textarea, "+" files (button / paste / drop), slash menu, subject chip, one round Send / Stop / Queue button
    ├── HitlTakeover.tsx, AskUserTakeover.tsx   approvals (batched deck) and the agent's questions
    ├── AttachmentPreview.tsx   the shared FilePreviewPanel fed with a sent or composer file (+ Save to <system> folder)
    ├── ChatAboutButton.tsx     "Chat about this system / audit" entry point
    └── message_parts/   ChatMarkdown (GFM + highlight.js, code header with copy/download), MarkdownTable (copy,
                         CSV/Markdown download), ThinkingBlock + CoTStep (CoT), ToolCallView (+ sources), SubagentCard,
                         RunBlocks (artifact, task rows, plan), MessageAttachments (shared FileChip + ImageGrid), ActionBars, BranchControls,
                         MessageUsage (usage gauge + tooltip)
```

The conversation list is rendered into the shell rail through `SidebarExtra` (`src/app/sidebarSlot.tsx`), from the
page (`pages/ChatView.tsx`) so `features/` never imports `app/`. Below `lg` it appears in the mobile drawer. The same
way, the chat header goes into the top bar through `TopbarExtra` (`src/app/topbarSlot.tsx`; the page hands it to
`ChatWorkspace` as `HeaderSlot`), so the chat shows one borderless header row like magenticx: the agent's name + chevron
(the picker) on the left, the conversation title and the subject link, then ⋯ (pin, archive, delete); the theme toggle stays.

Like magenticx: a new chat is the logo, a rotating greeting, the agent's description and the composer centred, with the
suggestions as pills below; the approval takeover is compact (shield, "Approval required", what the tool does, a chevron
for the arguments; one row with an optional reason, Reject, Approve in amber); the questions takeover asks one question
at a time (numbered tiles, keys 1–6, write your own, Skip — let the agent decide, Next / Send answers). Not ported: the
travelling glow border of the composer (no glows here), the draft command highlight, recent agents in the picker.

## Files and images

Ported from magenticx's attachment UX onto the shared pieces in `@/shared/ui` (see [frontend.md](frontend.md#design-system-srcsharedui)):

| magenticx | Here |
| --- | --- |
| Composer strip (`ChatInputBar`): 56 px image thumbnails, file chips with a tile and name, round red remove, fading edges, images first | Same, on `FileChip variant="composer"`; adds type · size, read progress and a failed state; an image opens the lightbox, a file the preview |
| `MessageAttachments`: 40 px accent tile + name + MIME, Eye / Download on hover; images in a two-column grid, odd last spans both | Same (`FileChip variant="message"`, `ImageGrid`); the subtitle is type · size; a ⋯ menu adds "Save to <system> folder"; on touch screens the ⋯ menu holds every action |
| `ImageLightbox`: full screen, download + close, Esc / backdrop, panel motion | Same plus zoom (buttons, wheel, double-click, + − 0), drag to pan and ←/→ through the message's images; Radix focus trap and return |
| `ArtifactCard`: a presented image shows as the image; other files as a "Generated document" card that previews or downloads | Same, opening the shared preview / lightbox |
| `AttachmentPreviewPanel`: big centred panel, name + type · MIME · size, Download, PDF / Office viewer / Markdown / JSON / CSV / code / text | Same layout on our tokens (full screen on a phone); DOCX converted in the browser (no Office Online viewer, no public token), Excel / PowerPoint download only, images preview in the panel too |

Escape in the lightbox or the preview closes only that layer (it no longer also stops a running answer).

## Mapping to our API

| UI | Backend |
| --- | --- |
| Sidebar lists | `GET /v1/conversations`, `/pinned`, `/archived` (`?page=1&size=`) |
| Open a chat | `GET /v1/conversations/{id}` (all branches, images inline) |
| Rename / pin / archive / delete | `PATCH .../{id}/title`, `/pin`, `/unpin`, `/archive`, `/unarchive`, `DELETE .../{id}` |
| Send (new chat) | `POST /v1/inference/runs/start` `mode: new` with `agentSlug`, `systemId`, `auditId`, `message` (attachments as base64) |
| Send / edit / retry | `mode: send` (`parentMessageId`, `queue_if_busy` while a run is active → 202 queued), `edit` (`targetMessageId`), `retry` (`targetMessageId`, `messagePath`) |
| Streaming | `WS /v1/inference/runs/{id}/ws?client_id=` → `subscribe {since}` → `snapshot`, `event {seq, payload: events}`, `terminal` |
| Stop | `POST /v1/inference/runs/{id}/cancel` (also Esc, `/stop`) |
| Approve / reject, answer questions | `POST /v1/inference/runs/{id}/resume` `{interruptId, decision, reason, decisions[], value: {answers}}` |
| Thumbs | `POST /v1/messages/{conv}/{msg}/like` / `dislike` |
| Search | `GET /v1/search?q=&limit=20` (titles, messages, file names) |
| Preview / download | `GET /v1/attachments/preview|download/{conv}/{msg}/{blob}` (fetched as a blob so `X-Client-Id` goes along) |
| Save to system folder | `POST /v1/systems/{id}/files/from-attachment` `{attachmentId}` (attachment menu and preview footer, in a chat about a system) |
| Subject chip | `GET /v1/systems/{id}` (name), `GET /v1/audits/{id}` (system of an audit) |
| Agent picker | `GET /v1/agents` (not served yet: falls back to `assistant` / Copilot) |

AG-UI events folded: `THINKING_*`, `TOOL_CALL_*`, `TEXT_MESSAGE_*`, `CUSTOM` `HITL_INTERRUPT` (tool approvals and
`ask_user`), `BRIDGE_HITL_RESOLVED`, `TASK_SUBAGENT`, `SUBAGENT_EVENT` (keyed by namespace across a HITL resume),
`SUBAGENT_COMPLETED`, `PRESENT_ARTIFACT` (card linked to the generated attachment by filename), `SOURCES`,
`PLAN_SNAPSHOT`, `TOKEN_USAGE`, `TASK_LAUNCHED`, `TASK_SETTLED_INLINE`. An approved tool re-run under a new call id
folds back into its stalled step; events are deduped by `seq`.

## Entry points

`ChatAboutButton` on the system detail header ("Chat about this system" → `/chat?system=SYS-001`) and the audit
run header ("Chat about this audit" → `/chat?system=…&audit=…`). The composer shows **Discussing: CV Screener**
(removable before the first message); the conversation keeps `systemId` / `auditId`, its header links to the
system, and its attachments can be saved to the system folder.

## Mock mode

`npm run dev:mocks` serves three finished chats (one with a PDF, a CSV and an image), and `conv-hitl`, a run paused
on an approval. A new message streams a scripted run: thinking, `search_regulation` with sources, an
`evidence-checker` sub-agent with its own tool, a gated `write_finding_note` that waits for **Approve / Reject**,
then the streamed answer with a code block and an artifact card. A message containing "clarify" makes the agent
ask questions instead (`ask_user`). Shots: `chat`, `chat-about-system`, `chat-conversation`, `chat-attachments`,
`chat-preview`, `chat-hitl`.

## Kept, changed, dropped

- **Kept**: conversation list with pinned/recent/archived and row actions, search, new chat, streaming with a caret,
  CoT blocks (live open with a shimmering latest-step title, folded to that title + "· 7s", `lib/cotTitle.ts` and `lib/toolPresentation.ts`; a Done / Stopped / Failed footer), tool steps with args/result/duration, sub-agent
  cards, background-task rows, plan checklist, artifact cards, source chips, HITL takeover (batched deck,
  reject reason) and ask-user takeover, attachments (button, paste, drag-drop, read progress, chips with preview,
  tiles + image thumbnails in messages, download), previews (image, PDF, DOCX, Markdown, CSV, JSON/code, text),
  edit (new branch) / retry / branch switcher, stop, queued message while busy, thumbs, copy, usage line,
  markdown with highlighted code + copy, slash commands, shortcuts (Esc stop, Ctrl/⌘+Shift+O new chat,
  Ctrl/⌘+Shift+S search, Alt+L focus the composer, Alt+A attach, Alt+G agent picker), agent picker in the header.
- **Condensed**: the timeline reducer (magenticx's 2,000-line fold → ~600 lines; no charts, compaction, nested
  delegation rows or planTiming); one live run store instead of `useInferenceRuns` + `useBackgroundTasks`.
- **Dropped** (no backend or out of scope): login/accounts, sharing, voice, automations/workflows, agent builder,
  incognito, effort/model pickers, the agent map, context-compaction control and gauge, charts (`RENDER_CHART`),
  inline citation pills (sources show as chips on the search step instead), conversation rail/markers, favicons
  (initial letter instead), the conversation-channel socket (task frames, queue state) and the task drill-down
  socket.

## Backend gaps found

- `POST /v1/inference/runs/start` `mode: new` did not accept `systemId` / `auditId` (only `POST /v1/conversations`
  did): **fixed** (`schema/inference.py`, `utils/inference_start.py`, 404 on an unknown system).
- No `GET /v1/agents` proxy to the agents service catalog (`GET /agents` is internal-only): the UI falls back to a
  single `assistant` agent. Add a thin proxy to get the picker live.
- Edit-and-approve (changing a gated tool's arguments) is not in the resume contract (`approve | reject` only), so
  the takeover offers approve / reject with a reason, like magenticx.
