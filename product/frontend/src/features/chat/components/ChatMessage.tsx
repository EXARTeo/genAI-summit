/**
 * One message (magenticx `components/ChatMessage.tsx` + `message_parts/Content.tsx` +
 * `TimelineSequence.tsx`). A user message is a right-aligned bubble with its files and an inline
 * editor (an edit is a new branch). An agent message renders its run timeline in log order:
 * thinking, sub-agents, artifacts, tasks, the streamed answer; then actions and usage.
 */
import { AlertTriangle, Bell, CircleStop } from 'lucide-react';
import { memo, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { AgentThinking, Button, Textarea } from '@/shared/ui';
import type { SiblingInfo } from '../lib/branches';
import { isActiveRun, type LiveRun } from '../lib/runState';
import { countTools, hasAgentSignal, timelineText } from '../lib/timeline';
import type { MessageOut } from '../lib/types';
import { AiActions, BranchControls, UsageLine, UserActions } from './message_parts/ActionBars';
import { ChatMarkdown } from './message_parts/ChatMarkdown';
import { MessageAttachments } from './message_parts/MessageAttachments';
import { ArtifactCard, PlanChecklist, TaskRefRow, TaskSettledRow } from './message_parts/RunBlocks';
import { SubagentCard } from './message_parts/SubagentCard';
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
  const text = message.content ?? '';

  if (message.kind === 'task_notification') {
    return (
      <div className="flex items-center justify-center gap-2 py-1 text-2xs text-muted">
        <Bell className="size-3" />
        {message.taskNotice?.name ?? 'A background task'} {message.taskNotice?.status ?? 'finished'}
      </div>
    );
  }

  return (
    <div className="group flex flex-col items-end gap-1.5">
      <MessageAttachments attachments={message.attachments} messageId={message.id} align="end" />
      {editing ? (
        <div className="w-full max-w-[85%] rounded-xl border border-primary/40 bg-surface p-2 shadow-card">
          <Textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setEditing(false);
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (draft.trim()) void onEdit(draft).then((ok) => ok && setEditing(false));
              }
            }}
            className="min-h-[72px] resize-none border-0 bg-transparent p-1 shadow-none focus-visible:ring-0"
            aria-label="Edit message"
          />
          <div className="flex justify-end gap-2 pt-1">
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!draft.trim() || busy}
              onClick={() => void onEdit(draft).then((ok) => ok && setEditing(false))}
            >
              Send
            </Button>
          </div>
        </div>
      ) : (
        text && (
          <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-surface-muted px-3.5 py-2 text-sm leading-relaxed">
            {text}
          </div>
        )
      )}
      {!editing && (
        <div className="flex items-center gap-0.5 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          <BranchControls index={siblings.index} count={siblings.count} onSelect={onBranch} />
          <UserActions
            text={text}
            disabled={busy}
            onEdit={() => {
              setDraft(text);
              setEditing(true);
            }}
          />
        </div>
      )}
    </div>
  );
});

function runSeconds(run: LiveRun): number | null {
  if (!run.completedAt) return null;
  const s = Math.round((Date.parse(run.completedAt) - Date.parse(run.startedAt)) / 1000);
  return s > 0 ? s : null;
}

export const AssistantMessage = memo(function AssistantMessage({
  message,
  run,
  siblings,
  onBranch,
  busy,
  isLast,
  onRetry,
  onRate,
}: BaseProps & {
  run: LiveRun | null;
  isLast: boolean;
  onRetry: () => void;
  onRate: (liked: boolean) => void;
}) {
  const live = isActiveRun(run);
  const timeline = run?.timeline ?? null;
  const text = timelineText(timeline) || (message.content ?? '');
  const status = String(run?.status ?? message.streamingStatus ?? 'completed');
  const lastBlock = timeline?.blocks[timeline.blocks.length - 1];
  const streamingText = live && lastBlock?.kind === 'content';
  const generated = message.attachments.filter((a) => a.origin === 'generated');
  const uploads = message.attachments.filter((a) => a.origin !== 'generated');
  const usedFiles = new Set<string>();

  return (
    <div className="group flex flex-col gap-2.5" aria-busy={live || undefined}>
      <div className="flex items-center gap-2 text-2xs font-medium text-muted">
        <span className="grid size-5 place-items-center rounded-md bg-primary/10 text-[10px] font-semibold text-primary">
          {(message.agentName ?? 'A').charAt(0)}
        </span>
        {message.agentName ?? message.agentSlug ?? 'Agent'}
      </div>

      {timeline?.plan?.length ? <PlanChecklist items={timeline.plan} /> : null}

      {live && !hasAgentSignal(timeline) && (
        <AgentThinking size="sm" label="Starting" className="text-muted" />
      )}

      {timeline?.blocks.map((block) => {
        switch (block.kind) {
          case 'thinking':
            return <ThinkingBlock key={block.id} block={block} live={live} />;
          case 'content':
            return (
              <ChatMarkdown
                key={block.id}
                text={block.text}
                streaming={streamingText && block === lastBlock}
              />
            );
          case 'subagent':
            return <SubagentCard key={block.id} block={block} live={live} />;
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
            return <TaskSettledRow key={block.id} block={block} />;
          default:
            return null;
        }
      })}

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

      {!live && (
        <div
          className={cn(
            'flex items-center gap-0.5 transition-opacity focus-within:opacity-100 group-hover:opacity-100',
            !isLast && 'opacity-0',
          )}
        >
          <BranchControls index={siblings.index} count={siblings.count} onSelect={onBranch} />
          <AiActions text={text} liked={message.liked} onRetry={onRetry} onRate={onRate} disabled={busy} />
          {run && <span className="ml-2" />}
          {run && (
            <UsageLine
              usage={run.timeline.usage}
              tools={countTools(run.timeline)}
              seconds={runSeconds(run)}
            />
          )}
        </div>
      )}
    </div>
  );
});
