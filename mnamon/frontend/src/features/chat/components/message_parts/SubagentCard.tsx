/**
 * A delegated sub-agent (magenticx `message_parts/SubagentContainer.tsx` `SubagentCard`).
 * Collapsed it is one compact row: bot badge, name (+ type chip), what it was asked, tool count,
 * duration once settled, status chip, chevron. Expanded it shows the full task (clamped with
 * Show more), its RESPONSE, its TOOL ACTIVITY (each call with ARGS / RESULT) and any approvals
 * or questions it raised. While it works, a teal hairline runs along the top edge (our
 * `glow-border` motion; magenticx's conic ring and gradient fill are decorative, so the card is a
 * flat token surface here).
 */
import { Bot, Check, ChevronRight, Copy, Hand, MessageSquareText, Wrench } from 'lucide-react';
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { approvalHeadline, hitlActionRequests, toTitleCase } from '../../lib/hitl';
import type { Approval, SubagentBlock, ToolStep } from '../../lib/timeline';
import { formatSubagentDuration, parseToolArgs } from '../../lib/toolPresentation';
import { ChatMarkdown } from './ChatMarkdown';
import { Collapse } from './CoTStep';
import { SubagentStatusChip } from './SubagentStatusChip';
import { prettyPayload } from './ToolCallView';

const normalizeName = (value: string) => value.toLowerCase().replace(/[-_\s]+/g, '');

function SectionLabel({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <span className="flex items-center gap-2 text-2xs font-semibold uppercase tracking-[0.22em] text-muted">
      <span className="grid size-7 place-items-center rounded-full bg-primary/10 text-primary">{icon}</span>
      {title}
    </span>
  );
}

function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`Toggle ${title.toLowerCase()}`}
        className="mb-3 flex w-full items-center text-left"
      >
        <SectionLabel icon={icon} title={title} />
      </button>
      <Collapse open={open}>{children}</Collapse>
    </section>
  );
}

