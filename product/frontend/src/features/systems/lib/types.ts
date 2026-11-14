/** Mirrors product/backend/schema/systems.py (SystemOut, FileOut, FileContentOut, FileEventOut). */

export type RiskClass = 'prohibited' | 'high_risk' | 'limited_risk' | 'minimal_risk' | string;

/** The system card fields we read from `SystemOut.data` (seeded from system-card.yaml). */
export interface SystemCard {
  card_version?: number;
  organisation?: string;
  provider?: string;
  role?: 'provider' | 'deployer' | string;
  risk_class?: RiskClass;
  annex_basis?: string;
  intended_purpose?: string;
  deployment?: { status?: string; countries?: string[]; users?: string; since?: string };
  affected_persons?: string;
  human_oversight?: string;
  protected_attributes?: string[];
  known_proxies?: string[];
  components?: string[];
  declared_metrics?: Record<string, string>;
  org_thresholds?: Record<string, string>;
  /** UI summary of the most recent audit (filled by the backend or mocks). */
  last_audit?: {
    id: string;
    status: string;
    at: string;
    findings?: { gaps: number; supports: number; inconclusive: number };
  } | null;
  [key: string]: unknown;
}

export interface System {
  id: string;
  name: string;
  status: string;
  data: SystemCard;
  createdAt: string;
  updatedAt: string;
}

export interface WorkspaceFile {
  namespace: string;
  path: string;
  version: number;
  contentType: string;
  size: number;
  sha256: string;
  createdBy: string;
  isCurrent: boolean;
  data: Record<string, unknown>;
  createdAt: string;
}

export interface WorkspaceFileContent extends WorkspaceFile {
  text: string | null;
  dataB64: string | null;
}

export interface FileWriteResult {
  file: WorkspaceFile;
  changed: boolean;
}

export interface FileEvent {
  id: number;
  namespace: string;
  path: string;
  version: number | null;
  action: string;
  actor: string;
  reason: string | null;
  auditId: string | null;
  runId: string | null;
  traceId: string | null;
  data: Record<string, unknown>;
  at: string;
}

/** The parts of plugin.yaml the UI shows (docs/architecture/agent-context.md § 3). */
export interface PluginCard {
  id: string;
  name: string;
  system: string;
  placement: {
    kind: string;
    position?: string;
    upstream?: string[];
    downstream?: string[];
    pipeline_summary?: string;
  };
  access: { type: string; uri?: string; url?: string; environment?: string; limits?: Record<string, number> };
  io?: { output?: Record<string, unknown> };
  expected_behaviour: { task: string; must?: string[]; must_not?: string[]; known_limitations?: string[] };
}

export interface BusinessRule {
  id: string;
  /** Plugin folder the rule belongs to, e.g. `cv-ranker`. */
  plugin: string;
  title: string;
  kind: 'hard' | 'soft' | 'policy';
  text: string;
}
