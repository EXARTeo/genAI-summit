/**
 * One message (magenticx `components/ChatMessage.tsx` + `message_parts/Content.tsx` +
 * `TimelineSequence.tsx`).
 *
 * - User: its files above a right-aligned card (`max-w-[85%] md:max-w-[75%]`, time inside under
 *   the text), edited in place (an edit is a new branch); on hover ‹ 2/3 › · Copy · Edit below.
 * - Agent: no header; the run timeline in log order (nested sub-agents inside their parent's card;
 *   the plan lives in the composer's plan panel, as in magenticx) at full column width (thinking, sub-agents,
 *   artifacts, tasks, the streamed answer), then the action bar: time · agent · usage · actions.
 */
import { AlertTriangle, Check, CircleStop, X } from 'lucide-react';
import { memo, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, Button, Textarea } from '@/shared/ui';
import type { SiblingInfo } from '../lib/branches';
import { formatClock } from '../lib/messageFormat';
import { stripNotificationEcho } from '../lib/notificationEcho';
import { isActiveRun, type LiveRun } from '../lib/runState';
import { subagentTree } from '../lib/subagentTree';
import { hasAgentSignal, timelineText, type SubagentBlock } from '../lib/timeline';
import type { MessageOut } from '../lib/types';
import { AiActionBar, UserActionBar } from './message_parts/ActionBars';
import { ChatMarkdown } from './message_parts/ChatMarkdown';
import { MessageAttachments } from './message_parts/MessageAttachments';
import { ArtifactCard, TaskRefRow } from './message_parts/RunBlocks';
import { SubagentCard } from './message_parts/SubagentCard';
import { TaskSettledMarker } from './message_parts/TaskSettledMarker';
import { ThinkingBlock } from './message_parts/ThinkingBlock';

interface BaseProps {
  message: MessageOut;
  siblings: SiblingInfo;
  onBranch: (index: number) => void;
  busy: boolean;
}

