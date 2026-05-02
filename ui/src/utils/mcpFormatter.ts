// mcpFormatter.ts — Formatage réponses MCP → Markdown (Sprint UI-04)
// Centralise le formatage qui était inline dans ChatPanel (Sprint UI-01/02/03)
// BUGFIX [object Object] : toStr() sanitise tous les champs avant interpolation

import type {
  MemorySearchResult,
  GenerateSpecResult,
  ValidateSpecResult,
  SandboxResult,
  EditBatchResult,
} from '../types/mcp';

/**
 * Convertit n'importe quelle valeur en string safe.
 * Évite le [object Object] quand Python retourne un dict/list là où on attend une string.
 */
function toStr(val: unknown, fallback = '—'): string {
  if (val === null || val === undefined) return fallback;
  if (typeof val === 'string') return val || fallback;
  if (typeof val === 'number' || typeof val === 'boolean') return String(val);
  // Objet/Array → JSON compact (évite [object Object])
  return JSON.stringify(val);
}

export function formatMcpResponse(tool: string, result: unknown): string {
  if (result === null || result === undefined) return '_Aucun résultat._';

  switch (tool) {
    case 'llm_chat':        return formatLlmChat(result as Record<string, unknown>);
    case 'web_search':       return formatWebSearch(result as Record<string, unknown>);
    case 'memory_search':    return formatMemorySearch(result as MemorySearchResult);
    case 'generate_spec':    return formatGenerateSpec(result as GenerateSpecResult);
    case 'validate_spec':    return formatValidateSpec(result as ValidateSpecResult);
    case 'sandbox_run':      return formatSandboxRun(result as SandboxResult);
    case 'evaluate_quality': return formatEvaluateQuality(result as Record<string, unknown>);
    case 'project_search':   return formatProjectSearch(result as Record<string, unknown>);
    case 'edit_batch':       return formatEditBatch(result as EditBatchResult);
    case 'analyze_error':    return formatAnalyzeError(result as Record<string, unknown>);
    default:
      return '```json\n' + JSON.stringify(result, null, 2) + '\n```';
  }
}

// ─── Formatters individuels ───────────────────────────────────────────────────

// UI-06 : réponse directe Ollama — pass-through Markdown avec footer modèle
function formatLlmChat(r: Record<string, unknown>): string {
  if (r.available === false) {
    return `⚠️ **Ollama non disponible**\n\n${r.response ?? ''}`;
  }
  const model    = String(r.model ?? 'llama3.2:3b');
  const response = String(r.response ?? '');
  return `${response}\n\n---\n_Modèle : ${model}_`;
}

// UI-06 : recherche web DDG + synthèse Ollama
function formatWebSearch(r: Record<string, unknown>): string {
  if (r.available === false || r.error) {
    return `⚠️ **Recherche indisponible**\n\n${r.error ?? 'Connexion internet inaccessible.'}`;
  }

  const synthesis = String(r.synthesis ?? '');
  const model     = String(r.model ?? '');
  const sources   = (r.sources as Array<{ title: string; url: string; success: boolean }>) ?? [];

  const lines: string[] = [];

  if (synthesis) {
    lines.push(synthesis);
  }

  if (sources.length > 0) {
    lines.push('\n---\n**Sources consultées :**');
    sources.forEach((s, i) => {
      const icon = s.success ? '📋' : '❌';
      lines.push(`${icon} [${s.title || s.url}](${s.url})`);
    });
  }

  if (model) {
    lines.push(`\n_Synthèse : ${model}_`);
  }

  return lines.join('\n') || '_Aucun résultat._';
}

