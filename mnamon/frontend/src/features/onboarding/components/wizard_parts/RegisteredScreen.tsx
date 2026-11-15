import { motion } from 'framer-motion';
import { ArrowRight, Plus, Puzzle, Scale } from 'lucide-react';
import { Link } from 'react-router-dom';
import { systemRoutes } from '@/features/systems/lib/routes';
import { Button, Card } from '@/shared/ui';

/** After registration: classify the risk (PM), then hand over to the AI engineer (Plugins tab). */
export function RegisteredScreen({
  systemId,
  name,
  onAnother,
}: {
  systemId: string;
  name: string;
  onAnother: () => void;
}) {
  return (
    <Card className="mx-auto max-w-2xl p-6 sm:p-8">
      <div className="flex flex-col items-center text-center">
        <motion.span
          className="grid size-12 place-items-center rounded-full bg-success text-success-foreground"
          initial={{ scale: 0.7, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
          aria-hidden
        >
          <svg viewBox="0 0 24 24" className="size-6" fill="none">
            <motion.path
              d="M5 12.5l4.5 4.5L19 7.5"
              stroke="currentColor"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.35, delay: 0.12 }}
            />
          </svg>
        </motion.span>
        <h2 className="mt-4 text-lg font-semibold tracking-tight" role="status">
          {name} is registered
        </h2>
        <p className="mt-1 text-sm text-muted">
          <span className="font-mono">{systemId}</span> is a draft with its system card and documents. Two
          steps remain.
        </p>
      </div>

      <ol className="mt-6 space-y-3">
        <li className="flex flex-col gap-3 rounded-lg border border-primary/30 bg-primary/[0.04] p-4 sm:flex-row sm:items-center">
          <span className="grid size-8 shrink-0 place-items-center rounded-md bg-primary/10 text-primary [&_svg]:size-4">
            <Scale />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">1 · Classify its risk</div>
            <p className="text-xs text-muted">
              The agent proposes the AI Act class; the AI Officer approves it.
            </p>
          </div>
          <Button asChild size="sm">
            <Link to={systemRoutes.detail(systemId)}>
              Open and classify <ArrowRight />
            </Link>
          </Button>
        </li>
        <li className="flex flex-col gap-3 rounded-lg border border-border p-4 sm:flex-row sm:items-center">
          <span className="grid size-8 shrink-0 place-items-center rounded-md bg-surface-muted text-muted [&_svg]:size-4">
            <Puzzle />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">2 · Hand over to the AI engineer: build the pipeline</div>
            <p className="text-xs text-muted">
              The engineer adds the models and the steps around them in the Plugins tab, then runs audits.
            </p>
          </div>
          <Button asChild size="sm" variant="secondary">
            <Link to={systemRoutes.detail(systemId, 'plugins')}>
              Plugins tab <ArrowRight />
            </Link>
          </Button>
        </li>
      </ol>

      <div className="mt-6 flex justify-center">
        <Button variant="ghost" size="sm" leftIcon={<Plus />} onClick={onAnother}>
          Register another system
        </Button>
      </div>
    </Card>
  );
}
