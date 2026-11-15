import { MessageSquarePlus, Send } from 'lucide-react';
import { useState } from 'react';
import { getClientId } from '@/shared/lib/client-id';
import { formatRelative } from '@/shared/lib/format';
import { Badge, Button, Select, Textarea, toast } from '@/shared/ui';
import { useAnnotateFinding } from '../../hooks/useAudits';
import { ANNOTATION_KINDS, annotationKind, type Annotation, type AnnotationKind } from '../../lib/findings';

/** Who wrote it: `client:<uuid>` → "you" for this browser, else a short id. */
function actorLabel(actor: string): string {
  const id = actor.replace(/^client:/, '');
  return id === getClientId() ? 'You' : actor.startsWith('agent') ? actor : `Reviewer ${id.slice(0, 6)}`;
}

/**
 * The human notes on one sealed finding, oldest first, and a small form to add one.
 * The verdict never changes: contest, accept the risk, plan a remediation, or comment.
 */
export function AnnotationThread({
  auditId,
  findingId,
  annotations,
  canAnnotate,
}: {
  auditId: string;
  findingId: string;
  annotations: Annotation[];
  /** Legacy (artifact) findings cannot be annotated: they are not sealed rows. */
  canAnnotate: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<AnnotationKind>('comment');
  const [body, setBody] = useState('');
  const annotate = useAnnotateFinding(auditId);

  const submit = () => {
    const text = body.trim();
    if (!text) return;
    annotate.mutate(
      { findingId, body: { kind, body: text } },
      {
        onSuccess: () => {
          setBody('');
          setOpen(false);
          toast.success('Annotation added');
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not add the annotation'),
      },
    );
  };

  return (
    <div>
      {annotations.length > 0 ? (
        <ol className="space-y-2">
          {annotations.map((a) => {
            const k = annotationKind(a.kind);
            return (
              <li
                key={a.id}
                className="rounded-lg border border-border bg-surface-muted/30 px-3 py-2 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <Badge tone={k.tone}>{k.label}</Badge>
                  <span className="font-medium text-text/80">{actorLabel(a.actor)}</span>
                  <span>· {formatRelative(a.created_at)}</span>
                </div>
                <p className="mt-1 whitespace-pre-wrap break-words">{a.body}</p>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-xs text-muted">No annotations yet.</p>
      )}
      {canAnnotate &&
        (open ? (
          <div className="mt-3 space-y-2 rounded-lg border border-border p-3 print:hidden">
            <div className="flex flex-wrap items-center gap-2">
              <Select
                aria-label="Annotation kind"
                value={kind}
                onValueChange={(v) => setKind(v as AnnotationKind)}
                options={ANNOTATION_KINDS.map((k) => ({ value: k.value, label: k.label }))}
                className="w-48"
              />
              <span className="text-xs text-muted">The verdict stays sealed; your note sits next to it.</span>
            </div>
            <Textarea
              rows={3}
              value={body}
              maxLength={5000}
              placeholder="Why, and what should happen next"
              onChange={(e) => setBody(e.target.value)}
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button
                size="sm"
                leftIcon={<Send />}
                onClick={submit}
                loading={annotate.isPending}
                disabled={!body.trim()}
              >
                Add note
              </Button>
            </div>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="mt-2 print:hidden"
            leftIcon={<MessageSquarePlus />}
            onClick={() => setOpen(true)}
          >
            Annotate
          </Button>
        ))}
    </div>
  );
}
