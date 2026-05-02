import { useCallback } from 'react';
import { McpError } from '../types/mcp';
import type {
  GenerateSpecResult,
  ValidateSpecResult,
  EditBatchResult,
  SandboxResult,
  MemorySearchResult,
} from '../types/mcp';

// ─── useMcp ───────────────────────────────────────────────────────────────────
export function useMcp() {
  const call = useCallback(async <T>(
    tool: string,
    args: Record<string, unknown>
  ): Promise<T> => {
    // Guard : window.lcca peut ne pas exister si le preload n'est pas chargé
    // (ex : renderer ouvert sans Electron, ou bridge pas encore prêt)
    const lcca = (window as any).lcca;
    if (!lcca?.mcpCall) {
      throw new McpError(-32000, 'McpServer non connecté — lancez le serveur Python (venv activé)');
    }

    let raw: any;
    try {
      raw = await lcca.mcpCall(tool, args);
    } catch (err: any) {
      throw new McpError(-32000, err?.message ?? 'Erreur réseau McpBridge');
    }

    if (raw?.error) {
      throw new McpError(raw.error.code ?? -32000, raw.error.message ?? 'Erreur MCP');
    }

    const text = raw?.content?.[0]?.text;
    if (text === undefined || text === null) {
      throw new McpError(-32603, `Réponse MCP vide pour l'outil "${tool}"`);
    }

    try {
      return JSON.parse(text) as T;
    } catch {
      throw new McpError(-32700, `Réponse non-JSON de "${tool}" : ${String(text).slice(0, 120)}`);
    }
  }, []);

  return {
    generateSpec: (intent: string, domain: string) =>
      call<GenerateSpecResult>('generate_spec', { intent, domain }),

    validateSpec: (specId?: string, bodyMd?: string) =>
      call<ValidateSpecResult>('validate_spec', {
        ...(specId ? { spec_id: specId } : {}),
        ...(bodyMd ? { body_md: bodyMd } : {}),
      }),

    editBatch: (files: unknown[]) =>
      call<EditBatchResult>('edit_batch', { files }),

    sandboxRun: (code: string) =>
      call<SandboxResult>('sandbox_run', { code }),

    evaluateQuality: (code: string) =>
      call<Record<string, unknown>>('evaluate_quality', { code }),

    memorySearch: (query: string, n = 5) =>
      call<MemorySearchResult>('memory_search', { query, n }),

    memoryStore: (content: string, metadata: Record<string, unknown>) =>
      call<{ stored: boolean }>('memory_store', { content, metadata }),

    projectSearch: (query: string) =>
      call<{ files: string[]; symbols: unknown[] }>('project_search', { query }),

    analyzeError: (errorText: string, file?: string) =>
      call<Record<string, unknown>>('analyze_error', {
        error_text: errorText,
        ...(file ? { file } : {}),
      }),

    raw: call,
  };
}
