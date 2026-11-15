import { ChevronDown, ScanSearch } from 'lucide-react';
import { useState } from 'react';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, Tooltip } from '@/shared/ui';
import { pct } from '../../lib/classification';
import {
  collapseGroups,
  groupClaims,
  irisSummaryOf,
  irisSupport,
  irisVerdict,
  VERDICT_TONE,
  type IrisVerdict,
} from '../../lib/iris';
import type { ClassificationResult, IrisClaim } from '../../lib/types';

/** Collapsed view: every disagreement + this many other claims. */
const COLLAPSED = 6;

const yesNo = (b: boolean) => (b ? 'yes' : 'no');

const VERDICT_WORDS: Record<IrisVerdict, string> = {
  agree: 'agrees',
  disagree: 'disagrees',
  strong: 'strongly disagrees',
  none: 'did not run',
};

/** "Iris agrees with the agent (93%): <statement>" for screen readers. */
function chipLabel(c: IrisClaim): string {
  const v = irisVerdict(c);
  if (v === 'none') return `Iris did not run on: ${c.statement}`;
  return `Iris ${VERDICT_WORDS[v]} with the agent (${pct(irisSupport(c))} support): ${c.statement}`;
}

function ChipTip({ c }: { c: IrisClaim }) {
  return (
    <span className="block space-y-1 font-normal">
      <span className="block leading-5">“{c.statement}”</span>
      <span className="num block opacity-75">
        {c.iris === null
          ? `Agent: ${yesNo(c.agent)} · Iris did not run`
          : `Agent: ${yesNo(c.agent)} · Iris P(yes) = ${c.iris.toFixed(2)}`}
      </span>
    </span>
  );
}

/** "Iris ✓ 93%" / "Iris ✗ 12%" / "Iris —": Iris's support for the agent's answer on one claim. */
export function IrisChip({ claim, className }: { claim: IrisClaim | undefined; className?: string }) {
  if (!claim) return null;
  const v = irisVerdict(claim);
  const text = v === 'none' ? 'Iris —' : `Iris ${v === 'agree' ? '✓' : '✗'} ${pct(irisSupport(claim))}`;
  return (
    <Tooltip content={<ChipTip c={claim} />}>
      <span
        className={cn('inline-flex shrink-0 cursor-help rounded-md', className)}
        role="img"
        aria-label={chipLabel(claim)}
        tabIndex={0}
      >
        <Badge tone={VERDICT_TONE[v]} className="num" aria-hidden>
          {text}
        </Badge>
      </span>
    </Tooltip>
  );
}

/** "N of M claims agree", for the summary's Independent check cell. */
export function IrisClaimsLine({ r, onShow }: { r: ClassificationResult; onShow?: () => void }) {
  const s = irisSummaryOf(r.iris_claims, r.iris_summary);
  if (!s) return null;
  const strong = (r.iris_claims ?? []).some((c) => irisVerdict(c) === 'strong');
  return (
    <span className="flex w-full flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs text-muted">
      <span className={cn('num', s.disagree > 0 && (strong ? 'text-danger' : 'text-warning'))}>
        {s.agree} of {s.checked} claims agree
      </span>
      {onShow && (
        <button
          type="button"
          onClick={onShow}
          className="rounded-sm font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          See the checks
        </button>
      )}
    </span>
  );
}

function ProbBar({ c }: { c: IrisClaim }) {
  const v = irisVerdict(c);
  if (c.iris === null) return <span className="text-xs text-muted">Not run</span>;
  return (
    <span className="flex w-full items-center gap-2 sm:w-32" title={`Iris P(yes) = ${c.iris.toFixed(2)}`}>
      <span
        className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-surface-muted"
        role="meter"
        aria-label="Iris P(yes)"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(c.iris * 100)}
      >
        <span
          className={cn(
            'absolute inset-y-0 left-0 rounded-full',
            v === 'agree' && 'bg-success',
            v === 'disagree' && 'bg-warning',
            v === 'strong' && 'bg-danger',
          )}
          style={{ width: `${Math.round(c.iris * 100)}%` }}
        />
        <span className="absolute inset-y-0 left-1/2 w-px bg-border" aria-hidden />
      </span>
      <span className="num w-9 text-right text-xs text-muted">{pct(c.iris)}</span>
    </span>
  );
}

