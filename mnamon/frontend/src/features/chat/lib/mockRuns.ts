/**
 * Mock mode: an in-browser stand-in for the backend's conversations + run manager, so the chat is
 * demoable without the stack. A new message streams a scripted AG-UI run: thinking, a search tool
 * with sources, a sub-agent with its own tool, a gated write that pauses on a HITL approval,
 * then the streamed answer and an artifact. A message containing "clarify" makes the agent ask
 * questions (`ask_user`) instead. Frames match `WS /v1/inference/runs/{id}/ws`.
 */
import type {
  AttachmentIn,
  AttachmentOut,
  ConversationDetail,
  ConversationSummary,
  InferenceRunOut,
  InferenceStartPayload,
  InferenceStartResponse,
  MessageOut,
  RawEvent,
  ResumePayload,
  RunFrame,
} from './types';

type Listener = (frame: RunFrame) => void;

interface MockRun {
  run: InferenceRunOut;
  events: RawEvent[];
  script: RawEvent[][];
  cursor: number;
  timer?: ReturnType<typeof setTimeout>;
  paused: boolean;
  listeners: Set<Listener>;
  /** Step to continue with after the approval (`afterApprove` / `afterReject`). */
  resumeWith?: { approve: RawEvent[][]; reject: RawEvent[][] };
  interruptId?: string;
}

const conversations = new Map<string, ConversationDetail>();
const runs = new Map<string, MockRun>();
export const blobs = new Map<string, { mime: string; b64: string; name: string }>();
let counter = 100;
const uid = (p: string) => `${p}-${(counter++).toString(36)}`;
const now = () => new Date().toISOString();
const isTest = () => import.meta.env.MODE === 'test';

// ---------------------------------------------------------------------------
// Seed data
// ---------------------------------------------------------------------------
const b64 = (text: string) => btoa(unescape(encodeURIComponent(text)));

const PDF_TEXT = `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 420 300]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 120>>stream
BT /F1 16 Tf 30 250 Td (CV Screener - model card) Tj 0 -28 Td /F1 11 Tf (Selection rate by gender: 0.71 vs 0.86) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>
%%EOF`;

const CSV_TEXT = `group,applicants,shortlisted,selection_rate
female,412,293,0.71
male,388,334,0.86
`;

// A small bar chart of the selection rates (a screenshot stand-in; content, not UI colours).
const CHART_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="160" viewBox="0 0 240 160">
<rect width="240" height="160" fill="#fafafa"/>
<text x="16" y="24" font-family="sans-serif" font-size="12" fill="#3f3f46">Selection rate</text>
<rect x="40" y="62" width="60" height="78" rx="3" fill="#0f766e"/>
<rect x="140" y="46" width="60" height="94" rx="3" fill="#a1a1aa"/>
<text x="58" y="56" font-family="sans-serif" font-size="11" fill="#18181b">0.71</text>
<text x="158" y="40" font-family="sans-serif" font-size="11" fill="#18181b">0.86</text>
<text x="52" y="154" font-family="sans-serif" font-size="10" fill="#71717a">female</text>
<text x="158" y="154" font-family="sans-serif" font-size="10" fill="#71717a">male</text>
</svg>`;

function seedAttachment(
  name: string,
  mime: string,
  data: string,
  origin = 'upload',
  extra: Partial<AttachmentOut> = {},
): AttachmentOut {
  const blobId = uid('blob');
  blobs.set(blobId, { mime, b64: data, name });
  return {
    id: uid('att'),
    name,
    mime,
    size: Math.round((data.length * 3) / 4),
    timestamp: now(),
    origin,
    blobId,
    data: mime.startsWith('image/') ? data : null,
    ...extra,
  };
}

function summaryOf(c: ConversationDetail): ConversationSummary {
  const { messages: _m, activeTaskMessageId: _a, ...summary } = c;
  return { ...summary, isStreaming: Boolean(c.activeRunId) };
}

function message(partial: Partial<MessageOut> & Pick<MessageOut, 'id' | 'sender'>): MessageOut {
  const t = now();
  return {
    parentMessageId: null,
    content: '',
    attachments: [],
    rawEvents: [],
    created_at: t,
    updated_at: t,
    ...partial,
  };
}

function minutesAgo(n: number) {
  return new Date(Date.now() - n * 60_000).toISOString();
}

// ---------------------------------------------------------------------------
// The scripted run
// ---------------------------------------------------------------------------
const ev = (type: string, extra: Record<string, unknown> = {}): RawEvent => ({ type, ...extra });
const custom = (name: string, value: unknown): RawEvent => ({ type: 'CUSTOM', name, value });
const sub = (taskId: string, inner: RawEvent): RawEvent =>
  custom('SUBAGENT_EVENT', { task_id: taskId, namespace: [`evidence-checker:${taskId}`], event: inner });

function chunks(text: string, size = 18): string[] {
  const words = text.split(/(\s+)/);
  const out: string[] = [];
  let buf = '';
  for (const w of words) {
    buf += w;
    if (buf.length >= size) {
      out.push(buf);
      buf = '';
    }
  }
  if (buf) out.push(buf);
  return out;
}

const ANSWER = `**F-001 is a gap** because the CV Screener's shortlisting rate for women (0.71) is well below the rate for men (0.86): the ratio is **0.83**, under the organisation's 0.90 threshold for *equal opportunity*.

