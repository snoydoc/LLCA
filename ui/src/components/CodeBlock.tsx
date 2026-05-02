// CodeBlock.tsx — UI-DS-02 : coloration syntaxique conditionnelle par thème
// Tokenizer CSS léger (sans dépendance externe) — utilise les variables --syn-* de themes.css
import { useState, useCallback, useMemo } from 'react';
import { Copy, Check } from 'lucide-react';
import { useSettingsStore } from '../stores/settingsStore';

interface CodeBlockProps {
  language: string;
  code:     string;
  filename?: string;
}

// ─── Tokenizer minimal ────────────────────────────────────────────────────────
// Chaque règle : { regex, cssVar } — appliquées dans l'ordre sur le code HTML-échappé.
// On wrap chaque match dans un <span style="color: var(--syn-X)">

// ─── Règles diff ─────────────────────────────────────────────────────────────
// Marquées séparément : on gère +/- par classe CSS plutôt que span
const IS_DIFF_LANG = new Set(['diff', 'patch']);

const LANG_RULES: Record<string, Array<{ re: RegExp; varName: string }>> = {
  python: [
    { re: /(#[^\n]*)/g,                                                        varName: '--syn-comment'  },
    { re: /\b(def|class|return|import|from|if|elif|else|for|while|in|not|and|or|with|as|try|except|finally|raise|pass|break|continue|lambda|yield|async|await|True|False|None)\b/g, varName: '--syn-keyword' },
    { re: /\b([A-Z][a-zA-Z0-9_]*)(?=\()/g,                                    varName: '--syn-fn'       },
    { re: /\b([a-z_][a-zA-Z0-9_]*)(?=\()/g,                                    varName: '--syn-fn'       },
    { re: /(&quot;.*?&quot;|&#39;.*?&#39;|`[^`]*`)/g,                          varName: '--syn-string'   },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
  typescript: [
    { re: /(\/\/[^\n]*)/g,                                                     varName: '--syn-comment'  },
    { re: /(\/\*[\s\S]*?\*\/)/g,                                               varName: '--syn-comment'  },
    { re: /\b(const|let|var|function|return|import|export|from|if|else|for|while|class|extends|interface|type|enum|async|await|new|this|typeof|instanceof|in|of|try|catch|finally|throw|break|continue|default|switch|case|void|never|any|unknown|as|satisfies|declare|readonly|static|public|private|protected|abstract|override)\b/g, varName: '--syn-keyword' },
    { re: /\b([A-Z][a-zA-Z0-9_]*)(?=[^(])/g,                                   varName: '--syn-fn'       },
    { re: /\b([a-z_][a-zA-Z0-9_]*)(?=\()/g,                                    varName: '--syn-fn'       },
    { re: /(&quot;.*?&quot;|&#39;.*?&#39;|`[^`]*`)/g,                          varName: '--syn-string'   },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
  javascript: [
    { re: /(\/\/[^\n]*)/g,                                                     varName: '--syn-comment'  },
    { re: /(\/\*[\s\S]*?\*\/)/g,                                               varName: '--syn-comment'  },
    { re: /\b(const|let|var|function|return|import|export|from|if|else|for|while|class|extends|async|await|new|this|typeof|instanceof|in|of|try|catch|finally|throw|break|continue|default|switch|case)\b/g, varName: '--syn-keyword' },
    { re: /\b([a-z_][a-zA-Z0-9_]*)(?=\()/g,                                    varName: '--syn-fn'       },
    { re: /(&quot;.*?&quot;|&#39;.*?&#39;|`[^`]*`)/g,                          varName: '--syn-string'   },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
  bash: [
    { re: /(#[^\n]*)/g,                                                        varName: '--syn-comment'  },
    { re: /\b(if|then|else|elif|fi|for|while|do|done|case|esac|in|function|return|export|echo|cd|ls|mkdir|rm|cp|mv|cat|grep|sed|awk|chmod|chown|sudo|source|exit)\b/g, varName: '--syn-keyword' },
    { re: /(\$[A-Za-z_][A-Za-z0-9_]*|\$\{[^}]+\})/g,                         varName: '--syn-fn'       },
    { re: /(&quot;.*?&quot;|&#39;.*?&#39;)/g,                                  varName: '--syn-string'   },
    { re: /\b(\d+)/g,                                                           varName: '--syn-number'   },
  ],
  sql: [
    { re: /(--[^\n]*)/g,                                                       varName: '--syn-comment'  },
    { re: /\b(SELECT|FROM|WHERE|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|AND|OR|NOT|IN|EXISTS|INSERT|INTO|VALUES|UPDATE|SET|DELETE|CREATE|TABLE|INDEX|DROP|ALTER|ADD|COLUMN|PRIMARY|KEY|FOREIGN|REFERENCES|DEFAULT|NULL|UNIQUE|CONSTRAINT|GROUP|BY|ORDER|HAVING|LIMIT|OFFSET|DISTINCT|COUNT|SUM|AVG|MAX|MIN|COALESCE|CASE|WHEN|THEN|ELSE|END)\b/gi, varName: '--syn-keyword' },
    { re: /(&quot;.*?&quot;|&#39;.*?&#39;)/g,                                  varName: '--syn-string'   },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
  css: [
    { re: /(\/\*[\s\S]*?\*\/)/g,                                               varName: '--syn-comment'  },
    { re: /([.#][a-zA-Z][a-zA-Z0-9_-]*)/g,                                     varName: '--syn-tag'      },
    { re: /([a-z-]+)(?=\s*:)/g,                                                 varName: '--syn-attr'     },
    { re: /(::[a-z-]+|:[a-z-]+)/g,                                              varName: '--syn-keyword'  },
    { re: /(&quot;.*?&quot;|&#39;.*?&#39;)/g,                                  varName: '--syn-string'   },
    { re: /(#[0-9a-fA-F]{3,8})/g,                                               varName: '--syn-number'   },
  ],
  json: [
    { re: /(&quot;[^&]*?&quot;)(?=\s*:)/g,                                     varName: '--syn-attr'     },
    { re: /:\s*(&quot;[^&]*?&quot;)/g,                                          varName: '--syn-string'   },
    { re: /\b(true|false|null)\b/g,                                             varName: '--syn-keyword'  },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
  yaml: [
    { re: /(#[^\n]*)/g,                                                         varName: '--syn-comment'  },
    { re: /^([\w-]+)(?=\s*:)/gm,                                               varName: '--syn-attr'     },
    { re: /:\s*(&quot;.*?&quot;|&#39;.*?&#39;|[^\n{[]+)/g,                    varName: '--syn-string'   },
    { re: /\b(true|false|null|yes|no)\b/g,                                      varName: '--syn-keyword'  },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
  toml: [
    { re: /(#[^\n]*)/g,                                                         varName: '--syn-comment'  },
    { re: /(\[[^\]]+\])/g,                                                       varName: '--syn-keyword'  },
    { re: /^([\w-]+)(?=\s*=)/gm,                                               varName: '--syn-attr'     },
    { re: /=\s*(&quot;.*?&quot;|&#39;.*?&#39;)/g,                             varName: '--syn-string'   },
    { re: /\b(true|false)\b/g,                                                  varName: '--syn-fn'       },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
  powershell: [
    { re: /(#[^\n]*)/g,                                                         varName: '--syn-comment'  },
    { re: /(\$[A-Za-z_][A-Za-z0-9_]*)/g,                                        varName: '--syn-fn'       },
    { re: /\b(if|else|elseif|foreach|for|while|do|switch|function|return|param|begin|process|end|try|catch|finally|throw|break|continue|exit|Write-Host|Write-Output|Write-Error|Get-|Set-|New-|Remove-|Invoke-)\b/g, varName: '--syn-keyword' },
    { re: /(&quot;.*?&quot;|&#39;.*?&#39;)/g,                                  varName: '--syn-string'   },
    { re: /\b(\d+\.?\d*)/g,                                                     varName: '--syn-number'   },
  ],
};
// Fallback : langues non reconnues → aliases courants
const LANG_ALIASES: Record<string, string> = {
  ts: 'typescript', tsx: 'typescript', jsx: 'javascript', js: 'javascript',
  sh: 'bash', shell: 'bash', zsh: 'bash', py: 'python',
  ps1: 'powershell', ps: 'powershell',
  yml: 'yaml',
  patch: 'diff',
};

/** Échappe le HTML pour éviter les injections XSS avant la colorisation */
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Applique les règles de colorisation et retourne du HTML annoté */
function colorize(code: string, lang: string): string {
  const resolved = LANG_ALIASES[lang] ?? lang;
  const rules    = LANG_RULES[resolved];
  if (!rules) return escapeHtml(code);

  let html = escapeHtml(code);
  for (const { re, varName } of rules) {
    html = html.replace(re, (match) =>
      `<span style="color:var(${varName})">${match}</span>`
    );
  }
  return html;
}

/**
 * Rend le code avec numéros de ligne.
 * Pour diff : détecte les +/- et applique cb-diff-add / cb-diff-del.
 * Retourne un tableau de strings HTML à injecter comme dangerouslySetInnerHTML.
 */
function renderLines(
  code: string,
  lang: string
): string {
  const resolved = LANG_ALIASES[lang] ?? lang;
  const isDiff   = IS_DIFF_LANG.has(resolved);

  const rawLines = code.split('\n');
  // Retirer la dernière ligne vide si le code se termine par \n
  if (rawLines[rawLines.length - 1] === '') rawLines.pop();

  const parts: string[] = [];
  rawLines.forEach((line, i) => {
    const lineNum  = i + 1;
    let cls        = 'cb-line';
    let lineHtml: string;

    if (isDiff) {
      if (line.startsWith('+') && !line.startsWith('+++')) cls += ' cb-diff-add';
      else if (line.startsWith('-') && !line.startsWith('---')) cls += ' cb-diff-del';
      lineHtml = escapeHtml(line);
    } else {
      lineHtml = colorize(line, lang);
    }

    parts.push(
      `<span class="${cls}">` +
      `<span class="cb-ln">${lineNum}</span>` +
      `<span class="cb-code">${lineHtml}</span>` +
      `</span>`
    );
  });
  return parts.join('');
}

// ─── Composant ────────────────────────────────────────────────────────────────
export function CodeBlock({ language, code, filename }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  // On écoute le thème pour re-calculer si thème change (les var CSS s'adaptent automatiquement,
  // mais on garde la dépendance pour forcer un re-render propre)
  useSettingsStore(s => s.theme); // abonnement léger

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = code;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [code]);

  // Mémoïsation : re-calcule si code ou langue change
  const renderedLines = useMemo(
    () => renderLines(code, (language ?? '').toLowerCase()),
    [code, language]
  );

  const displayLang = (language || 'text').toLowerCase();

  return (
    <div className="code-block">
      <div className="code-block-header">
        {/* Dots macOS — charte graphique adham_dual_theme */}
        <div className="code-block-dots" aria-hidden="true">
          <span className="code-block-dot code-block-dot-r" />
          <span className="code-block-dot code-block-dot-y" />
          <span className="code-block-dot code-block-dot-g" />
        </div>
        <span className="code-block-lang">{displayLang}</span>
        {filename && <span className="code-block-filename">{filename}</span>}
        <button
          className={`code-block-copy${copied ? ' copied' : ''}`}
          onClick={handleCopy}
          aria-label="Copier le code"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copié !' : 'Copier'}
        </button>
      </div>
      <pre className="code-block-pre">
        <code dangerouslySetInnerHTML={{ __html: renderedLines }} />
      </pre>
    </div>
  );
}
