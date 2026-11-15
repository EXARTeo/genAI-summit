// Regulation memory (reg-memory / RKS) as the frontend sees it through the backend.
// Source fields mirror mnamon/reg-memory/engine/catalog/sources.yaml.

export type SourceKind =
  | 'regulation'
  | 'amendment'
  | 'consolidated'
  | 'guideline'
  | 'faq'
  | 'code_of_practice'
  | 'standard'
  | 'national_law'
  | 'internal_policy'
  | 'other';

export type Binding = true | false | 'internal';

export interface DocVersion {
  version: number;
  fetchedAt: string;
  sha256: string;
  status: 'new' | 'changed' | 'same' | 'failed';
  bytes: number;
  diff?: { linesAdded: number; linesRemoved: number; changedSections: string[] };
}

export interface RegSource {
  id: string;
  title: string;
  kind: SourceKind;
  binding: Binding;
  status: 'final' | 'draft';
  publisher: string;
  url?: string;
  tags: string[];
  documents: number;
  versions: DocVersion[];
}

export interface DocText {
  docId: string;
  version: number;
  text: string;
}

export interface DocDiff {
  docId: string;
  from: number;
  to: number;
  unified: string;
}

export type JudgeDecision =
  | 'no_impact'
  | 'reinterpret_existing_evidence'
  | 'rerun_tests'
  | 'new_tests_needed';
export type ChangeType = 'editorial' | 'clarification' | 'scope_change' | 'new_obligation' | 'repeal';

export interface AffectedSystem {
  systemId: string;
  systemName: string;
  path: string[]; // provision → requirement → findings
  findings: string[];
  decision: JudgeDecision;
  confidence: number;
  reasoning: string;
  humanDecision?: JudgeDecision | null;
  rerunAuditId?: string | null;
  /** The system's obligations the change touched (the focused re-run's scope). */
  obligations?: string[];
  /** Old findings the judge marked `stale`. */
  staleFindings?: string[];
  counterArgument?: string | null;
  /** The audit whose findings the judge read. */
  auditId?: string | null;
}

/** The change judge's run: pending → running (started on accept) → done | failed. */
export type JudgeState = 'pending' | 'running' | 'done' | 'failed';

export interface RegChange {
  id: string;
  sourceId: string;
  title: string;
  detectedAt: string;
  changeType: ChangeType;
  provisions: string[];
  fromVersion: number;
  toVersion: number;
  candidateKbVersion: string;
  status: 'proposed' | 'accepted' | 'rejected';
  summary: string;
  affected: AffectedSystem[];
  traceId?: string;
  judge?: JudgeState;
  impactedObligations?: { obligation_id?: string; id?: string; via?: unknown; [k: string]: unknown }[];
}

/** PUT /v1/regulation/demo/mirror: "Simulate change" on the mirrored guideline page. */
export interface DemoMirrorEdit {
  find?: string;
  replace?: string;
  appendHtml?: string;
  reset?: boolean;
  check?: boolean;
}

/** POST /v1/regulation/check-now (reg-memory CheckAccepted, or the CheckRecord when waited for). */
export interface CheckNowResult {
  check_id?: string;
  status?: string;
  [k: string]: unknown;
}

/** One reg-memory provision (article, paragraph, point, annex, recital), as `/v1/regulation/provisions` returns it. */
export interface Provision {
  id: string;
  instrument: string;
  kind: string;
  path: string[];
  parent: string | null;
  title?: string | null;
  text?: string;
  content_hash?: string;
  source_doc?: string;
  chapter?: string | null;
  chapter_title?: string | null;
  label?: string;
  kb_version?: string;
  amended_by?: string[];
  valid_from?: string | null;
}

export interface ProvisionList {
  kb_version: string;
  total: number;
  items: Provision[];
}

/** A kb release (reg-memory shape, `/v1/regulation/releases`). */
export interface KbRelease {
  kb_version: string;
  status: string;
  created_at?: string;
  parent?: string | null;
}

export interface ReleaseList {
  active?: string | null;
  items: KbRelease[];
}

/** One "file" of a change's diff: a provision (diffed across kb versions) or the source document. */
export type ChangeFile =
  | { kind: 'provision'; key: string; id: string }
  | { kind: 'document'; key: string; docId: string; from: number; to: number }
  | { kind: 'opaque'; key: string; id: string };

export type DiffRowType = 'add' | 'del' | 'ctx' | 'hunk';

export interface WordPart {
  text: string;
  changed: boolean;
}

export interface DiffRow {
  type: DiffRowType;
  text: string;
  oldNo?: number;
  newNo?: number;
  /** Word-level parts, set on paired del/add lines. */
  words?: WordPart[];
}

/** A section of a source shown in the reader: a provision subtree or a heading-split text block. */
export interface ReaderSection {
  key: string;
  label: string;
  title?: string | null;
  /** Group heading in the outline (chapter, "Annexes", page range…). */
  group: string;
  groupSub?: string | null;
  /** Indented blocks to typeset, in order. */
  blocks: ReaderBlock[];
}

export interface ReaderBlock {
  id: string;
  depth: number;
  /** "1.", "(a)", "Section A"; empty for the section's own text. */
  marker: string;
  text: string;
  /** Text may be markdown (document fallback). */
  markdown?: boolean;
}