export const UserMessage = memo(function UserMessage({
  message,
  siblings,
  onBranch,
  busy,
  onEdit,
}: BaseProps & { onEdit: (text: string) => Promise<boolean> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content ?? '');
  const [saving, setSaving] = useState(false);
  const text = message.content ?? '';

  const submit = () => {
    if (!draft.trim() || busy || saving) return;
    setSaving(true);
    void onEdit(draft)
      .then((ok) => ok && setEditing(false))
      .finally(() => setSaving(false));
  };

  return (
    <div className="group/message flex flex-col items-end gap-2">
      <MessageAttachments attachments={message.attachments} messageId={message.id} align="end" />
      {(text || editing) && (
        <div
          className={cn(
            'min-w-0 rounded-lg border border-border p-5 shadow-card',
            'bg-foreground text-background dark:bg-surface-sunken dark:text-foreground',
            editing ? 'w-full' : 'max-w-[85%] md:max-w-[75%]',
          )}
          data-testid="user-bubble"
        >
          <div className="flex flex-col gap-3">
            {editing ? (
              <Textarea
                autoFocus
                value={draft}
                disabled={saving}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    e.preventDefault();
                    setEditing(false);
                  }
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    submit();
                  }
                }}
                className="min-h-24 resize-none border-0 bg-transparent p-0 text-base text-inherit shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
                aria-label="Edit message"
              />
            ) : (
              <p className="whitespace-pre-wrap break-words text-base leading-relaxed">{text}</p>
            )}
            <div className="flex items-center justify-between gap-2 text-sm">
              <span className="num opacity-70">{formatClock(message.created_at)}</span>
              {editing && (
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    leftIcon={<X />}
                    disabled={saving}
                    onClick={() => setEditing(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    leftIcon={<Check />}
                    loading={saving}
                    disabled={!draft.trim() || busy}
                    onClick={submit}
                  >
                    Submit
                  </Button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {!editing && (
        <UserActionBar
          text={text}
          editDisabled={busy}
          onEdit={() => {
            setDraft(text);
            setEditing(true);
          }}
          branch={{ index: siblings.index, count: siblings.count, onSelect: onBranch }}
        />
      )}
    </div>
  );
});

export const AssistantMessage = memo(function AssistantMessage({
  message,
  run,
  siblings,
  onBranch,
  busy,
  onRetry,
  onRate,
  showBar = true,
  copyText,
}: BaseProps & {
  run: LiveRun | null;
  /** Kept for callers; the bar now shows on every settled answer, as in magenticx. */
  isLast?: boolean;
  onRetry: () => void;
  onRate: (liked: boolean) => void;
  /**
   * False for an earlier part of a stacked answer (lib/answerGroups): only the group's last
   * message carries the action bar.
   */
  showBar?: boolean;
  /** What Copy takes: the whole group's text for a stacked answer. */
  copyText?: string;
}) {
  const root = useRef<HTMLDivElement>(null);
  const live = isActiveRun(run);
  const timeline = run?.timeline ?? null;
  const text = timelineText(timeline) || stripNotificationEcho(message.content ?? '');
  const status = String(run?.status ?? message.streamingStatus ?? 'completed');
  const lastBlock = timeline?.blocks[timeline.blocks.length - 1];
  const streamingText = live && lastBlock?.kind === 'content';
  const lastThinking = timeline?.blocks.filter((b) => b.kind === 'thinking').at(-1);
  const generated = message.attachments.filter((a) => a.origin === 'generated');
  const uploads = message.attachments.filter((a) => a.origin !== 'generated');
  const usedFiles = new Set<string>();
  const subagentCount = timeline?.blocks.filter((b) => b.kind === 'subagent').length ?? 0;
  // Nested sub-agents sit inside the card of the sub-agent that delegated to them.
  const tree = subagentTree(timeline);
  const renderSubagent = (block: SubagentBlock): ReactNode => (
    <SubagentCard
      block={block}
      live={live}
      nested={tree.childrenOf(block).map((child) => ({
        key: child.id,
        active: child.status === 'running',
        node: renderSubagent(child),
      }))}
    />
  );

  const openSubagents = () =>
    root.current
      ?.querySelector('[data-subagent-anchor]')
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' });

  return (
    <div ref={root} className="group/message flex min-w-0 flex-col gap-3" aria-busy={live || undefined}>
      {live && !hasAgentSignal(timeline) && (
        <AgentThinking size="sm" label="Starting" className="text-muted" />
      )}

      {timeline?.blocks.map((block) => {
        switch (block.kind) {
          case 'thinking':
            return (
              <ThinkingBlock
                key={block.id}
                block={block}
                live={live}
                doneStatus={
                  block === lastThinking && (status === 'cancelled' || status === 'failed')
                    ? status
                    : undefined
                }
              />
            );
          case 'content': {
            // A notification the model echoed is never the agent's words (lib/notificationEcho).
            const shown = stripNotificationEcho(block.text);
            if (!shown) return null;
            return (
              <ChatMarkdown key={block.id} text={shown} streaming={streamingText && block === lastBlock} />
            );
          }
          case 'subagent':
            if (tree.isNested(block)) return null;
            return (
              <div key={block.id} data-subagent-anchor className="min-w-0">
                {renderSubagent(block)}
              </div>
            );
          case 'artifact': {
            const attachment = generated.find((a) => a.name === block.filename && !usedFiles.has(a.id));
            if (attachment) usedFiles.add(attachment.id);
            return (
              <ArtifactCard key={block.id} block={block} attachment={attachment} messageId={message.id} />
            );
          }
          case 'task_ref':
            return <TaskRefRow key={block.id} block={block} />;
          case 'task_settled':
            return <TaskSettledMarker key={block.id} block={block} />;
          default:
            return null;
        }
      })}

      {!timeline && message.content ? <ChatMarkdown text={stripNotificationEcho(message.content)} /> : null}

      {(() => {
        const rest = [...uploads, ...generated.filter((a) => !usedFiles.has(a.id))];
        return rest.length ? <MessageAttachments attachments={rest} messageId={message.id} /> : null;
      })()}

      {status === 'failed' && (
        <div className="flex items-start gap-2 rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span className="flex-1">
            {run?.errorMessage ?? message.errorMessage ?? 'The agent could not finish this answer.'}
          </span>
          <Button size="sm" variant="ghost" onClick={onRetry} className="h-6 text-danger">
            Retry
          </Button>
        </div>
      )}
      {status === 'cancelled' && (
        <div className="flex items-center gap-1.5 text-2xs text-muted">
          <CircleStop className="size-3" /> Stopped
        </div>
      )}
      {status === 'cancelling' && <AgentThinking size="sm" label="Stopping" />}

      {!live && showBar && (
        <AiActionBar
          text={copyText ?? text}
          time={formatClock(run?.completedAt ?? message.created_at)}
          agentName={message.agentName ?? message.agentSlug ?? 'Agent'}
          liked={message.liked}
          onRate={onRate}
          onRetry={onRetry}
          retryDisabled={busy}
          subagentCount={subagentCount}
          onOpenSubagents={openSubagents}
          branch={{ index: siblings.index, count: siblings.count, onSelect: onBranch }}
        />
      )}
    </div>
  );
});
