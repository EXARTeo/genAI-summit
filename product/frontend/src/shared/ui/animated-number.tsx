import { animate, useReducedMotion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/shared/lib/utils';

export interface AnimatedNumberProps {
  value: number;
  /** Fraction digits. */
  decimals?: number;
  duration?: number;
  format?: (n: number) => string;
  prefix?: string;
  suffix?: string;
  className?: string;
}

/** Counts up (or down) to `value` whenever it changes. Instant under reduced motion. */
export function AnimatedNumber({
  value,
  decimals = 0,
  duration = 0.9,
  format,
  prefix = '',
  suffix = '',
  className,
}: AnimatedNumberProps) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);
  const from = useRef(reduce ? value : 0);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      from.current = value;
      return;
    }
    const controls = animate(from.current, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => setDisplay(v),
    });
    from.current = value;
    return () => controls.stop();
  }, [value, duration, reduce]);

  const text = format ? format(display) : display.toFixed(decimals);
  return (
    <span
      className={cn('tabular-nums', className)}
      aria-label={`${prefix}${format ? format(value) : value.toFixed(decimals)}${suffix}`}
    >
      {prefix}
      {text}
      {suffix}
    </span>
  );
}
