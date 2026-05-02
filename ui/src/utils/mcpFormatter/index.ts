// mcpFormatter/index.ts — Barrel re-export rétrocompat (REFACTO-UI-01)
// Garantit que `from '../utils/mcpFormatter'` fonctionne sans modification
// dans tous les composants existants (ChatPanel, etc.).

export { formatGenerateSpec, formatValidateSpec }   from './spec';
export { formatMemorySearch, formatSandboxRun, formatEditBatch } from './memory';
export {
  formatLlmChat,
  formatWebSearch,
  formatEvaluateQuality,
  formatProjectSearch,
  formatAnalyzeError,
} from './system';

// Re-export du dispatcher principal depuis mcpFormatter.ts (niveau parent)
// Les imports `from '../utils/mcpFormatter'` sans chemin complet passent
// par ce barrel — le dispatcher reste dans le fichier d'origine.
export { formatMcpResponse } from '../mcpFormatter';
