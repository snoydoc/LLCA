// ─── Résultats bruts des tools MCP ───────────────────────────────────────────

export interface McpRawResponse {
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}

export class McpError extends Error {
  constructor(public code: number, message: string) {
    super(message);
    this.name = 'McpError';
  }
}

// ─── Statut du serveur ────────────────────────────────────────────────────────
export type McpStatusValue = 'connecting' | 'connected' | 'disconnected' | 'error';

export interface McpStatus {
  status: McpStatusValue;
  llmStatus?: 'available' | 'unavailable' | 'unknown';
}

// ─── Résultats typés par tool ─────────────────────────────────────────────────

export interface ViolationEntry {
  rule:           string;
  severity:       'blocking' | 'warning' | 'info';
  fix_suggestion: string;
}

export interface GenerateSpecResult {
  spec_id:          string;
  title:            string;
  domain:           string;
  version:          string;
  score:            number;
  validated:        boolean;
  complexity_score: number;
  violations:       ViolationEntry[];
  body_md?:         string;
  auto_stored?:     boolean;   // CTX-04 : true si stockage auto lcca_specs réussi
}

export interface ValidateSpecResult {
  spec_id:          string;
  valid:            boolean;
  score:            number;
  blocking:         number;
  violations:       ViolationEntry[];
  validation_notes: string;
  body_md?:         string;
}

export interface MemoryEntry {
  id:       string;
  content:  string;
  metadata: Record<string, unknown>;
  distance?: number;
}

export interface MemorySearchResult {
  solutions?: MemoryEntry[];
  failures?:  MemoryEntry[];
  context?:   MemoryEntry[];
  specs?:     MemoryEntry[];
}

export interface EditBatchResult {
  success:  boolean;
  tx_id?:   string;
  applied:  number;
  errors:   string[];
}

export interface SandboxResult {
  success:   boolean;
  exit_code: number;
  stdout:    string;
  stderr:    string;
  duration?: number;
}

export interface StreamToken {
  token:   string;
  msgId:   string;
  isFinal: boolean;
}

export interface McpEvent {
  type:    'status' | 'log' | 'error';
  payload: unknown;
}
