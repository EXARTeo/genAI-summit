import * as React from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { cn } from '@/shared/lib/utils';
import { AgentMapIcon, Tooltip } from '@/shared/ui';
import { useAgentMapNav } from '../../hooks/useAgentMapNav';
import type { AgentMap } from '../../lib/agentMap';
import { AgentMapPanel } from './AgentMapPanel';

type AgentMapButtonProps = {
  map: AgentMap;
  agentName: string;
  /** False on an empty conversation: there is nothing to map yet. */
  visible: boolean;
};

/**
 * Port of magenticx `agent_map/AgentMapButton.tsx`. The composer's agent-map button, right of the context ring: the sub-agents
 * the visible branch used, counted on a badge (lit while one works), and the
 * panel that maps them. Shown only once a sub-agent has run on this branch,
 * like the plan button waits for a plan.
 */
export function AgentMapButton({ map, agentName, visible }: AgentMapButtonProps) {
  const [open, setOpen] = React.useState(false);
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const reduceMotion = useReducedMotion();
  const count = map.subagentCount;
  const working = map.runningCount > 0;
  const shown = visible && count > 0;
  const label = `Agent map, ${count} sub-agent${count === 1 ? '' : 's'}${working ? `, ${map.runningCount} working` : ''}`;

  React.useEffect(() => {
    if (!shown) setOpen(false);
  }, [shown]);

  // A task marker in the chat asked to open its task here.
  // Only requests made while this button is mounted: an old one never reopens the panel.
  const request = useAgentMapNav((s) => s.request);
  const [since] = React.useState(() => useAgentMapNav.getState().request?.nonce ?? 0);
  const fresh = request && request.nonce > since ? request : null;
  React.useEffect(() => {
    if (fresh && shown) setOpen(true);
  }, [fresh, shown]);

  return (
    <>
      <AnimatePresence initial={false}>
        {shown ? (
          <motion.span
            key="agent-map-button"
            className="inline-flex"
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.6 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <Tooltip content="Agent map">
              <button
                ref={buttonRef}
                type="button"
                aria-label={label}
                aria-haspopup="dialog"
                aria-expanded={open}
                onClick={() => setOpen(true)}
                className="group/map relative grid size-9 shrink-0 cursor-pointer place-items-center rounded-full text-muted transition-[background-color,color,transform] duration-150 hover:bg-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 active:scale-[0.94] motion-reduce:active:scale-100"
              >
                <AgentMapIcon className="transition-transform duration-300 ease-out motion-safe:supports-[hover:hover]:group-hover/map:scale-110" />
                <AnimatePresence initial={false}>
                  {count ? (
                    <motion.span
                      key={count}
                      aria-hidden
                      initial={reduceMotion ? { opacity: 0 } : { scale: 0.4, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ opacity: 0, transition: { duration: 0.1 } }}
                      transition={{ type: 'spring', stiffness: 520, damping: 26 }}
                      className={cn(
                        'pointer-events-none absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold tabular-nums leading-none ring-2 ring-surface',
                        working ? 'bg-primary text-primary-foreground' : 'bg-foreground text-background',
                      )}
                    >
                      {count > 99 ? '99+' : count}
                    </motion.span>
                  ) : null}
                </AnimatePresence>
              </button>
            </Tooltip>
          </motion.span>
        ) : null}
      </AnimatePresence>
      <AgentMapPanel
        open={open && shown}
        onOpenChange={setOpen}
        map={map}
        agentName={agentName}
        anchorRef={buttonRef}
        request={fresh}
      />
    </>
  );
}
