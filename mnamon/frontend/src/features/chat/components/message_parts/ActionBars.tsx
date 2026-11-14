/**
 * Per-message action bars (magenticx `message_parts/ActionBars.tsx`).
 *
 * - Answer: time · agent · usage gauge · Copy · Like · Dislike · ⋯ (Try again) · sub-agents (with
 *   a count badge) · ‹ 2/3 ›. A rated answer shows only the thumb it got (click again to clear).
 *   magenticx's Share, Fork, Read aloud, Report and Sources are left out: no backend for them here.
 * - User message: ‹ 2/3 › · Copy · Edit, shown on hover (kept visible for a moment after a copy).
 */
import { Bot, Check, Copy, MoreHorizontal, Pencil, RotateCcw, ThumbsDown, ThumbsUp } from 'lucide-react';
import { motion, useAnimationControls, type TargetAndTransition } from 'framer-motion';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu, IconButton } from '@/shared/ui';
import { BranchControls } from './BranchControls';

/** A tap pulse with a slight overshoot (magenticx); MotionConfig turns it off for reduced motion. */
const TAP_PULSE: TargetAndTransition = {
  scale: [1, 1.28, 1],
  transition: { duration: 0.36, ease: [0.34, 1.56, 0.64, 1] },
};
const COPIED_RESET_MS = 1500;

export const ACTION_BUTTON =
  'size-8 text-muted hover:bg-hover hover:text-text active:bg-hover-strong data-[state=open]:bg-hover-strong';

export interface BranchConfig {
  index: number;
  count: number;
  onSelect: (index: number) => void;
}

export function CopyButton({ text, onCopied }: { text: string; onCopied?: () => void }) {
  const [copied, setCopied] = useState(false);
  const pulse = useAnimationControls();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <IconButton
      label={copied ? 'Copied' : 'Copy'}
      className={ACTION_BUTTON}
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        onCopied?.();
        void pulse.start(TAP_PULSE);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), COPIED_RESET_MS);
      }}
      icon={
        <motion.span animate={pulse} className="relative inline-block size-4">
          <Copy
            className={cn(
              'absolute inset-0 transition-all duration-200',
              copied ? 'scale-75 opacity-0' : 'scale-100 opacity-100',
            )}
          />
          <Check
            className={cn(
              'absolute inset-0 transition-all duration-200',
              copied ? 'scale-100 opacity-100' : 'scale-75 opacity-0',
            )}
          />
        </motion.span>
      }
    />
  );
}

function PulseButton({
  label,
  icon,
  onClick,
  className,
  pressed,
  disabled,
}: {
  label: string;
  icon: ReactNode;
  onClick: () => void;
  className?: string;
  pressed?: boolean;
  disabled?: boolean;
}) {
  const pulse = useAnimationControls();
  return (
    <IconButton
      label={label}
      className={cn(ACTION_BUTTON, className)}
      aria-pressed={pressed}
      disabled={disabled}
      onMouseDown={(e) => e.preventDefault()}
      onClick={() => {
        onClick();
        void pulse.start(TAP_PULSE);
      }}
      icon={
        <motion.span animate={pulse} className="inline-flex">
          {icon}
        </motion.span>
      }
    />
  );
}

export function UserActionBar({
  text,
  onEdit,
  editDisabled,
  branch,
  className,
}: {
  text: string;
  onEdit?: () => void;
  editDisabled?: boolean;
  branch: BranchConfig;
  className?: string;
}) {
  // A copy keeps the bar up for a moment, so the check mark is seen after the pointer leaves.
  const [sticky, setSticky] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <div
      className={cn(
        'flex justify-end transition-opacity duration-150',
        sticky
          ? 'opacity-100'
          : 'opacity-0 focus-within:opacity-100 group-hover/message:opacity-100 [@media(hover:none)]:opacity-100',
        className,
      )}
      data-testid="user-action-bar"
    >
      <div className="flex items-center gap-2">
        <BranchControls index={branch.index} count={branch.count} onSelect={branch.onSelect} />
        <div className="flex items-center gap-0.5">
          <CopyButton
            text={text}
            onCopied={() => {
              setSticky(true);
              if (timer.current) clearTimeout(timer.current);
              timer.current = setTimeout(() => setSticky(false), COPIED_RESET_MS);
            }}
          />
          {onEdit && (
            <PulseButton
              label="Edit message"
              icon={<Pencil className="!size-[18px]" />}
              onClick={onEdit}
              disabled={editDisabled}
            />
          )}
        </div>
      </div>
    </div>
  );
}

export function AiActionBar({
  text,
  time,
  agentName,
  usage,
  liked,
  onRate,
  onRetry,
  retryDisabled,
  subagentCount = 0,
  onOpenSubagents,
  branch,
}: {
  text: string;
  time?: string;
  agentName?: string | null;
  /** The usage gauge (MessageUsage), shown after the agent name. */
  usage?: ReactNode;
  liked?: boolean | null;
  onRate: (liked: boolean) => void;
  onRetry: () => void;
  retryDisabled?: boolean;
  subagentCount?: number;
  onOpenSubagents?: () => void;
  branch: BranchConfig;
}) {
  return (
    <div className="flex w-full flex-wrap items-center gap-x-2 gap-y-1" data-testid="ai-action-bar">
      {(time || agentName || usage) && (
        <div className="flex items-center gap-2 text-xs text-muted md:text-sm">
          {time ? <span className="num">{time}</span> : null}
          {agentName ? (
            <span className="flex items-center gap-1">
              <Bot className="size-4" aria-hidden />
              <span>{agentName}</span>
            </span>
          ) : null}
          {usage}
        </div>
      )}
      <div className="flex items-center gap-0.5">
        <CopyButton text={text} />
        {liked !== false && (
          <PulseButton
            label={liked === true ? 'Remove like' : 'Like'}
            icon={<ThumbsUp className={cn(liked === true && 'fill-primary/20')} />}
            className={cn(liked === true && 'text-primary hover:text-primary')}
            pressed={liked === true}
            onClick={() => onRate(true)}
          />
        )}
        {liked !== true && (
          <PulseButton
            label={liked === false ? 'Remove dislike' : 'Dislike'}
            icon={<ThumbsDown className={cn(liked === false && 'fill-primary/20')} />}
            className={cn(liked === false && 'text-primary hover:text-primary')}
            pressed={liked === false}
            onClick={() => onRate(false)}
          />
        )}
        <DropdownMenu
          align="start"
          trigger={
            <IconButton label="More message actions" icon={<MoreHorizontal />} className={ACTION_BUTTON} />
          }
          items={[{ label: 'Try again', icon: <RotateCcw />, disabled: retryDisabled, onSelect: onRetry }]}
        />
        {subagentCount > 0 && onOpenSubagents && (
          <IconButton
            label={`Sub-agents (${subagentCount})`}
            className={cn(ACTION_BUTTON, 'relative')}
            onMouseDown={(e) => e.preventDefault()}
            onClick={onOpenSubagents}
            icon={
              <>
                <Bot />
                <span className="num absolute -right-0.5 -top-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-primary px-0.5 text-[9px] font-semibold leading-none text-primary-foreground">
                  {subagentCount > 9 ? '9+' : subagentCount}
                </span>
              </>
            }
          />
        )}
        <BranchControls index={branch.index} count={branch.count} onSelect={branch.onSelect} />
      </div>
    </div>
  );
}