What the evidence says:

1. The model card declares a fairness check, but only on overall accuracy, not per group.
2. The dataset sheet shows the training data is 61 % male applicants (Art. 10(2)(f) asks for an examination of possible biases).
3. The reviewer's lesson from the last audit already flagged the same pattern.

| Group | Shortlisted | Applicants | Selection rate |
| --- | ---: | ---: | ---: |
| Women | 142 | 200 | 0.71 |
| Men | 172 | 200 | 0.86 |

\`\`\`python
ratio = 0.71 / 0.86  # selection rate, female / male
assert ratio >= 0.90, f"disparate impact {ratio:.2f}"
\`\`\`

I wrote a finding note to the system folder and attached a short evidence summary below.`;

const NOTE_ARGS =
  '{"system": "SYS-001", "path": "findings/F-001-note.md", "summary": "Selection-rate ratio 0.83 < 0.90 (equal opportunity)"}';

function answerScript(opts: { toolCallId: string; taskId: string; interruptId: string; text: string }) {
  const { toolCallId, taskId, interruptId } = opts;
  const searchId = uid('call');
  const readId = uid('call');
  const execId = uid('call');
  const grepId = uid('call');
  const before: RawEvent[][] = [
    [ev('RUN_STARTED')],
    [
      ev('THINKING_START'),
      ev('THINKING_TEXT_MESSAGE_CONTENT', {
        delta: '**Checking F-001 against Art. 10**\n\nThe user asks why F-001 was raised. ',
      }),
    ],
    [
      ev('THINKING_TEXT_MESSAGE_CONTENT', {
        delta: 'I should check the finding against Art. 10 and the system evidence.',
      }),
    ],
    [ev('TOOL_CALL_START', { toolCallId: searchId, toolCallName: 'search_regulation' })],
    [
      ev('TOOL_CALL_ARGS', {
        toolCallId: searchId,
        delta: '{"query": "Art. 10 data governance bias examination"}',
      }),
      ev('TOOL_CALL_END', { toolCallId: searchId }),
    ],
    [
      ev('TOOL_CALL_RESULT', {
        toolCallId: searchId,
        content:
          'Art. 10(2)(f): examination in view of possible biases that are likely to affect health and safety or lead to discrimination…',
      }),
      custom('SOURCES', {
        tool_call_id: searchId,
        sources: [
          {
            id: 'src-1',
            url: 'https://artificialintelligenceact.eu/article/10/',
            title: 'Article 10: Data and Data Governance',
          },
          {
            id: 'src-2',
            url: 'https://eur-lex.europa.eu/eli/reg/2024/1689/oj',
            title: 'Regulation (EU) 2024/1689',
          },
        ],
      }),
    ],
    [
      ev('THINKING_TEXT_MESSAGE_CONTENT', {
        delta:
          '**Recomputing the ratio**\n\nThe finding quotes 0.71 and 0.86; recompute the ratio before I rely on it.',
      }),
    ],
    [
      ev('TOOL_CALL_START', { toolCallId: execId, toolCallName: 'execute' }),
      ev('TOOL_CALL_ARGS', {
        toolCallId: execId,
        delta: '{"command": "python -c \\"print(round(0.71 / 0.86, 2))\\""}',
      }),
      ev('TOOL_CALL_END', { toolCallId: execId }),
    ],
    [ev('TOOL_CALL_RESULT', { toolCallId: execId, content: '0.83\n[Command succeeded with exit code 0]' })],
    [
      ev('THINKING_TEXT_MESSAGE_CONTENT', {
        delta:
          '**Handing the dossier check to the evidence checker**\n\nThe ratio holds. The evidence checker should confirm the per-group rates in the dossier.',
      }),
    ],
    [
      ev('THINKING_END'),
      custom('TASK_SUBAGENT', {
        task_id: taskId,
        subagent_type: 'evidence-checker',
        description:
          'Check the CV Screener dossier for per-group selection rates: read the model card and data/selection_rates.csv, recompute the female / male ratio and say whether it is under the organisation threshold of 0.90. Quote the file and line for every number you report.',
      }),
    ],
    [
      sub(taskId, ev('THINKING_START')),
      sub(
        taskId,
        ev('THINKING_TEXT_MESSAGE_CONTENT', { delta: 'Looking for per-group metrics in the dossier.' }),
      ),
    ],
    [
      sub(taskId, ev('TOOL_CALL_START', { toolCallId: grepId, toolCallName: 'grep' })),
      sub(
        taskId,
        ev('TOOL_CALL_ARGS', {
          toolCallId: grepId,
          delta: '{"pattern": "selection_rate", "path": "/systems/SYS-001/"}',
        }),
      ),
      sub(taskId, ev('TOOL_CALL_END', { toolCallId: grepId })),
    ],
    [
      sub(
        taskId,
        ev('TOOL_CALL_RESULT', {
          toolCallId: grepId,
          content: '/systems/SYS-001/data/selection_rates.csv\n/systems/SYS-001/model-card.md',
        }),
      ),
    ],
    [
      sub(taskId, ev('TOOL_CALL_START', { toolCallId: readId, toolCallName: 'read_system_file' })),
      sub(
        taskId,
        ev('TOOL_CALL_ARGS', { toolCallId: readId, delta: '{"path": "data/selection_rates.csv"}' }),
      ),
    ],
    [
      sub(taskId, ev('TOOL_CALL_END', { toolCallId: readId })),
      sub(taskId, ev('TOOL_CALL_RESULT', { toolCallId: readId, content: CSV_TEXT })),
    ],
    [
      sub(taskId, ev('THINKING_END')),
      sub(taskId, ev('TEXT_MESSAGE_START')),
      sub(
        taskId,
        ev('TEXT_MESSAGE_CONTENT', {
          delta:
            'Selection rate **female 0.71**, **male 0.86** (data/selection_rates.csv, lines 2–3) → ratio **0.83**, below the 0.90 threshold. The model card reports accuracy only overall, not per group.',
        }),
      ),
    ],
    [
      sub(taskId, ev('TEXT_MESSAGE_END')),
      custom('SUBAGENT_COMPLETED', { task_id: taskId, status: 'success' }),
    ],
    [
      ev('THINKING_START'),
      ev('THINKING_TEXT_MESSAGE_CONTENT', {
        delta:
          '**Recording the finding note**\n\nI will record the finding note in the system folder. That writes, so it needs approval.',
      }),
    ],
    [ev('TOOL_CALL_START', { toolCallId, toolCallName: 'write_finding_note' })],
    [
      ev('TOOL_CALL_ARGS', {
        toolCallId,
        delta: NOTE_ARGS,
      }),
      ev('TOOL_CALL_END', { toolCallId }),
    ],
    [
      custom('HITL_INTERRUPT', {
        thread_id: 'thread-mock',
        interrupt: {
          id: interruptId,
          value: {
            action_requests: [
              {
                action: 'write_finding_note',
                args: {
                  system: 'SYS-001',
                  path: 'findings/F-001-note.md',
                  summary: 'Selection-rate ratio 0.83 < 0.90 (equal opportunity)',
                },
                description: 'Write a finding note into the CV Screener folder (creates a new file version).',
              },
            ],
          },
        },
      }),
    ],
  ];
  const rerunId = `${toolCallId}-rerun`;
  const tail = (approved: boolean): RawEvent[][] => [
    [
      custom('BRIDGE_HITL_RESOLVED', {
        interrupt_id: interruptId,
        decision: approved ? 'approve' : 'reject',
      }),
    ],
    ...(approved
      ? [
          [
            ev('TOOL_CALL_START', { toolCallId: rerunId, toolCallName: 'write_finding_note' }),
            ev('TOOL_CALL_ARGS', { toolCallId: rerunId, delta: NOTE_ARGS }),
            ev('TOOL_CALL_END', { toolCallId: rerunId }),
          ],
          [
            ev('TOOL_CALL_RESULT', {
              toolCallId: rerunId,
              content: 'Wrote findings/F-001-note.md (version 1).',
            }),
          ],
        ]
      : []),
    [ev('THINKING_END'), ev('TEXT_MESSAGE_START')],
    ...chunks(
      approved
        ? ANSWER
        : ANSWER.replace(
            'I wrote a finding note to the system folder and attached',
            'You declined the note, so nothing was written. I attached',
          ),
    ).map((delta) => [ev('TEXT_MESSAGE_CONTENT', { delta })]),
    [
      ev('TEXT_MESSAGE_END'),
      custom('PRESENT_ARTIFACT', {
        artifact_id: 'art-1',
        path: 'outputs/F-001-evidence.md',
        filename: 'F-001-evidence.md',
        title: 'F-001 evidence summary',
        summary: 'Per-group selection rates, the threshold and the Art. 10 reference.',
        mime: 'text/markdown',
      }),
      custom('TOKEN_USAGE', {
        input_tokens: 4210,
        output_tokens: 612,
        model: 'gemini-2.5-pro',
        context_tokens: 5100,
        context_window: 1_000_000,
      }),
    ],
    [ev('RUN_FINISHED')],
  ];
  return { before, tail };
}

