// ContextMenu.tsx — Menu contextuel clic droit sur les bulles de message
// Invariants :
//   - Fermeture sur Escape / clic extérieur / scroll
//   - Position ajustée pour rester dans la fenêtre (clamp viewport)
//   - Copie via navigator.clipboard (Electron l'expose nativement)
//   - onQuote : injecte "> texte\n" dans l'InputZone via callback
import { useEffect, useRef, useCallback } from 'react';

export interface ContextMenuAction {
  id:       string;
  label:    string;
  icon:     string;
  shortcut?: string;
  danger?:  boolean;
  divider?: boolean; // divider AVANT cet item
  disabled?: boolean;
}

interface Props {
  x:        number;
  y:        number;
  actions:  ContextMenuAction[];
  onAction: (id: string) => void;
  onClose:  () => void;
}

export function ContextMenu({ x, y, actions, onAction, onClose }: Props) {
  const menuRef = useRef<HTMLDivElement>(null);

  // Ajustement position pour rester dans le viewport
  const getStyle = useCallback(() => {
    const el    = menuRef.current;
    const W     = window.innerWidth;
    const H     = window.innerHeight;
    const mW    = el?.offsetWidth  ?? 200;
    const mH    = el?.offsetHeight ?? 300;
    const left  = Math.min(x, W - mW - 8);
    const top   = Math.min(y, H - mH - 8);
    return { left: Math.max(8, left), top: Math.max(8, top) };
  }, [x, y]);

  // Fermeture sur clic extérieur / Escape / scroll
  useEffect(() => {
    const handleKey   = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    const handleClick = (e: MouseEvent)    => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    };
    const handleScroll = () => onClose();

    document.addEventListener('keydown',  handleKey,    true);
    document.addEventListener('mousedown', handleClick,  true);
    document.addEventListener('scroll',   handleScroll, true);
    return () => {
      document.removeEventListener('keydown',  handleKey,    true);
      document.removeEventListener('mousedown', handleClick,  true);
      document.removeEventListener('scroll',   handleScroll, true);
    };
  }, [onClose]);

  // Focus trap léger : premier item focusable
  useEffect(() => {
    const first = menuRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)');
    first?.focus();
  }, []);

  const style = getStyle();

  return (
    <div
      ref={menuRef}
      className="ctx-menu"
      role="menu"
      aria-label="Actions sur le message"
      style={{ position: 'fixed', left: style.left, top: style.top, zIndex: 9999 }}
    >
      {actions.map((action) => (
        <div key={action.id}>
          {action.divider && <div className="ctx-divider" role="separator" />}
          <button
            className={`ctx-item${action.danger ? ' ctx-item--danger' : ''}`}
            role="menuitem"
            disabled={action.disabled}
            onClick={() => {
              if (!action.disabled) { onAction(action.id); onClose(); }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (!action.disabled) { onAction(action.id); onClose(); }
              }
            }}
          >
            <span className="ctx-icon" aria-hidden="true">{action.icon}</span>
            <span className="ctx-label">{action.label}</span>
            {action.shortcut && (
              <span className="ctx-shortcut" aria-hidden="true">{action.shortcut}</span>
            )}
          </button>
        </div>
      ))}
    </div>
  );
}


// ── Hook : useContextMenu ────────────────────────────────────────────────────
// Gère l'état ouvert/position/cible du menu contextuel

import { useState } from 'react';

export interface ContextMenuState {
  open:    boolean;
  x:       number;
  y:       number;
  target?: string; // identifiant de la cible (ex: message id)
}

export function useContextMenu() {
  const [menu, setMenu] = useState<ContextMenuState>({ open: false, x: 0, y: 0 });

  const openMenu = useCallback((e: React.MouseEvent, target?: string) => {
    e.preventDefault();
    e.stopPropagation();
    setMenu({ open: true, x: e.clientX, y: e.clientY, target });
  }, []);

  const closeMenu = useCallback(() => {
    setMenu(prev => ({ ...prev, open: false }));
  }, []);

  return { menu, openMenu, closeMenu };
}


// ── Helpers ──────────────────────────────────────────────────────────────────

/** Copie du texte dans le presse-papier. Retourne true si succès. */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback execCommand (contexte non-HTTPS ou ancien Electron)
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity  = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  }
}

/** Extrait le premier bloc de code (``` ... ```) du contenu markdown. */
export function extractFirstCodeBlock(content: string): string | null {
  const m = content.match(/```[\w]*\n?([\s\S]*?)```/);
  return m ? m[1].trim() : null;
}

/** Formate le contenu en citation Markdown. */
export function formatAsQuote(text: string): string {
  return text
    .split('\n')
    .map(line => `> ${line}`)
    .join('\n') + '\n';
}
