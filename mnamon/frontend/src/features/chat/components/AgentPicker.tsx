/**
 * The chat's agent picker (magenticx `AgentPicker.tsx`): the agent's name + chevron in the chat
 * header; it opens a search box over the agents, with a check on the current one. Arrow keys
 * move, Enter picks, Escape closes.
 *
 * Built on cmdk (as the ⌘K palette is) inside a small hand-rolled popover: the design system has
 * no Popover primitive, and a Radix DropdownMenu's typeahead steals the keys from a search input.
 */
import { Command } from 'cmdk';
import { Bot, Check, ChevronDown, Search } from 'lucide-react';
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { cn } from '@/shared/lib/utils';
import type { AgentManifest } from '../lib/types';

export interface AgentPickerHandle {
  open: () => void;
}

export const AgentPicker = forwardRef<
  AgentPickerHandle,
  {
    agents: AgentManifest[];
    agent: AgentManifest | null;
    onPick: (agent: AgentManifest) => void;
  }
>(function AgentPicker({ agents, agent, onPick }, ref) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useImperativeHandle(ref, () => ({ open: () => setOpen(true) }), []);

  // Close on a press outside or on Escape (focus goes back to the trigger).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // Ours alone: the chat's Esc (stop the answer) must not fire too.
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener('pointerdown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const pick = (a: AgentManifest) => {
    setOpen(false);
    trigger.current?.focus();
    if (a.slug !== agent?.slug) onPick(a);
  };

  return (
    <div ref={root} className="relative min-w-0">
      <button
        ref={trigger}
        type="button"
        aria-label={`Agent: ${agent?.name ?? 'none selected'}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex h-10 min-w-0 max-w-full items-center gap-1.5 rounded-xl px-2.5 text-text transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 active:bg-hover-strong md:max-w-[22rem]',
          open && 'bg-hover',
        )}
      >
        <span className={cn('min-w-0 truncate text-lg', !agent && 'text-muted')}>
          {agent?.name ?? 'Select an agent'}
        </span>
        <ChevronDown className="size-4 shrink-0 opacity-50" aria-hidden />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1.5 w-72 animate-[fade-in_160ms_ease-out] overflow-hidden rounded-xl border border-border bg-surface text-text shadow-pop">
          <Command loop label="Agents">
            <div className="flex items-center gap-2 border-b border-border px-3">
              <Search className="size-4 shrink-0 text-muted" aria-hidden />
              <Command.Input
                autoFocus
                placeholder="Search agents…"
                aria-label="Search agents"
                className="h-10 flex-1 bg-transparent text-sm outline-none placeholder:text-muted"
              />
            </div>
            <Command.List className="max-h-72 overflow-y-auto p-1.5">
              <Command.Empty className="px-2.5 py-3 text-center text-xs text-muted">
                No agent matches.
              </Command.Empty>
              <Command.Group
                heading="Agents"
                className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-1.5 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-muted"
              >
                {agents.map((a) => {
                  const current = a.slug === agent?.slug;
                  return (
                    <Command.Item
                      key={a.slug}
                      value={`${a.name} ${a.slug} ${a.description ?? ''}`}
                      onSelect={() => pick(a)}
                      title={a.description || undefined}
                      className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 text-sm aria-selected:bg-surface-muted"
                    >
                      <Bot className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{a.name}</span>
                        {a.description && (
                          <span className="line-clamp-2 text-2xs text-muted">{a.description}</span>
                        )}
                      </span>
                      <Check
                        className={cn('mt-0.5 size-3.5 shrink-0 text-primary', !current && 'opacity-0')}
                        aria-hidden
                      />
                    </Command.Item>
                  );
                })}
              </Command.Group>
            </Command.List>
          </Command>
        </div>
      )}
    </div>
  );
});
