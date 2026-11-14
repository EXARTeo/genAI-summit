import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import type { BadgeTone } from './badge';

export interface ProgressRingProps {
  /** 0..1 */
  value: number;
  size?: number;
  stroke?: number;
  tone?: Exclude<BadgeTone, 'solid' | 'neutral'> | 'gradient';
  /** Center content; defaults to the percentage. */
  label?: ReactNode;
  className?: string;
}

const COLOR: Record<string, string> = {
  primary: 'rgb(var(--rgb-primary))',
  accent: 'rgb(var(--rgb-accent))',
  success: 'rgb(var(--rgb-success))',
  warning: 'rgb(var(--rgb-warning))',
  danger: 'rgb(var(--rgb-danger))',
  info: 'rgb(var(--rgb-info))',
};

let gradientSeq = 0;

export function ProgressRing({ value, size = 56, stroke = 5, tone = 'gradient', label, className }: ProgressRingProps) {
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const gid = `ring-grad-${(gradientSeq = (gradientSeq + 1) % 1e6)}`;
  return (
    <div
      className={cn('relative inline-grid place-items-center', className)}
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v * 100)}
    >
      <svg width={size} height={size} className="-rotate-90">
        {tone === 'gradient' && (
          <defs>
            <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="rgb(var(--rgb-primary))" />
              <stop offset="100%" stopColor="rgb(var(--rgb-accent))" />
            </linearGradient>
          </defs>
        )}
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgb(var(--rgb-border))" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={tone === 'gradient' ? `url(#${gid})` : COLOR[tone]}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - v) }}
          transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
        />
      </svg>
      <span className="absolute text-xs font-semibold tabular-nums">{label ?? `${Math.round(v * 100)}%`}</span>
    </div>
  );
}
