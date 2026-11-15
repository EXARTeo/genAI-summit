// Port of magenticx `plan/PlanButton.tsx`; the plan icon is lucide `ListChecks`, the glow a `live-dot`.
import * as React from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { ListChecks } from 'lucide-react';
import { Tooltip } from '@/shared/ui';
import { planProgressLabel, type ConversationPlans } from '../../lib/conversationPlans';
import { PlanPanel } from './PlanPanel';

type PlanButtonProps = {
  plans: ConversationPlans;
  agentName: string;
  /** False on an empty conversation; the button also waits for a plan. */
  visible: boolean;
};

/**
 * The composer's plan button, right of the agent map's: the plan icon alone,
 * a soft glow behind it while a step is being worked on, and the panel with
 * the plan. The progress is in its label and the panel, not on the button.
 * Shown once the conversation has a plan on the branch the user sees.
 */
export function PlanButton({ plans, agentName, visible }: PlanButtonProps) {
  const [open, setOpen] = React.useState(false);
  const buttonRef = React.useRef<HTMLButtonElement>(null);
  const panelId = React.useId();
  const reduceMotion = useReducedMotion();
  const current = plans.current;
  const shown = visible && current !== null;
  const working = Boolean(current && current.activeIndex >= 0);
  const label = current ? `Plan · ${planProgressLabel(current)}` : 'Plan';

  React.useEffect(() => {
    if (!shown) setOpen(false);
  }, [shown]);

  return (
    <>
      <AnimatePresence initial={false}>
        {shown && current ? (
          <motion.span
            key="plan-button"
            className="inline-flex"
            initial={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.6 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={reduceMotion ? { opacity: 0 } : { opacity: 0, scale: 0.6 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
          >
            <Tooltip content={label}>
              <button
                ref={buttonRef}
                type="button"
                aria-label={label}
                aria-haspopup="dialog"
                aria-expanded={open}
                aria-controls={open ? panelId : undefined}
                data-active={working}
                onClick={() => setOpen(true)}
                className="group/plan relative grid size-9 shrink-0 cursor-pointer place-items-center rounded-full text-muted transition-[background-color,color,transform] duration-150 hover:bg-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 active:scale-[0.94] data-[active=true]:text-primary motion-reduce:active:scale-100"
              >
                <ListChecks
                  className="size-5 transition-transform duration-300 ease-out motion-safe:supports-[hover:hover]:group-hover/plan:scale-110"
                  aria-hidden
                />
                {working ? <span aria-hidden className="live-dot absolute right-1 top-1" /> : null}
              </button>
            </Tooltip>
          </motion.span>
        ) : null}
      </AnimatePresence>
      <PlanPanel
        open={open && shown}
        onOpenChange={setOpen}
        plans={plans}
        agentName={agentName}
        anchorRef={buttonRef}
        id={panelId}
      />
    </>
  );
}
