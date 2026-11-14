/*
 * Drawn here, not taken from Lucide: magenticx's "new chat" mark (`shared/ui/new-chat-icon.tsx`),
 * a softly rounded square left open at its top-right corner with a pencil writing into it. Lucide's
 * `SquarePen` has a sharper page and a thinner pencil. It strokes in `currentColor` on the same
 * 24-unit grid, stroke 2 and round caps as the Lucide icons beside it, so it follows the theme.
 */
import type { SVGProps } from 'react';
import { cn } from '@/shared/lib/utils';

export function NewChatIcon({ className, strokeWidth = 2, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={cn('size-5 shrink-0', className)}
      {...props}
    >
      <path d="M11.25 3.75h-3a4.5 4.5 0 0 0-4.5 4.5v7.5a4.5 4.5 0 0 0 4.5 4.5h7.5a4.5 4.5 0 0 0 4.5-4.5v-3" />
      <path d="M17.7 4.3a2.12 2.12 0 0 1 3 3l-7.2 7.2-3.85 1.05 1.05-3.85z" />
    </svg>
  );
}
