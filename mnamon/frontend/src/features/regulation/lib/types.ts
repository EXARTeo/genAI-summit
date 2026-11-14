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
}

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
}