function askScript(interruptId: string) {
  return {
    before: [
      [ev('RUN_STARTED')],
      [
        ev('THINKING_START'),
        ev('THINKING_TEXT_MESSAGE_CONTENT', {
          delta: 'The request is ambiguous; I should ask before I start.',
        }),
      ],
      [
        custom('HITL_INTERRUPT', {
          thread_id: 'thread-mock',
          interrupt: {
            id: interruptId,
            value: {
              type: 'ask_user',
              questions: [
                {
                  id: 'scope',
                  question: 'Which system should I look at?',
                  options: ['CV Screener', 'Loan Scorer', 'Both'],
                },
                {
                  id: 'depth',
                  question: 'How deep should the review go?',
                  options: ['Quick check', 'Full audit'],
                  multiple: false,
                },
              ],
            },
          },
        }),
      ],
    ],
    tail: (approved: boolean, answers?: unknown) => [
      [
        custom('BRIDGE_HITL_RESOLVED', {
          interrupt_id: interruptId,
          decision: approved ? 'approve' : 'reject',
          answers,
        }),
      ],
      [ev('THINKING_END'), ev('TEXT_MESSAGE_START')],
      ...chunks(
        'Thanks, that narrows it down. I will start with a quick check of the CV Screener and report back with the gaps I find.',
      ).map((delta) => [ev('TEXT_MESSAGE_CONTENT', { delta })]),
      [ev('TEXT_MESSAGE_END'), ev('RUN_FINISHED')],
    ],
  };
}

