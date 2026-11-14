/**
 * A reply's usage (magenticx `message_parts/MessageUsage.tsx`): a gauge with the compact token
 * total in the action bar, the breakdown on hover or focus (input, output, model calls, tools,
 * run time) with the model in the footer. magenticx's cost, first-token and speed rows are left
 * out: our run events carry no such numbers.
 */
import { Gauge } from 'lucide-react';
import { Tooltip } from '@/shared/ui';
import { formatCompactTokens, formatDuration } from '../../lib/messageFormat';
import type { RunUsage } from '../../lib/timeline';

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-6">
      <span className="opacity-70">{label}</span>
      <span className="num font-medium">{value}</span>
    </div>
  );
}

export function MessageUsage({
  usage,
  tools,
  seconds,
}: {
  usage: RunUsage | null;
  tools: number;
  seconds: number | null;
}) {
  if (!usage) return null;
  const total = usage.inputTokens + usage.outputTokens;
  const card = (
    <div className="flex min-w-[11rem] flex-col gap-1 py-0.5 text-2xs font-normal">
      <Row label="Input" value={usage.inputTokens.toLocaleString()} />
      <Row label="Output" value={usage.outputTokens.toLocaleString()} />
      {usage.modelCalls > 0 && <Row label="Model calls" value={String(usage.modelCalls)} />}
      {tools > 0 && <Row label="Tools" value={String(tools)} />}
      {seconds ? <Row label="Run time" value={formatDuration(seconds)} /> : null}
      {usage.model && (
        <div className="mt-1 truncate border-t border-background/20 pt-1 font-mono opacity-80">
          {usage.model}
        </div>
      )}
    </div>
  );
  return (
    <Tooltip content={card} side="bottom" delayDuration={100}>
      <span
        tabIndex={0}
        className="flex cursor-help items-center gap-1 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        aria-label={`Token usage: ${total.toLocaleString()} tokens`}
      >
        <Gauge className="size-4" aria-hidden />
        <span className="num">{formatCompactTokens(total)}</span>
      </span>
    </Tooltip>
  );
}
