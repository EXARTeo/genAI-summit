/**
 * The agent map's detail view: one sub-agent, opened from the tree or the graph (port of magenticx
 * `agent_map/AgentMapDetail.tsx`). A header with what it is and where it sits (the answer, the
 * sub-agent that delegated to it), then its work read as a conversation: the instruction it was
 * given, as a user message from the agent that delegated, and its reply drawn by the chat's own
 * renderers (thinking and tool steps, Markdown), then the sub-agents it delegated to; a click on
 * one opens it here, a step deeper. A background task shows its whole conversation from its own
 * event stream: every follow-up the parent sent (`update_async_task`) as another bubble, each
 * followed by its reply, in order. Read only: there is no composer.
 */
import { motion, useReducedMotion } from 'framer-motion';
import { Bot, CornerDownRight, MessageSquare, Timer, Wrench, type LucideIcon } from 'lucide-react';
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { AgentThinking } from '@/shared/ui';
import {
  agentNodeDuration,
  agentTranscript,
  type AgentMapAnswer,
  type AgentMapNode,
} from '../../lib/agentMap';
import { useTaskTranscript } from '../../hooks/useTaskTranscript';
import { stripNotificationEcho } from '../../lib/notificationEcho';
import { transcriptTurns } from '../../lib/taskTranscript';
import { ChatMarkdown } from '../message_parts/ChatMarkdown';
import { SubagentStatusChip } from '../message_parts/SubagentStatusChip';
import { ThinkingBlock } from '../message_parts/ThinkingBlock';
import { AgentNodeCard } from './AgentNodeCard';

const EASE = [0.22, 1, 0.36, 1] as const;
const CLAMP_PX = 168;

function Fact({ icon: Icon, children }: { icon: LucideIcon; children: ReactNode }) {
  return (
    <span className="num flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-border/60 bg-background px-2.5 py-1 text-xs text-muted">
      <Icon className="size-3.5 shrink-0 text-muted/80" aria-hidden />
      <span className="min-w-0 truncate">{children}</span>
    </span>
  );
}

