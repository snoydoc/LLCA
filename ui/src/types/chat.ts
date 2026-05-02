// ─── Session ──────────────────────────────────────────────────────────────────
export interface Session {
  id:        string;
  title:     string;
  createdAt: string;
  updatedAt: string;
}

// ─── Badges ───────────────────────────────────────────────────────────────────
export interface TxBadge {
  txId:      string;
  files:     string[];
  status:    'committed' | 'rolled_back' | 'partial';
  timestamp: string;
}

export interface SpecBadge {
  specId:     string;
  title:      string;
  domain:     string;
  validated:  boolean;
  score:      number;
  autoStored?: boolean;  // CTX-05 : true si stocké automatiquement dans lcca_specs
  body_md?:   string;   // BUGFIX : corps Markdown propagé depuis generate_spec
  violations?: unknown[]; // BUGFIX : violations propagées depuis generate_spec
  version?:   string;   // BUGFIX : version propagée depuis generate_spec
}

// ─── Message ──────────────────────────────────────────────────────────────────
export interface Message {
  id:          string;
  role:        'user' | 'assistant' | 'system';
  content:     string;
  createdAt:   string;
  txBadge?:    TxBadge;
  specBadge?:  SpecBadge;
  isStreaming?: boolean;
  // UI-08 : outil MCP actif pendant le streaming (pour l'indicateur de phase)
  activeTool?: string;
  // UI-MODEL-01 : modèle Ollama actif au moment de la génération
  modelName?:  string;
}

// ─── Résumé spec pour ContextPanel ───────────────────────────────────────────
export interface SpecSummary {
  specId:     string;
  title:      string;
  domain:     string;
  validated:  boolean;
  score:      number;
  createdAt:  string;
  body_md?:   string;
  violations?: unknown[];
  version?:   string;
}

// ─── Enregistrement TX pour l'historique ─────────────────────────────────────
export interface TxRecord {
  txId:      string;
  files:     string[];
  status:    'committed' | 'rolled_back' | 'partial';
  timestamp: string;
}