// ---------------------------------------------------------------------------
// Run engine
// ---------------------------------------------------------------------------
function emit(r: MockRun, frame: RunFrame) {
  r.listeners.forEach((l) => l(frame));
}

function snapshotPayload(r: MockRun, type: 'snapshot' | 'terminal') {
  const conv = conversations.get(r.run.conversationId);
  const msg = conv?.messages.find((m) => m.id === r.run.id) ?? null;
  return {
    type,
    run: { ...r.run, rawEvents: r.events },
    message: msg,
    summary: conv ? summaryOf(conv) : null,
  };
}

function finish(r: MockRun, status: 'completed' | 'cancelled' | 'failed') {
  clearTimeout(r.timer);
  r.run = { ...r.run, status, completedAt: now(), updatedAt: now(), pendingInterrupts: 0 };
  const conv = conversations.get(r.run.conversationId);
  if (conv) {
    const text = r.events
      .filter((e) => e.type === 'TEXT_MESSAGE_CONTENT')
      .map((e) => String(e.delta ?? ''))
      .join('');
    conv.messages = conv.messages.map((m) =>
      m.id === r.run.id
        ? {
            ...m,
            content: text,
            rawEvents: r.events,
            streamingStatus: status,
            updated_at: now(),
            attachments: r.events.some((e) => e.name === 'PRESENT_ARTIFACT')
              ? [
                  seedAttachment(
                    'F-001-evidence.md',
                    'text/markdown',
                    b64(
                      '# F-001 evidence\n\n| group | rate |\n| --- | --- |\n| female | 0.71 |\n| male | 0.86 |\n\nRatio 0.83 < 0.90 (Art. 10(2)(f)).\n',
                    ),
                    'generated',
                    {
                      title: 'F-001 evidence summary',
                    },
                  ),
                ]
              : m.attachments,
          }
        : m,
    );
    conv.activeRunId = null;
    conv.lastMessage = text.slice(0, 120) || conv.lastMessage;
    conv.updated_at = now();
  }
  emit(r, { type: 'terminal', payload: snapshotPayload(r, 'terminal') });
}

