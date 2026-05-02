// mcpFormatter/memory.ts — Formatage réponses MCP mémoire & recherche (REFACTO-UI-01)
import type { MemorySearchResult, SandboxResult, EditBatchResult } from '../../types/mcp';

export function formatMemorySearch(r: MemorySearchResult): string {
  // FIX Audit 006 : Python memory_search retourne des clés normalisées sans préfixe lcca_.
  const raw = r as any;
  const solutions = raw.solutions ?? raw.lcca_solutions ?? [];
  const failures  = raw.failures  ?? raw.lcca_failures  ?? [];
  const context   = raw.context   ?? raw.lcca_context   ?? [];
  const patches   = raw.patches   ?? raw.lcca_patches   ?? [];

  const specs    = context.filter((e: any) => e?.metadata?.spec_id);
  const contexts = context.filter((e: any) => !e?.metadata?.spec_id);

  const total = solutions.length + failures.length + contexts.length + patches.length + specs.length;
  if (total === 0) return '_Aucun résultat en mémoire pour cette requête._';

  const parts: string[] = [`**${total} résultat(s) trouvé(s)**\n`];

  if (specs.length) {
    parts.push('### 📋 Specs');
    specs.slice(0, 5).forEach((e: any) => {
      const title  = e.metadata?.title  ?? e.content?.slice(0, 60) ?? e.id ?? 'Sans titre';
      const domain = e.metadata?.domain ?? 'global';
      parts.push(`- **${title}** — \`${domain}\``);
    });
  }
  if (solutions.length) {
    parts.push('\n### ✅ Solutions');
    solutions.slice(0, 3).forEach((e: any) => {
      const preview = String(e.content ?? e.metadata?.content ?? '').slice(0, 120);
      parts.push(`- ${preview}${preview.length === 120 ? '…' : ''}`);
    });
  }
  if (failures.length) {
    parts.push('\n### ❌ Échecs connus');
    failures.slice(0, 2).forEach((e: any) => {
      const preview = String(e.content ?? e.metadata?.content ?? '').slice(0, 120);
      parts.push(`- ${preview}${preview.length === 120 ? '…' : ''}`);
    });
  }
  if (contexts.length) {
    parts.push('\n### 📚 Contexte');
    contexts.slice(0, 3).forEach((e: any) => {
      const preview = String(e.content ?? '').slice(0, 120);
      parts.push(`- ${preview}${preview.length === 120 ? '…' : ''}`);
    });
  }
  if (patches.length) {
    parts.push('\n### 🧹 Patches');
    patches.slice(0, 2).forEach((e: any) => {
      const preview = String(e.content ?? '').slice(0, 80);
      parts.push(`- ${preview}${preview.length === 80 ? '…' : ''}`);
    });
  }
  return parts.join('\n');
}

export function formatSandboxRun(r: SandboxResult): string {
  const status = r.success ? '✅ Succès' : `❌ Erreur (exit ${r.exit_code})`;
  const parts = [`**Exécution sandbox** — ${status}`];
  if (r.stdout) parts.push(`\n\`\`\`\n${r.stdout.slice(0, 2000)}\n\`\`\``);
  if (r.stderr) parts.push(`\n**Stderr :**\n\`\`\`\n${r.stderr.slice(0, 500)}\n\`\`\``);
  return parts.join('\n');
}

export function formatEditBatch(r: EditBatchResult): string {
  if (!r.success) return `❌ **edit_batch échoué** : ${(r.errors ?? []).join(', ')}`;
  const txId = (r as any).tx_id ?? 'unknown';
  return `✅ **${r.applied ?? 0} patch(es) appliqué(s)**\n\nTX: ${txId} | Fichiers: voir TX | ✅`;
}
