import { ArrowUp, Sparkles } from 'lucide-react';
import { PageHeader } from '@/shared/ui';

const SUGGESTIONS = [
  'Why did F-001 on the CV Screener indicate a gap?',
  'Which systems are affected by the Art. 10 guideline change?',
  'What did reviewers correct in the last audit?',
];

// Stub route view: the composer is shown (disabled) so the page reads as the real thing; replaced when
// the chat feature (src/features/chat) lands on AG-UI.
export default function ChatView() {
  return (
    <div>
      <PageHeader title="Chat" description="Ask the copilot about a system, a finding or an article." />
      <div className="mx-auto flex min-h-[55vh] max-w-2xl flex-col justify-end gap-6 pb-4">
        <div className="text-center">
          <div className="mx-auto mb-3 grid size-10 place-items-center rounded-lg border border-border bg-surface text-primary">
            <Sparkles className="size-4" />
          </div>
          <h2 className="text-base font-semibold">Chat is coming</h2>
          <p className="mt-1 text-sm text-muted">
            Conversations will stream over AG-UI with every tool call visible and traced.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {SUGGESTIONS.map((s) => (
            <div key={s} className="rounded-lg border border-border bg-surface p-3 text-xs text-muted">
              {s}
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-border bg-surface p-2 pl-4 shadow-card">
          <input
            disabled
            aria-label="Message"
            placeholder="Ask about a system, a finding or an article…"
            className="h-8 flex-1 bg-transparent text-sm outline-none placeholder:text-muted disabled:cursor-not-allowed"
          />
          <span className="grid size-8 place-items-center rounded-lg bg-surface-muted text-muted">
            <ArrowUp className="size-4" />
          </span>
        </div>
      </div>
    </div>
  );
}