function step(r: MockRun) {
  if (r.paused || r.run.status !== 'running') return;
  const batch = r.script[r.cursor];
  if (!batch) {
    finish(r, 'completed');
    return;
  }
  r.cursor += 1;
  const stamped: RawEvent[] = batch.map((e) => ({
    ...e,
    seq: r.events.length + batch.indexOf(e) + 1,
    timestamp: Date.now(),
  }));
  r.events.push(...stamped);
  const interrupt = stamped.some((e) => e.name === 'HITL_INTERRUPT');
  if (interrupt) {
    r.paused = true;
    r.run.pendingInterrupts = 1;
  }
  r.run.updatedAt = now();
  emit(r, {
    type: 'event',
    seq: `${r.events.length}-0`,
    payload: {
      type: 'events',
      run: {
        id: r.run.id,
        status: r.run.status,
        updatedAt: r.run.updatedAt,
        pendingInterrupts: r.run.pendingInterrupts ?? 0,
      },
      events: stamped,
    },
  });
  if (!r.paused) r.timer = setTimeout(() => step(r), isTest() ? 0 : 140 + Math.random() * 160);
}

function launch(r: MockRun, delay = 500) {
  r.run.status = 'running';
  r.timer = setTimeout(() => step(r), isTest() ? 0 : delay);
}

export function subscribeMockRun(runId: string, listener: Listener): () => void {
  const r = runs.get(runId);
  if (!r) {
    setTimeout(() => listener({ type: 'terminal', payload: null }), 0);
    return () => undefined;
  }
  r.listeners.add(listener);
  // A fresh subscriber gets the whole log so far, like the backend's live snapshot.
  setTimeout(() => listener({ type: 'snapshot', payload: snapshotPayload(r, 'snapshot') }), 0);
  return () => r.listeners.delete(listener);
}

// ---------------------------------------------------------------------------
// The store API (used by the mock routes)
// ---------------------------------------------------------------------------
function storeAttachments(list: AttachmentIn[] | undefined): AttachmentOut[] {
  return (list ?? []).map((a) => seedAttachment(a.name, a.mime, a.dataB64));
}

function newRun(
  conv: ConversationDetail,
  parentId: string,
  text: string,
  messagePath: string[],
): { run: InferenceRunOut; message: MessageOut } {
  const id = uid('msg');
  const placeholder = message({
    id,
    sender: 'ai',
    parentMessageId: parentId,
    agentSlug: conv.agentSlug,
    agentName: conv.agentName,
    streamingStatus: 'queued',
  });
  conv.messages.push(placeholder);
  conv.activeRunId = id;
  const run: InferenceRunOut = {
    id,
    conversationId: conv.id,
    assistantMessageId: id,
    parentMessageId: parentId,
    status: 'queued',
    agentSlug: conv.agentSlug,
    agentName: conv.agentName,
    messagePath,
    rawEvents: [],
    startedAt: now(),
    updatedAt: now(),
  };
  const interruptId = uid('int');
  const ask = /clarif/i.test(text);
  const script = ask
    ? askScript(interruptId)
    : answerScript({ toolCallId: uid('call'), taskId: uid('task'), interruptId, text });
  const r: MockRun = {
    run,
    events: [],
    script: script.before,
    cursor: 0,
    paused: false,
    listeners: new Set(),
    interruptId,
  };
  (r as MockRun & { tail: typeof script.tail }).tail = script.tail;
  runs.set(id, r);
  launch(r);
  return { run, message: placeholder };
}