function ClaimRow({ c }: { c: IrisClaim }) {
  const v = irisVerdict(c);
  return (
    <li
      className={cn(
        'flex flex-col gap-2 py-2.5 text-sm sm:flex-row sm:items-center sm:gap-4',
        v === 'strong' && '-mx-2 rounded-md border-l-2 border-danger bg-danger/[0.05] px-2',
        v === 'disagree' && '-mx-2 rounded-md border-l-2 border-warning/60 px-2',
      )}
    >
      <p className="min-w-0 flex-1 leading-5">{c.statement}</p>
      <div className="flex shrink-0 items-center gap-3">
        <span className="w-14 text-xs">
          <span className="text-muted">Agent </span>
          <span className="font-medium">{c.agent ? 'Yes' : 'No'}</span>
        </span>
        <span className="min-w-0 flex-1 sm:flex-none">
          <ProbBar c={c} />
        </span>
        <span className="flex w-24 justify-end">
          <IrisChip claim={c} />
        </span>
      </div>
    </li>
  );
}

/** Every claim and assumption put to Iris, grouped by article, disagreements first. */
export function IrisChecks({ r, id }: { r: ClassificationResult; id?: string }) {
  const claims = r.iris_claims ?? [];
  const [all, setAll] = useState(false);
  if (!claims.length) return null;
  const s = irisSummaryOf(claims, r.iris_summary);
  const groups = groupClaims(claims);
  const strong = claims.filter((c) => irisVerdict(c) === 'strong');
  const rest = groups
    .map((g) => ({ ...g, claims: g.claims.filter((c) => irisVerdict(c) !== 'strong') }))
    .filter((g) => g.claims.length > 0);
  const collapsed = collapseGroups(rest, COLLAPSED);
  const shown = all ? rest : collapsed.groups;

  return (
    <section
      id={id}
      tabIndex={-1}
      aria-labelledby={id ? `${id}-title` : undefined}
      className="min-w-0 scroll-mt-20 rounded-lg border border-border p-4 focus:outline-none"
    >
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
        <h4
          id={id ? `${id}-title` : undefined}
          className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-muted [&_svg]:size-3.5"
        >
          <ScanSearch />
          Independent checks (Oumi Iris)
        </h4>
        {s && (
          <span className="flex flex-wrap gap-1.5">
            <Badge tone="success" className="num">
              {s.agree} agree
            </Badge>
            {s.disagree > 0 && (
              <Badge tone={strong.length ? 'danger' : 'warning'} className="num">
                {s.disagree} disagree
              </Badge>
            )}
          </span>
        )}
      </div>
      <p className="mb-3 max-w-3xl text-xs leading-5 text-muted">
        Each article-level claim and assumption of the proposal, asked of Iris as a yes/no question. The bar
        is Iris’s probability that the statement is true; the chip is its support for the agent’s answer.
      </p>

      {strong.length > 0 && (
        <div className="mb-3">
          <h5 className="text-xs font-medium text-danger">Strong disagreements</h5>
          <ul>
            {strong.map((c) => (
              <ClaimRow key={c.key} c={c} />
            ))}
          </ul>
        </div>
      )}

      <div className="space-y-3">
        {shown.map((g) => (
          <div key={g.group}>
            <h5 className="text-xs font-medium text-muted">{g.label}</h5>
            <ul className="divide-y divide-border">
              {g.claims.map((c) => (
                <ClaimRow key={c.key} c={c} />
              ))}
            </ul>
          </div>
        ))}
      </div>

      {collapsed.hidden > 0 && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-2"
          aria-expanded={all}
          onClick={() => setAll((v) => !v)}
          rightIcon={<ChevronDown className={cn('transition-transform', all && 'rotate-180')} />}
        >
          {all ? 'Show fewer' : `Show all ${claims.length}`}
        </Button>
      )}
    </section>
  );
}
