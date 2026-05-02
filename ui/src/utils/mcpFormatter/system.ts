// mcpFormatter/system.ts — Formatage réponses MCP système (LLM, web, AST, erreurs) (REFACTO-UI-01)

export function formatLlmChat(r: Record<string, unknown>): string {
  if (r.available === false) {
    return `⚠️ **Ollama non disponible**\n\n${r.response ?? ''}`;
  }
  const model    = String(r.model ?? 'llama3.2:3b');
  const response = String(r.response ?? '');
  return `${response}\n\n---\n_Modèle : ${model}_`;
}

export function formatWebSearch(r: Record<string, unknown>): string {
  if (r.available === false || r.error) {
    return `⚠️ **Recherche indisponible**\n\n${r.error ?? 'Connexion internet inaccessible.'}`;
  }

  const synthesis = String(r.synthesis ?? '');
  const model     = String(r.model ?? '');
  const sources   = (r.sources as Array<{ title: string; url: string; success: boolean }>) ?? [];

  const lines: string[] = [];
  if (synthesis) lines.push(synthesis);
  if (sources.length > 0) {
    lines.push('\n---\n**Sources consultées :**');
    sources.forEach((s) => {
      const icon = s.success ? '📋' : '❌';
      lines.push(`${icon} [${s.title || s.url}](${s.url})`);
    });
  }
  if (model) lines.push(`\n_Synthèse : ${model}_`);

  return lines.join('\n') || '_Aucun résultat._';
}

export function formatEvaluateQuality(r: Record<string, unknown>): string {
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

export function formatProjectSearch(r: Record<string, unknown>): string {
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

export function formatAnalyzeError(r: Record<string, unknown>): string {
  const lines = [
    `**Diagnostic** : \`${r.error_type ?? '?'}\`${r.file ? ` dans \`${r.file}\`` : ''}`,
    '',
  ];
  if (r.suggestion) lines.push(`**Suggestion** : ${r.suggestion}`);
  if (r.fix_prompt) lines.push(`\n**Prompt de correction** :\n> ${String(r.fix_prompt).slice(0, 200)}`);
  return lines.filter(Boolean).join('\n');
}