export const mockChat = {
  list: (filter: 'recent' | 'pinned' | 'archived') =>
    [...conversations.values()]
      .filter((c) =>
        filter === 'archived'
          ? c.isArchived
          : !c.isArchived && (filter === 'pinned' ? c.isPinned : !c.isPinned),
      )
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
      .map(summaryOf),
  get: (id: string) => conversations.get(id),
  remove: (id: string) => conversations.delete(id),
  patch: (id: string, patch: Partial<ConversationDetail>) => {
    const c = conversations.get(id);
    if (!c) return undefined;
    Object.assign(c, patch, { updated_at: c.updated_at });
    return summaryOf(c);
  },
  rate: (convId: string, msgId: string, liked: boolean) => {
    const m = conversations.get(convId)?.messages.find((x) => x.id === msgId);
    if (m) m.liked = m.liked === liked ? null : liked;
    return m;
  },
  start: (payload: InferenceStartPayload): InferenceStartResponse | null => {
    const text = payload.message?.content ?? '';
    if (payload.mode === 'new') {
      const id = uid('conv');
      const conv: ConversationDetail = {
        id,
        agentSlug: payload.agentSlug ?? 'assistant',
        agentName: payload.agentName ?? 'Copilot',
        title: payload.title ?? (text.slice(0, 60) || 'New chat'),
        isArchived: false,
        isPinned: false,
        systemId: payload.systemId ?? null,
        auditId: payload.auditId ?? null,
        lastMessage: text.slice(0, 120),
        created_at: now(),
        updated_at: now(),
        messages: [],
      };
      const user = message({
        id: uid('msg'),
        sender: 'user',
        content: text,
        attachments: storeAttachments(payload.message?.attachments),
      });
      conv.messages.push(user);
      conversations.set(id, conv);
      const { run, message: ai } = newRun(conv, user.id, text, [user.id]);
      return { summary: summaryOf(conv), run, message: ai, userMessage: user };
    }
    const conv = payload.conversationId ? conversations.get(payload.conversationId) : undefined;
    if (!conv) return null;
    conv.updated_at = now();
    if (payload.mode === 'retry') {
      const target = conv.messages.find((m) => m.id === payload.targetMessageId);
      const parent = conv.messages.find((m) => m.id === target?.parentMessageId);
      if (!parent) return null;
      const { run, message: ai } = newRun(conv, parent.id, parent.content ?? '', [parent.id]);
      return { summary: summaryOf(conv), run, message: ai, userMessage: null };
    }
    const parentId =
      payload.mode === 'edit'
        ? (conv.messages.find((m) => m.id === payload.targetMessageId)?.parentMessageId ?? null)
        : (payload.parentMessageId ?? null);
    const user = message({
      id: uid('msg'),
      sender: 'user',
      content: text,
      parentMessageId: parentId,
      attachments: storeAttachments(payload.message?.attachments),
    });
    conv.messages.push(user);
    conv.lastMessage = text.slice(0, 120);
    const { run, message: ai } = newRun(conv, user.id, text, [user.id]);
    return { summary: summaryOf(conv), run, message: ai, userMessage: user };
  },
  activeRuns: () =>
    [...runs.values()]
      .filter((r) => ['queued', 'running', 'cancelling'].includes(String(r.run.status)))
      .map((r) => r.run),
  cancel: (runId: string) => {
    const r = runs.get(runId);
    if (!r) return undefined;
    finish(r, 'cancelled');
    return r.run;
  },
  resume: (runId: string, payload: ResumePayload) => {
    const r = runs.get(runId) as
      | (MockRun & { tail?: (ok: boolean, answers?: unknown) => RawEvent[][] })
      | undefined;
    if (!r || !r.paused) return undefined;
    const answers = (payload.value as { answers?: unknown } | undefined)?.answers;
    const approved = payload.decision === 'approve';
    r.script = [...r.script.slice(0, r.cursor), ...(r.tail?.(approved, answers) ?? [])];
    r.paused = false;
    r.run.pendingInterrupts = 0;
    r.timer = setTimeout(() => step(r), isTest() ? 0 : 200);
    return r.run;
  },
  search: (q: string) => {
    const needle = q.toLowerCase();
    const out: {
      kind: 'conversation' | 'message' | 'file';
      id: string;
      conversationId: string;
      title: string;
      snippet?: string;
      updatedAt: string;
    }[] = [];
    for (const c of conversations.values()) {
      if ((c.title ?? '').toLowerCase().includes(needle))
        out.push({
          kind: 'conversation',
          id: c.id,
          conversationId: c.id,
          title: c.title ?? 'Untitled',
          updatedAt: c.updated_at,
        });
      for (const m of c.messages) {
        const text = m.content ?? '';
        const at = text.toLowerCase().indexOf(needle);
        if (at >= 0)
          out.push({
            kind: 'message',
            id: m.id,
            conversationId: c.id,
            title: c.title ?? 'Untitled',
            snippet: text.slice(Math.max(0, at - 40), at + 80),
            updatedAt: m.created_at,
          });
        for (const a of m.attachments) {
          if (a.name.toLowerCase().includes(needle))
            out.push({
              kind: 'file',
              id: a.id,
              conversationId: c.id,
              title: a.name,
              snippet: c.title ?? undefined,
              updatedAt: a.timestamp,
            });
        }
      }
    }
    return out.slice(0, 20);
  },
  findAttachment: (attachmentId: string) => {
    for (const c of conversations.values()) {
      for (const m of c.messages) {
        const a = m.attachments.find((x) => x.id === attachmentId);
        if (a) return a;
      }
    }
    return undefined;
  },
};