function formatMemorySearch(r: MemorySearchResult): string {
  // FIX Audit 006 : Python memory_search retourne des clés normalisées sans préfixe lcca_.
  // Ordre : clés normalisées en premier, lcca_* en fallback rétrocompat.
  const raw = r as any;
  // Les clés retournées par Python memory_search sont normalisées sans préfixe "lcca_".
  // Le fallback lcca_* couvre une régression éventuelle du handler.
  const solutions = raw.solutions ?? raw.lcca_solutions ?? [];
  const failures  = raw.failures  ?? raw.lcca_failures  ?? [];
  const context   = raw.context   ?? raw.lcca_context   ?? [];
  const patches   = raw.patches   ?? raw.lcca_patches   ?? [];

  // Les specs sont dans lcca_context avec metadata.spec_id
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

function formatGenerateSpec(r: GenerateSpecResult): string {
  // BUGFIX [object Object] : toStr() sur tous les champs (Python peut retourner dict/list)
  // BUGFIX title : nettoyer les préfixes Markdown ## que le LLM met parfois dans le titre
  const rawTitle = toStr(r.title, 'Sans titre');
  const title    = rawTitle.replace(/^#{1,6}\s*/, '').trim() || 'Sans titre';
  const domain   = toStr(r.domain, 'global');
  const version  = toStr(r.version, '7.2.0');
  const specId   = toStr(r.spec_id, 'unknown');
  const score    = typeof r.score === 'number' ? r.score : 0;
  const cplx     = typeof r.complexity_score === 'number' ? r.complexity_score : 0;
  const status   = r.validated ? '✅ Validée' : '⚠ Non validée';
  const storedTag = r.auto_stored ? ' · 💾 mémorisée' : '';
  const violations = Array.isArray(r.violations) ? r.violations : [];
  return [
    `**Spec générée** : ${title}`,
    '',
    `| Champ | Valeur |`,
    `|-------|--------|`,
    `| Domaine | \`${domain}\` |`,
    `| Version | ${version} |`,
    `| Complexité | ${cplx}/100 |`,
    `| Score | ${score.toFixed(2)} |`,
    `| Statut | ${status}${storedTag} |`,
    '',
    violations.length
      ? `**${violations.length} violation(s)** — voir le badge ci-dessous.`
      : `_Aucune violation._`,
    '',
    // Pattern pour extractSpecBadge — titre entre guillemets pour supporter les espaces
    `SPEC_GENERATED: specId=${specId} title="${title.replace(/"/g, "'")}" domain=${domain} validated=${r.validated} score=${score.toFixed(2)} autoStored=${r.auto_stored ?? false}`,
  ].join('\n');
}

function formatValidateSpec(r: ValidateSpecResult): string {
  // BUGFIX [object Object] : toStr() sur specId + score null-safe
  const specId     = toStr(r.spec_id, '—');
  const score      = typeof r.score === 'number' ? r.score : 0;
  const violations = Array.isArray(r.violations) ? r.violations : [];
  const status     = r.valid ? '✅ Valide' : '❌ Invalide';
  const lines = [
    `**Validation spec** \`${specId}\` — ${status}`,
    `Score : ${score.toFixed(2)} | Violations : ${violations.length}`,
  ];
  if (violations.length > 0) {
    lines.push('\n**Violations** :');
    violations.forEach((v: any) =>
      lines.push(`- [${toStr(v.severity, 'warning').toUpperCase()}] \`${toStr(v.rule, '?')}\` — ${toStr(v.fix_suggestion, '')}`)
    );
  }
  return lines.join('\n');
}

function formatSandboxRun(r: SandboxResult): string {
  const status = r.success ? '✅ Succès' : `❌ Erreur (exit ${r.exit_code})`;
  const parts = [`**Exécution sandbox** — ${status}`];
  if (r.stdout) parts.push(`\n\`\`\`\n${r.stdout.slice(0, 2000)}\n\`\`\``);
  if (r.stderr) parts.push(`\n**Stderr :**\n\`\`\`\n${r.stderr.slice(0, 500)}\n\`\`\``);
  return parts.join('\n');
}

function formatEvaluateQuality(r: Record<string, unknown>): string {
  return [
    `**Qualité du code** — Score : **${r.total_score ?? '?'}/100**`,
    '',
    `| Critère | Score |`,
    `|---------|-------|`,
    `| Syntaxe | ${(r as any).syntax_score ?? '—'} |`,
    `| Docstrings | ${(r as any).docstring_score ?? '—'} |`,
    `| Type hints | ${(r as any).type_hint_score ?? '—'} |`,
    `| Complexité | ${(r as any).complexity_score ?? '—'} |`,
    `| Conventions | ${(r as any).convention_score ?? '—'} |`,
  ].join('\n');
}

function formatProjectSearch(r: Record<string, unknown>): string {
  const symbols = (r.symbols as unknown[]) ?? [];
  const files   = (r.files   as string[])  ?? [];
  if (!symbols.length && !files.length) return '_Aucun fichier ni symbole trouvé._';

  const parts: string[] = [];
  if (symbols.length) {
    parts.push(`**${symbols.length} symbole(s) :**`);
    (symbols as any[]).slice(0, 8).forEach(s =>
      parts.push(`- \`${s.name}\` (${s.type}) — \`${s.file}:${s.line}\``)
    );
  }
  if (files.length) {
    parts.push(`\n**${files.length} fichier(s) :**`);
    files.slice(0, 8).forEach(f => parts.push(`- \`${f}\``));
  }
  return parts.join('\n');
}

function formatEditBatch(r: EditBatchResult): string {
  if (!r.success) return `❌ **edit_batch échoué** : ${(r.errors ?? []).join(', ')}`;
  // Pattern TX pour extractTxBadge
  const txId = (r as any).tx_id ?? 'unknown';
  return `✅ **${r.applied ?? 0} patch(es) appliqué(s)**\n\nTX: ${txId} | Fichiers: voir TX | ✅`;
}

function formatAnalyzeError(r: Record<string, unknown>): string {
  const lines = [
    `**Diagnostic** : \`${r.error_type ?? '?'}\`${r.file ? ` dans \`${r.file}\`` : ''}`,
    '',
  ];
  if (r.suggestion) lines.push(`**Suggestion** : ${r.suggestion}`);
  if (r.fix_prompt) lines.push(`\n**Prompt de correction** :\n> ${String(r.fix_prompt).slice(0, 200)}`);
  return lines.filter(Boolean).join('\n');
}
