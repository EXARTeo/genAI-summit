/**
 * Per-message actions (magenticx `message_parts/ActionBars.tsx` + `BranchControls.tsx` +
 * `MessageUsage.tsx`): branch switcher (‹ 2/3 ›), copy, edit (user), retry and thumbs (AI), and
 * the run's usage line.
 */
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Pencil,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { IconButton } from '@/shared/ui';
import type { RunUsage } from '../../lib/timeline';

export function BranchControls({
  index,
  count,
  onSelect,
}: {
  index: number;
  count: number;
  onSelect: (index: number) => void;
}) {
  if (count < 2) return null;
  return (
    <div className="flex items-center text-2xs text-muted" aria-label="Branches">
      <IconButton
        label="Previous version"
        size="icon-sm"
        icon={<ChevronLeft />}
        disabled={index === 0}
        onClick={() => onSelect(index - 1)}
      />
      <span className="num min-w-[2.25rem] text-center">
        {index + 1}/{count}
      </span>
      <IconButton
        label="Next version"
        size="icon-sm"
        icon={<ChevronRight />}
        disabled={index >= count - 1}
        onClick={() => onSelect(index + 1)}
      />
    </div>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <IconButton
      label={copied ? 'Copied' : 'Copy'}
      size="icon-sm"
      icon={copied ? <Check /> : <Copy />}
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
    />
  );
}

export function UserActions({
  text,
  onEdit,
  disabled,
}: {
  text: string;
  onEdit: () => void;
  disabled?: boolean;
}) {
  return (
    <>
      <CopyButton text={text} />
      <IconButton label="Edit" size="icon-sm" icon={<Pencil />} onClick={onEdit} disabled={disabled} />
    </>
  );
}

export function AiActions({
  text,
  liked,
  onRetry,
  onRate,
  disabled,
}: {
  text: string;
  liked?: boolean | null;
  onRetry: () => void;
  onRate: (liked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <>
      <CopyButton text={text} />
      <IconButton label="Retry" size="icon-sm" icon={<RotateCcw />} onClick={onRetry} disabled={disabled} />
      <IconButton
        label="Good answer"
        size="icon-sm"
        icon={<ThumbsUp className={cn(liked === true && 'fill-primary/20 text-primary')} />}
        onClick={() => onRate(true)}
        aria-pressed={liked === true}
      />
      <IconButton
        label="Bad answer"
        size="icon-sm"
        icon={<ThumbsDown className={cn(liked === false && 'fill-danger/15 text-danger')} />}
        onClick={() => onRate(false)}
        aria-pressed={liked === false}
      />
    </>
  );
}

const k = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

export function UsageLine({
  usage,
  tools,
  seconds,
}: {
  usage: RunUsage | null;
  tools: number;
  seconds: number | null;
}) {
  const parts = [
    usage?.model,
    usage ? `${k(usage.inputTokens)} in · ${k(usage.outputTokens)} out` : null,
    tools ? `${tools} tool${tools > 1 ? 's' : ''}` : null,
    seconds ? `${seconds} s` : null,
  ].filter(Boolean);
  if (!parts.length) return null;
  return <span className="num hidden truncate text-2xs text-muted sm:inline">{parts.join(' · ')}</span>;
}