// ---------------------------------------------------------------------------
// Seed conversations
// ---------------------------------------------------------------------------
function seedFinished(opts: {
  id: string;
  title: string;
  minutes: number;
  user: string;
  attachments?: AttachmentOut[];
  systemId?: string;
  auditId?: string;
  pinned?: boolean;
  approve?: boolean;
  /** Show the agent's plan and a background task in the answer. */
  withPlan?: boolean;
  /** An earlier version of the user message: the chat then has 2 branches (edited message). */
  editedFrom?: string;
}) {
  const userId = `${opts.id}-u1`;
  const aiId = `${opts.id}-a1`;
  const script = answerScript({
    toolCallId: `${opts.id}-call`,
    taskId: `${opts.id}-task`,
    interruptId: `${opts.id}-int`,
    text: opts.user,
  });
  const all = [...script.before, ...script.tail(opts.approve ?? true)].flat();
  if (opts.withPlan) {
    all.splice(1, 0, custom('PLAN_SNAPSHOT', { todos: PLAN_TODOS }));
    const after = all.findIndex((e) => e.name === 'SUBAGENT_COMPLETED') + 1;
    all.splice(
      after,
      0,
      custom('TASK_LAUNCHED', {
        task_id: `${opts.id}-bg`,
        name: 'evidence-checker',
        description: 'Collect the per-group rates of the last three audits for the trend chart',
      }),
      custom('TASK_SETTLED_INLINE', {
        task_id: `${opts.id}-bg`,
        name: 'evidence-checker',
        status: 'success',
      }),
    );
  }
  const start = Date.parse(minutesAgo(opts.minutes));
  const events: RawEvent[] = all.map((e, i) => ({ ...e, seq: i + 1, timestamp: start + i * 900 }));
  const text = events
    .filter((e) => e.type === 'TEXT_MESSAGE_CONTENT')
    .map((e) => String(e.delta))
    .join('');
  const conv: ConversationDetail = {
    id: opts.id,
    agentSlug: 'assistant',
    agentName: 'Copilot',
    title: opts.title,
    isArchived: false,
    isPinned: Boolean(opts.pinned),
    pinnedAt: opts.pinned ? minutesAgo(opts.minutes) : null,
    systemId: opts.systemId ?? null,
    auditId: opts.auditId ?? null,
    lastMessage: text.slice(0, 120),
    created_at: minutesAgo(opts.minutes + 2),
    updated_at: minutesAgo(opts.minutes),
    messages: [
      ...(opts.editedFrom ? earlierBranch(opts.id, opts.editedFrom, opts.minutes + 6) : []),
      message({
        id: userId,
        sender: 'user',
        content: opts.user,
        attachments: opts.attachments ?? [],
        created_at: minutesAgo(opts.minutes + 2),
      }),
      message({
        id: aiId,
        sender: 'ai',
        parentMessageId: userId,
        content: text,
        rawEvents: events,
        streamingStatus: 'completed',
        agentSlug: 'assistant',
        agentName: 'Copilot',
        created_at: minutesAgo(opts.minutes + 1),
        attachments: [
          seedAttachment(
            'F-001-evidence.md',
            'text/markdown',
            b64('# F-001 evidence\n\nRatio 0.83 < 0.90.\n'),
            'generated',
            { title: 'F-001 evidence summary' },
          ),
        ],
      }),
    ],
  };
  conversations.set(conv.id, conv);
}

const PLAN_TODOS = [
  { content: 'Check F-001 against Art. 10(2)(f)', status: 'completed' },
  { content: 'Recompute the per-group selection ratio', status: 'completed' },
  { content: 'Confirm the rates in the system dossier', status: 'completed' },
  { content: 'Write the finding note and the evidence summary', status: 'completed' },
];

