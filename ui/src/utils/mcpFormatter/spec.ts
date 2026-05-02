// mcpFormatter/spec.ts — Formatage réponses MCP spec-related (REFACTO-UI-01)
// BUGFIX [object Object] : re-export depuis mcpFormatter.ts (source de vérité unique)
// Ce fichier délègue à mcpFormatter.ts pour éviter la duplication du bugfix.
export { formatGenerateSpec, formatValidateSpec } from '../mcpFormatter';
