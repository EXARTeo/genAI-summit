import { ExternalLink, ListTree, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Button, EmptyState, Input, PageHeader, Select, Sheet, Skeleton } from '@/shared/ui';
import { PrevNext, ReaderHistory, ReaderOutline, ReaderSectionView } from '../components/SourceReader';
import { useAllProvisions, useDocText, useRegSources } from '../hooks/useRegulation';
import { KIND_LABEL, documentSections, provisionSections, sectionMatches } from '../lib/reader';
import { fallbackSource, latestVersion } from '../lib/regulation';
import type { RegSource } from '../lib/types';

type Mode = 'read' | 'full' | 'changes';

/** /regulation/sources/:sourceId — one source decomposed per article (or per heading), readable. */
export function SourceReaderPage() {
  const { sourceId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const sources = useRegSources();
  // The catalog row; if the catalog call fails (reg-memory busy), read the source by id anyway.
  const source: RegSource | undefined =
    sources.data?.find((s) => s.id === sourceId) ?? (sources.error ? fallbackSource(sourceId) : undefined);
  const provisions = useAllProvisions();
  const own = useMemo(
    () => (provisions.data?.items ?? []).filter((p) => p.source_doc === sourceId),
    [provisions.data, sourceId],
  );
  const decomposed = own.length > 0;
  const latest = source ? latestVersion(source) : 0;
  const version = Number(params.get('v')) || latest;
  const needText = provisions.isSuccess && !decomposed && (latest > 0 || !!sources.error);
  const text = useDocText(needText ? sourceId : undefined, version || undefined);
  const mode = (params.get('mode') as Mode | null) ?? 'read';
  const q = params.get('q') ?? '';
  const [draft, setDraft] = useState(q);
  const [outlineOpen, setOutlineOpen] = useState(false);

  useEffect(() => setDraft(q), [q]);

  const sections = useMemo(() => {
    if (decomposed) return provisionSections(own);
    return text.data ? documentSections(text.data.text, source?.title ?? 'Full text') : [];
  }, [decomposed, own, text.data, source?.title]);
  const visible = useMemo(() => sections.filter((s) => sectionMatches(s, q)), [sections, q]);
  const picked = params.get('p');
  const activeIdx = Math.max(
    0,
    visible.findIndex((s) => s.key === picked),
  );
  const active = visible[activeIdx];

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === '') next.delete(k);
      else next.set(k, v);
    }
    setParams(next, { replace: true });
  };
  const pick = (key: string) => {
    setOutlineOpen(false);
    if (mode === 'full') {
      document.getElementById(`sec-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    update({ p: key, mode: mode === 'changes' ? null : mode });
    document.getElementById('reader-top')?.scrollIntoView({ block: 'start' });
  };

  // Debounced search into the URL (shareable, survives reloads).
  useEffect(() => {
    const t = setTimeout(() => draft !== q && update({ q: draft || null }), 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  if (sources.isLoading) return <Skeleton className="h-96 w-full" />;
  if (!source) {
    return (
      <EmptyState title="Source not found" description={`${sourceId} is not in the regulation catalog.`} />
    );
  }

  const versions = source.versions.filter((v) => v.status !== 'failed');
  const versionOptions = Array.from(new Set(versions.map((v) => v.version)))
    .filter((v) => v > 0)
    .sort((a, b) => b - a)
    .map((v) => ({ value: String(v), label: `v${v}${v === latest ? ' (latest)' : ''}` }));
  const hasHistory = versionOptions.length > 1;
  const loading = provisions.isLoading || (needText && text.isLoading);
  const last = source.versions[source.versions.length - 1];

  const outline = (
    <ReaderOutline sections={visible} active={mode === 'full' ? undefined : active?.key} onPick={pick} />
  );

  return (
    <div id="reader-top" className="scroll-mt-4">
      <PageHeader
        breadcrumbs={[
          { label: 'Regulation', to: '/regulation' },
          { label: 'Sources', to: '/regulation?tab=sources' },
          { label: source.id },
        ]}
        eyebrow={
          <span className="font-sans uppercase tracking-wider">
            {KIND_LABEL[source.kind]} ·{' '}
            {source.binding === true ? 'Binding' : source.binding === 'internal' ? 'Internal' : 'Non-binding'}
            {source.status === 'draft' ? ' · Draft' : ''}
          </span>
        }
        title={<span className="font-heading text-2xl font-medium sm:text-3xl">{source.title}</span>}
        description={
          <>
            {source.publisher}
            {latest > 0 && ` · v${latest}`}
            {last?.fetchedAt && ` · fetched ${formatRelative(last.fetchedAt)}`}
            {decomposed
              ? ` · ${own.length} provisions (kb ${provisions.data?.kbVersion})`
              : sections.length > 0
                ? ` · ${sections.length} sections from the document text`
                : ''}
          </>
        }
        actions={
          source.url ? (
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-muted hover:text-text"
            >
              Original <ExternalLink className="size-3" />
            </a>
          ) : undefined
        }
      />

      <div className="bg-shell-card/95 sticky top-[var(--topbar-height)] z-20 -mx-4 mb-6 flex flex-wrap items-center gap-2 border-b border-border px-4 py-2 backdrop-blur lg:-mx-8 lg:px-8">
        <div className="inline-flex rounded-md bg-surface-sunken p-0.5">
          {(
            [
              ['read', decomposed ? 'Articles' : 'Sections'],
              ['full', 'Full text'],
              ...(hasHistory ? ([['changes', 'History']] as const) : []),
            ] as const
          ).map(([m, label]) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => update({ mode: m === 'read' ? null : m })}
              className={cn(
                'rounded px-2.5 py-1 text-xs font-medium',
                mode === m ? 'bg-surface text-text shadow-card' : 'text-muted hover:text-text',
              )}
            >
              {label}
            </button>
          ))}
        </div>
        {mode !== 'changes' && (
          <div className="order-last w-full sm:order-none sm:w-auto sm:min-w-0 sm:max-w-xs sm:flex-1">
            <Input
              leftIcon={<Search />}
              placeholder={decomposed ? 'Search articles' : 'Search this source'}
              aria-label="Search this source"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
          </div>
        )}
        {q && mode !== 'changes' && (
          <span className="text-2xs text-muted">
            {visible.length} of {sections.length} match
          </span>
        )}
        <span className="ml-auto flex items-center gap-2">
          {(!decomposed || mode === 'changes') && versionOptions.length > 0 && (
            <Select
              className="h-8 w-36 text-xs"
              aria-label="Version"
              value={String(version)}
              onValueChange={(v) => update({ v: Number(v) === latest ? null : v })}
              options={versionOptions}
            />
          )}
          {mode !== 'changes' && (
            <Button
              variant="secondary"
              size="sm"
              className="lg:hidden"
              leftIcon={<ListTree />}
              onClick={() => setOutlineOpen(true)}
            >
              Contents
            </Button>
          )}
        </span>
      </div>

      {mode === 'changes' ? (
        <ReaderHistory
          docId={source.id}
          versions={source.versions}
          version={version}
          onVersion={(v) => update({ v: v === latest ? null : String(v) })}
        />
      ) : loading ? (
        <div className="grid gap-8 lg:grid-cols-[260px_minmax(0,1fr)]">
          <Skeleton className="hidden h-96 lg:block" />
          <div className="space-y-3">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-64" />
          </div>
        </div>
      ) : sections.length === 0 ? (
        <EmptyState
          title="No text yet"
          description={
            latest > 0
              ? 'reg-memory has no extracted text for this source.'
              : 'This source has not been fetched yet; run Check now in the change inbox.'
          }
        />
      ) : (
        <div className="grid gap-8 lg:grid-cols-[260px_minmax(0,1fr)] xl:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="hidden lg:block">
            <div className="sticky top-[calc(var(--topbar-height)+4rem)] max-h-[calc(100vh-var(--topbar-height)-6rem)] overflow-y-auto pb-8 pr-1">
              {outline}
            </div>
          </aside>
          <Sheet
            open={outlineOpen}
            onOpenChange={setOutlineOpen}
            side="left"
            title="Contents"
            width="w-[min(22rem,90vw)]"
          >
            {outline}
          </Sheet>
          <div className="min-w-0">
            <div className="mx-auto max-w-[72ch]">
              {visible.length === 0 ? (
                <EmptyState compact title="Nothing matches" description={`No section contains “${q}”.`} />
              ) : mode === 'full' ? (
                <div className="space-y-14">
                  {visible.map((s) => (
                    <ReaderSectionView key={s.key} s={s} q={q} compact />
                  ))}
                </div>
              ) : (
                active && (
                  <>
                    <ReaderSectionView s={active} q={q} />
                    <PrevNext prev={visible[activeIdx - 1]} next={visible[activeIdx + 1]} onPick={pick} />
                  </>
                )
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