/** The first version of an edited user message and the answer it got (branch 1 of 2). */
function earlierBranch(convId: string, text: string, minutes: number): MessageOut[] {
  const userId = `${convId}-u0`;
  const answer =
    'Two systems use training data covered by the changed Art. 10 guidance: the **CV Screener** and the **Loan Scorer**.';
  const start = Date.parse(minutesAgo(minutes));
  const events: RawEvent[] = [
    ev('RUN_STARTED'),
    ev('THINKING_START'),
    ev('THINKING_TEXT_MESSAGE_CONTENT', {
      delta: '**Finding the affected systems**\n\nList the systems whose data falls under Art. 10.',
    }),
    ev('THINKING_END'),
    ev('TEXT_MESSAGE_START'),
    ev('TEXT_MESSAGE_CONTENT', { delta: answer }),
    ev('TEXT_MESSAGE_END'),
    ev('RUN_FINISHED'),
  ].map((e, i) => ({ ...e, seq: i + 1, timestamp: start + i * 1200 }));
  return [
    message({ id: userId, sender: 'user', content: text, created_at: minutesAgo(minutes) }),
    message({
      id: `${convId}-a0`,
      sender: 'ai',
      parentMessageId: userId,
      content: answer,
      rawEvents: events,
      streamingStatus: 'completed',
      agentSlug: 'assistant',
      agentName: 'Copilot',
      created_at: minutesAgo(minutes - 1),
    }),
  ];
}

function seedPausedOnApproval() {
  const id = 'conv-hitl';
  const userId = `${id}-u1`;
  const aiId = `${id}-a1`;
  const conv: ConversationDetail = {
    id,
    agentSlug: 'assistant',
    agentName: 'Copilot',
    title: 'Record the F-001 finding note',
    isArchived: false,
    isPinned: false,
    systemId: 'SYS-001',
    lastMessage: 'Record a note for F-001 in the CV Screener folder.',
    created_at: minutesAgo(3),
    updated_at: minutesAgo(1),
    activeRunId: aiId,
    messages: [
      message({
        id: userId,
        sender: 'user',
        content: 'Record a note for F-001 in the CV Screener folder.',
        created_at: minutesAgo(3),
      }),
      message({
        id: aiId,
        sender: 'ai',
        parentMessageId: userId,
        streamingStatus: 'running',
        agentSlug: 'assistant',
        agentName: 'Copilot',
        created_at: minutesAgo(3),
      }),
    ],
  };
  conversations.set(id, conv);
  const script = answerScript({
    toolCallId: `${id}-call`,
    taskId: `${id}-task`,
    interruptId: `${id}-int`,
    text: '',
  });
  const r: MockRun & { tail?: (ok: boolean) => RawEvent[][] } = {
    run: {
      id: aiId,
      conversationId: id,
      assistantMessageId: aiId,
      parentMessageId: userId,
      status: 'running',
      agentSlug: 'assistant',
      agentName: 'Copilot',
      messagePath: [userId],
      rawEvents: [],
      startedAt: minutesAgo(3),
      updatedAt: minutesAgo(1),
      pendingInterrupts: 1,
    },
    events: script.before
      .flat()
      .map((e, i) => ({ ...e, seq: i + 1, timestamp: Date.now() - 120_000 + i * 1500 })),
    script: script.before,
    cursor: script.before.length,
    paused: true,
    listeners: new Set(),
    interruptId: `${id}-int`,
  };
  r.tail = script.tail;
  runs.set(aiId, r);
}

function seed() {
  seedFinished({
    id: 'conv-f001',
    title: 'Why is F-001 a gap?',
    minutes: 42,
    user: 'Why did F-001 on the CV Screener indicate a gap? The model card and the rates are attached.',
    systemId: 'SYS-001',
    attachments: [
      seedAttachment('model-card.pdf', 'application/pdf', b64(PDF_TEXT)),
      seedAttachment('selection_rates.csv', 'text/csv', b64(CSV_TEXT)),
      seedAttachment('selection-rates.svg', 'image/svg+xml', b64(CHART_SVG)),
    ],
  });
  seedFinished({
    id: 'conv-art10',
    title: 'Art. 10 guideline change: who is affected?',
    minutes: 60 * 26,
    user: 'Which systems are affected by the Art. 10 guideline change?',
    editedFrom: 'Which systems does the new Art. 10 guidance touch?',
  });
  seedFinished({
    id: 'conv-plan',
    title: 'Audit plan for the Loan Scorer',
    minutes: 60 * 50,
    user: 'Draft an audit plan for the Loan Scorer.',
    pinned: true,
    withPlan: true,
  });
  seedPausedOnApproval();
}

seed();