/** The instruction, as the chat draws a user message; a long one starts clipped behind "Show more". */
function InstructionBubble({
  from,
  to,
  text,
  followUp = false,
}: {
  from: string;
  to: string;
  text: string;
  /** A follow-up the parent sent later (`update_async_task`), not the original instruction. */
  followUp?: boolean;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const [long, setLong] = useState(false);
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const measure = () => setLong(el.scrollHeight > CLAMP_PX + 24);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text]);

  return (
    <div className="flex flex-col items-end gap-1.5">
      <p className="flex max-w-full items-center gap-1.5 pr-1 text-2xs text-muted">
        <CornerDownRight className="size-3 shrink-0" aria-hidden />
        <span className="truncate">
          {from} <span aria-hidden>→</span>
          <span className="sr-only">to</span> {to}
          {followUp ? <span className="text-muted/80"> · follow-up</span> : null}
        </span>
      </p>
      <div className="ml-auto max-w-[88%] rounded-lg border border-border bg-foreground p-4 text-background shadow-card dark:bg-surface-sunken dark:text-foreground">
        <div
          className={cn('relative min-w-0', long && !open && 'overflow-hidden')}
          style={long && !open ? { maxHeight: CLAMP_PX } : undefined}
        >
          <div ref={bodyRef}>
            {text.trim() ? (
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{text}</p>
            ) : (
              <p className="text-sm opacity-70">No instruction was recorded.</p>
            )}
          </div>
        </div>
        {long ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-expanded={open}
            className="mt-1.5 rounded text-xs font-medium underline-offset-2 opacity-80 hover:underline hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            {open ? 'Show less' : 'Show more'}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function AgentMapDetail({
  node,
  answer,
  ancestors,
  agentName,
  onOpenNode,
  now,
}: {
  node: AgentMapNode;
  answer: AgentMapAnswer;
  /** The sub-agents above it, outermost first. */
  ancestors: AgentMapNode[];
  /** The conversation's main agent: who delegated to a top-level sub-agent. */
  agentName: string;
  onOpenNode: (id: string) => void;
  now: number;
}) {
  const reduceMotion = useReducedMotion();
  const active = node.status === 'running';
  const duration = agentNodeDuration(node, now);
  const parent = ancestors[ancestors.length - 1];
  const transcript = useMemo(() => agentTranscript(node), [node]);
  // A background task: its whole conversation (every follow-up and reply) from its own stream.
  const task = useTaskTranscript(node.background ? node.taskId : null);
  const turns = useMemo(
    () => (task.timeline ? transcriptTurns(task.timeline, transcript.instruction) : null),
    [task.timeline, transcript.instruction],
  );
  const taskLive = node.status === 'running';
  const own = transcript.timeline.blocks.filter((b) => b.kind === 'thinking' || b.kind === 'content');
  const lastBlock = own[own.length - 1];
  const hasReply = own.length > 0;

  const reveal = (step: number) =>
    reduceMotion
      ? { initial: { opacity: 0 }, animate: { opacity: 1 } }
      : {
          initial: { opacity: 0, y: 8 },
          animate: { opacity: 1, y: 0 },
          transition: { duration: 0.32, ease: EASE, delay: 0.05 + step * 0.05 },
        };

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 pb-2">
      <motion.header {...reveal(0)} className="flex items-start gap-3.5">
        <span
          className={cn(
            'relative grid size-12 shrink-0 place-items-center rounded-2xl border bg-primary/10 text-primary',
            active ? 'glow-border border-primary/40' : 'border-border/70',
          )}
        >
          <Bot className="size-5" aria-hidden />
        </span>
        <div className="flex min-h-12 min-w-0 flex-1 flex-col justify-center gap-0.5">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h3 className="min-w-0 truncate text-lg font-semibold tracking-tight text-text">{node.title}</h3>
            {node.status ? <SubagentStatusChip status={node.status} /> : null}
          </div>
          {node.type ? <p className="truncate font-mono text-xs text-muted">{node.type}</p> : null}
        </div>
      </motion.header>

      <motion.div {...reveal(1)} className="flex flex-wrap gap-2">
        <Fact icon={MessageSquare}>
          Q{answer.number} · {answer.question || 'Untitled question'}
        </Fact>
        {parent ? <Fact icon={CornerDownRight}>Delegated by {parent.title}</Fact> : null}
        {duration ? <Fact icon={Timer}>{duration}</Fact> : null}
        {node.toolCount ? (
          <Fact icon={Wrench}>
            {node.toolCount} tool call{node.toolCount === 1 ? '' : 's'}
          </Fact>
        ) : null}
      </motion.div>

      {/* Keyed by node: another sub-agent mounts fresh, its thinking blocks in their own default state. */}
      <motion.section
        key={node.id}
        {...reveal(2)}
        aria-label={`${node.title}: instruction and reply`}
        className="space-y-5 border-t border-border/50 pt-5"
      >
        {turns ? (
          turns.map((turn, index) => {
            const own = turn.blocks.filter((b) => b.kind === 'thinking' || b.kind === 'content');
            const lastOwn = own[own.length - 1];
            const current = index === turns.length - 1;
            return (
              <div key={turn.id} className="space-y-5" data-testid="task-turn">
                <InstructionBubble
                  from={parent?.title ?? agentName}
                  to={node.title}
                  text={turn.instruction}
                  followUp={turn.followUp}
                />
                <div className="flex w-full min-w-0 flex-col gap-3">
                  {own.map((block) =>
                    block.kind === 'thinking' ? (
                      <ThinkingBlock key={block.id} block={block} live={taskLive && current} />
                    ) : block.kind === 'content' ? (
                      <ChatMarkdown
                        key={block.id}
                        text={stripNotificationEcho(block.text)}
                        streaming={taskLive && current && block === lastOwn}
                      />
                    ) : null,
                  )}
                  {!own.length &&
                    (taskLive && current ? (
                      <AgentThinking size="sm" label="Working" className="text-muted" />
                    ) : (
                      <p className="text-sm text-muted">No reply was recorded.</p>
                    ))}
                </div>
              </div>
            );
          })
        ) : (
          <>
            <InstructionBubble
              from={parent?.title ?? agentName}
              to={node.title}
              text={transcript.instruction}
            />

            <div className="flex w-full min-w-0 flex-col gap-3">
              {own.map((block) =>
                block.kind === 'thinking' ? (
                  <ThinkingBlock key={block.id} block={block} live={transcript.live} />
                ) : block.kind === 'content' ? (
                  <ChatMarkdown
                    key={block.id}
                    text={block.text}
                    streaming={transcript.live && block === lastBlock}
                  />
                ) : null,
              )}
              {!hasReply &&
                (transcript.live || (node.background && !task.loaded) ? (
                  <AgentThinking size="sm" label="Starting" className="text-muted" />
                ) : (
                  <p className="text-sm text-muted">No reply was recorded.</p>
                ))}
            </div>
          </>
        )}

        {node.children.length ? (
          <section aria-label="Sub-agents it delegated to" className="space-y-1.5">
            <p className="px-1 text-xs text-muted">Delegated to</p>
            <ul className="space-y-2">
              {node.children.map((child) => (
                <li key={child.id}>
                  <button
                    type="button"
                    onClick={() => onOpenNode(child.id)}
                    aria-label={`Open ${child.title}`}
                    className="group/node block w-full rounded-2xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
                  >
                    <AgentNodeCard node={child} now={now} />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </motion.section>
    </div>
  );
}