/** A content box with a Copy button on hover (magenticx `CopyableContentBox`, in our tokens). */
function CopyBox({ text, children, maxH }: { text: string; children: ReactNode; maxH: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="group/copy relative overflow-hidden rounded-2xl border border-border/60 bg-surface-sunken px-4 py-3">
      <button
        type="button"
        onClick={copy}
        aria-label={copied ? 'Copied' : 'Copy'}
        className="absolute right-2 top-2 grid size-7 place-items-center rounded-md text-muted opacity-0 transition-opacity hover:bg-hover hover:text-text focus-visible:opacity-100 group-hover/copy:opacity-100"
      >
        {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
      </button>
      <div className={cn('overflow-y-auto pr-8', maxH)}>{children}</div>
    </div>
  );
}

function ToolActivityItem({ tool }: { tool: ToolStep }) {
  const status =
    tool.state === 'output-error' ? 'failed' : tool.state === 'output-available' ? 'completed' : 'running';
  const [open, setOpen] = useState(true);
  const [argsOpen, setArgsOpen] = useState(true);
  const [resultOpen, setResultOpen] = useState(false);
  // A call that completes in front of the user folds itself, once.
  const previous = useRef(status);
  useLayoutEffect(() => {
    if (status === 'completed' && previous.current !== 'completed') setOpen(false);
    previous.current = status;
  }, [status]);
  const args = prettyPayload(parseToolArgs(tool.argsText));
  const result = tool.result === undefined ? '' : prettyPayload(tool.result);
  return (
    <div className="relative pl-7">
      <span aria-hidden className="absolute left-0 top-1 size-2.5 rounded-full bg-primary" />
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={`Toggle ${tool.name}`}
        className="mb-1.5 flex w-full min-w-0 flex-wrap items-center gap-2 text-left"
      >
        <span className="text-sm font-medium text-text">{tool.name}</span>
        <span
          className={cn(
            'rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em]',
            status === 'failed'
              ? 'bg-danger/10 text-danger'
              : status === 'completed'
                ? 'bg-success/10 text-success'
                : 'bg-primary/10 text-primary',
          )}
        >
          {status}
        </span>
        {tool.approval?.status === 'pending' && (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-warning">
            Needs approval
          </span>
        )}
      </button>
      <Collapse open={open}>
        <div className="space-y-2">
          {args && (
            <div>
              <button
                type="button"
                onClick={() => setArgsOpen((o) => !o)}
                aria-expanded={argsOpen}
                className="mb-1 text-2xs uppercase tracking-[0.14em] text-muted hover:text-text"
              >
                Args
              </button>
              <Collapse open={argsOpen}>
                <CopyBox text={args} maxH="max-h-[6.5rem]">
                  <pre className="whitespace-pre-wrap font-mono text-2xs leading-6 text-text [overflow-wrap:anywhere]">
                    {args}
                  </pre>
                </CopyBox>
              </Collapse>
            </div>
          )}
          {result && (
            <div>
              <button
                type="button"
                onClick={() => setResultOpen((o) => !o)}
                aria-expanded={resultOpen}
                className="mb-1 text-2xs uppercase tracking-[0.14em] text-muted hover:text-text"
              >
                Result
              </button>
              <Collapse open={resultOpen}>
                <CopyBox text={result} maxH="max-h-[8.75rem]">
                  <pre className="whitespace-pre-wrap font-mono text-2xs leading-6 text-text [overflow-wrap:anywhere]">
                    {result}
                  </pre>
                </CopyBox>
              </Collapse>
            </div>
          )}
        </div>
      </Collapse>
    </div>
  );
}

function InterruptItem({ item }: { item: Approval }) {
  const asked = Boolean(item.questions);
  const headline = asked
    ? (item.questions ?? []).map((q) => q.question).join(' · ')
    : approvalHeadline(hitlActionRequests(item.content));
  return (
    <div className="relative pl-7">
      <span aria-hidden className="absolute left-0 top-1 size-2.5 rounded-full bg-warning" />
      <div className="mb-1.5 flex items-center gap-2">
        <span className="rounded-full bg-warning/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.16em] text-warning">
          {asked ? 'Question asked' : 'Approval requested'}
        </span>
        {item.status !== 'pending' && (
          <span className={cn('text-2xs', item.status === 'approved' ? 'text-success' : 'text-danger')}>
            {item.status === 'approved' ? (asked ? 'Answered' : 'Approved') : asked ? 'Skipped' : 'Rejected'}
          </span>
        )}
      </div>
      <p className="text-sm text-text">{headline}</p>
    </div>
  );
}

/** One nested sub-agent under its parent's card (rendered by the caller, recursively). */
export interface NestedSubagent {
  key: string;
  active: boolean;
  node: ReactNode;
}

export function SubagentCard({
  block,
  live,
  nested,
}: {
  block: SubagentBlock;
  live: boolean;
  /** The sub-agents this one delegated to: shown under its row on the agent map's connector rail. */
  nested?: NestedSubagent[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const [clampable, setClampable] = useState(false);
  const promptRef = useRef<HTMLParagraphElement>(null);

  const thinking = block.blocks.flatMap((b) => (b.kind === 'thinking' ? b.items : []));
  const tools = thinking.filter((i): i is ToolStep => i.kind === 'tool');
  const interrupts = thinking.filter((i): i is Approval => i.kind === 'hitl');
  const transcript = block.blocks
    .map((b) => (b.kind === 'content' ? b.text : ''))
    .filter(Boolean)
    .join('\n\n');
  const title = block.label ?? toTitleCase(block.type) ?? 'Sub-agent';
  const showType = Boolean(block.type && normalizeName(block.type) !== normalizeName(title));
  const active = block.status === 'running';
  const settled = block.status === 'done' || block.status === 'failed' || block.status === 'cancelled';
  const duration = settled ? formatSubagentDuration(block.startedAt, block.endedAt) : null;
  const prompt = block.description || 'Delegated sub-agent task in progress.';

  useLayoutEffect(() => {
    const el = promptRef.current;
    if (!expanded || !el || promptOpen) return;
    setClampable(el.scrollHeight > el.clientHeight + 2);
  }, [expanded, promptOpen, prompt]);

  if (!block.spawned && block.status === 'pending' && !live) return null;

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-[22px] border bg-surface shadow-card transition-colors',
        active ? 'glow-border border-primary/30' : 'border-border/70',
      )}
      data-status={block.status}
      aria-busy={active || undefined}
    >
      <button
        type="button"
        onClick={() => setExpanded((o) => !o)}
        aria-expanded={expanded}
        aria-label={`${title}, ${block.status.replace('_', ' ')}`}
        className="flex w-full min-w-0 items-center gap-2.5 py-2.5 pl-3.5 pr-3.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
          <Bot className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-2">
            <span className="min-w-0 truncate text-[13.5px] font-semibold text-text">{title}</span>
            {showType && (
              <span className="hidden shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-[9px] font-medium uppercase tracking-[0.16em] text-primary sm:inline">
                {block.type}
              </span>
            )}
          </span>
          {!expanded && <span className="block truncate text-xs leading-[1.15rem] text-muted">{prompt}</span>}
        </span>
        {tools.length > 0 && (
          <span
            className="num hidden shrink-0 items-center gap-1 text-xs text-muted sm:flex"
            title={`${tools.length} tool call${tools.length === 1 ? '' : 's'}`}
          >
            <Wrench className="size-3" aria-hidden />
            {tools.length}
          </span>
        )}
        {duration && <span className="num hidden shrink-0 text-xs text-muted sm:inline">{duration}</span>}
        <SubagentStatusChip status={block.status} compact />
        <ChevronRight
          aria-hidden
          className={cn('size-4 shrink-0 text-muted transition-transform', expanded && 'rotate-90')}
        />
      </button>

      <Collapse open={expanded}>
        <div className="flex flex-col gap-6 border-t border-border/60 px-4 pb-5 pt-3 sm:px-5">
          <div className="max-w-3xl">
            <p ref={promptRef} className={cn('text-sm leading-6 text-muted', !promptOpen && 'line-clamp-3')}>
              {prompt}
            </p>
            {(clampable || promptOpen) && (
              <button
                type="button"
                onClick={() => setPromptOpen((o) => !o)}
                className="mt-1 text-xs font-medium text-primary transition-colors hover:text-primary/80"
              >
                {promptOpen ? 'Show less' : 'Show more'}
              </button>
            )}
          </div>

          {transcript && (
            <Section icon={<MessageSquareText className="size-3.5" />} title="Response">
              <CopyBox text={transcript} maxH="max-h-[14rem]">
                <ChatMarkdown text={transcript} className="text-sm leading-7" />
              </CopyBox>
            </Section>
          )}

          {tools.length > 0 && (
            <Section icon={<Wrench className="size-3.5" />} title="Tool activity">
              <div className="space-y-4 pl-5">
                {tools.map((tool, index) => (
                  <div key={tool.id} className="relative">
                    {index < tools.length - 1 && (
                      <span aria-hidden className="absolute -bottom-4 left-[5px] top-4 w-px bg-border" />
                    )}
                    <ToolActivityItem tool={tool} />
                  </div>
                ))}
              </div>
            </Section>
          )}

          {interrupts.length > 0 && (
            <Section icon={<Hand className="size-3.5" />} title="Approvals">
              <div className="space-y-3 pl-5">
                {interrupts.map((item) => (
                  <InterruptItem key={item.id} item={item} />
                ))}
              </div>
            </Section>
          )}

          {!transcript && !tools.length && !interrupts.length && (
            <p className="text-xs text-muted">Waiting for the sub-agent to start…</p>
          )}
        </div>
      </Collapse>

      {nested?.length ? (
        <div className="border-t border-border/60 px-3 pb-3 pt-1.5 sm:px-3.5">
          <ul
            aria-label={`${title}'s sub-agents`}
            className="agent-map-group [--am-gap:0.75rem] [--am-indent:0.875rem]"
          >
            {nested.map((child) => (
              <li
                key={child.key}
                className="agent-map-branch pt-1.5 [--am-elbow:2.125rem]"
                data-active={child.active ? 'true' : 'false'}
              >
                {child.node}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
