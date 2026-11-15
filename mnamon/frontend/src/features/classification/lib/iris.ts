// Oumi Iris's verdict on every article-level claim and assumption of a classification
// (`result.iris_claims` / `result.iris_summary`; both missing on older runs).
import type { BadgeTone } from '@/shared/ui';
import type { IrisClaim, IrisClaimGroup, IrisSummary } from './types';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const bool = (v: unknown): boolean | null => (typeof v === 'boolean' ? v : null);

/** Display order and headings of the claim groups. */
export const IRIS_GROUPS: { group: IrisClaimGroup; label: string }[] = [
  { group: 'annex_iii', label: 'Annex III areas' },
  { group: 'art5', label: 'Art. 5 practices' },
  { group: 'art6_3', label: 'Art. 6(3) derogation' },
  { group: 'art50', label: 'Art. 50 transparency' },
  { group: 'role', label: 'Role' },
  { group: 'annex_i', label: 'Annex I' },
  { group: 'assumption', label: 'Assumptions' },
  { group: 'counter', label: 'Counter-arguments' },
];

/** Keep only well-formed claims (the field is new; older runs have none). */
export function toIrisClaims(raw: unknown): IrisClaim[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter(isObj).flatMap((c) => {
    const key = typeof c.key === 'string' ? c.key : null;
    const statement = typeof c.statement === 'string' ? c.statement : null;
    if (!key || !statement) return [];
    const group = (typeof c.group === 'string' ? c.group : key.split(':')[0]) as IrisClaimGroup;
    return [
      {
        key,
        group,
        provision_id: typeof c.provision_id === 'string' ? c.provision_id : null,
        statement,
        agent: c.agent === true,
        iris: num(c.iris),
        agrees: bool(c.agrees),
        strong_disagreement: c.strong_disagreement === true,
      },
    ];
  });
}

/**
 * The claim behind one row of the card: in `group`, the one whose key is `ref`, `<group>:<ref>`,
 * or whose provision id is `ref` (`irisFor(c, 'AIA.ANNEX_III.4.a', 'annex_iii')`,
 * `irisFor(c, 'condition', 'art6_3')`, `irisFor(c, 'role', 'role')`, `irisFor(c, '1', 'counter')`).
 */
export function irisFor(
  claims: IrisClaim[] | null | undefined,
  ref: string,
  group: IrisClaimGroup,
): IrisClaim | undefined {
  if (!claims?.length) return undefined;
  const inGroup = claims.filter((c) => c.group === group);
  return (
    inGroup.find((c) => c.key === ref || c.key === `${group}:${ref}`) ??
    inGroup.find((c) => c.provision_id === ref)
  );
}

export type IrisVerdict = 'agree' | 'disagree' | 'strong' | 'none';

export function irisVerdict(c: IrisClaim): IrisVerdict {
  if (c.iris === null || c.agrees === null) return 'none';
  if (c.agrees) return 'agree';
  return c.strong_disagreement ? 'strong' : 'disagree';
}

export const VERDICT_TONE: Record<IrisVerdict, BadgeTone> = {
  agree: 'success',
  disagree: 'warning',
  strong: 'danger',
  none: 'neutral',
};

/** How much Iris backs the agent's answer: P(yes) when the agent says yes, else P(no). */
export function irisSupport(c: IrisClaim): number | null {
  if (c.iris === null) return null;
  return c.agent ? c.iris : 1 - c.iris;
}

const RANK: Record<IrisVerdict, number> = { strong: 0, disagree: 1, agree: 2, none: 3 };

export interface ClaimGroup {
  group: IrisClaimGroup;
  label: string;
  claims: IrisClaim[];
}

/**
 * Claims in the display order of their groups, disagreements first inside a group (stable
 * otherwise). Unknown groups go last under their raw name.
 */
export function groupClaims(claims: IrisClaim[]): ClaimGroup[] {
  const known = new Set(IRIS_GROUPS.map((g) => g.group));
  const extra = [...new Set(claims.map((c) => c.group).filter((g) => !known.has(g)))];
  const order = [...IRIS_GROUPS, ...extra.map((g) => ({ group: g, label: g.replace(/_/g, ' ') }))];
  return order
    .map(({ group, label }) => ({
      group,
      label,
      claims: claims
        .map((c, i) => ({ c, i }))
        .filter(({ c }) => c.group === group)
        .sort((a, b) => RANK[irisVerdict(a.c)] - RANK[irisVerdict(b.c)] || a.i - b.i)
        .map(({ c }) => c),
    }))
    .filter((g) => g.claims.length > 0);
}

/**
 * The collapsed view: every disagreement plus the first `limit` other claims (in group order);
 * `hidden` is how many are left out.
 */
export function collapseGroups(
  groups: ClaimGroup[],
  limit: number,
): { groups: ClaimGroup[]; hidden: number } {
  let left = limit;
  let hidden = 0;
  const out = groups
    .map((g) => ({
      ...g,
      claims: g.claims.filter((c) => {
        const v = irisVerdict(c);
        if (v === 'strong' || v === 'disagree') return true;
        if (left > 0) {
          left--;
          return true;
        }
        hidden++;
        return false;
      }),
    }))
    .filter((g) => g.claims.length > 0);
  return { groups: out, hidden };
}

/** `iris_summary` when sent, else counted from the claims; null when there are no claims. */
export function irisSummaryOf(
  claims: IrisClaim[] | null | undefined,
  summary: IrisSummary | null | undefined,
): IrisSummary | null {
  if (summary && typeof summary.checked === 'number' && summary.checked > 0) return summary;
  if (!claims?.length) return null;
  const v = claims.map(irisVerdict);
  const agree = v.filter((x) => x === 'agree').length;
  const disagree = v.filter((x) => x === 'disagree' || x === 'strong').length;
  return { checked: agree + disagree, agree, disagree };
}
