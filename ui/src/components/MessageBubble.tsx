import { useState, useCallback } from 'react';
import { MarkdownRenderer } from './MarkdownRenderer';
import { TxBadge }          from './TxBadge';
import { SpecBadge }        from './SpecBadge';
import { StreamingIndicator } from './StreamingIndicator';
import {
  ContextMenu,
  useContextMenu,
  copyToClipboard,
  extractFirstCodeBlock,
  formatAsQuote,
  type ContextMenuAction,
} from './ContextMenu';
import type { Message, SpecBadge as SpecBadgeType } from '../types/chat';

interface Props {
  message:        Message;
  isStreaming?:   boolean;
  onSpecView?:    (specId: string, badge?: SpecBadgeType) => void;
  onTxRollback?:  (txId: string)   => Promise<void>;
  onQuote?:       (text: string)   => void;  // injecte une citation dans l'InputZone
}

function exportSpec(badge: { specId: string; title: string }, content: string) {
  const blob = new Blob([content], { type: 'text/markdown' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `spec-${badge.specId}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

export function MessageBubble({ message, isStreaming, onSpecView, onTxRollback, onQuote }: Props) {
  const isUser   = message.role === 'user';
  const isSystem = message.role === 'system';
  const { menu, openMenu, closeMenu } = useContextMenu();
  const [toast, setToast] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 1800);
  }, []);

  // ── Actions disponibles selon le contexte ──────────────────────────────────
  const buildActions = useCallback((): ContextMenuAction[] => {
    const hasCode  = !!extractFirstCodeBlock(message.content);
    const isAssist = message.role === 'assistant';
    const actions: ContextMenuAction[] = [
      { id: 'copy',      label: 'Copier le texte',    icon: '⎘',  shortcut: 'Ctrl+C' },
      { id: 'copy-raw',  label: 'Copier le Markdown', icon: '📋' },
      ...(hasCode ? [{ id: 'copy-code', label: 'Copier le code', icon: '{}', shortcut: 'Ctrl+Shift+C' } as ContextMenuAction] : []),
      ...(onQuote ? [{ id: 'quote', label: 'Citer dans l\'InputZone', icon: '❝', divider: true } as ContextMenuAction] : []),
      ...(isAssist ? [{ id: 'copy-md', label: 'Exporter en .md', icon: '⬇', divider: !onQuote } as ContextMenuAction] : []),
    ];
    return actions;
  }, [message.content, message.role, onQuote]);

  const handleAction = useCallback(async (id: string) => {
    const plain   = message.content.replace(/```[\w]*\n?[\s\S]*?```/g, s => s.replace(/```[\w]*/g, '').replace(/```/g, '')).trim();
    const raw     = message.content;
    const code    = extractFirstCodeBlock(message.content);

    switch (id) {
      case 'copy':      await copyToClipboard(plain);       showToast('✓ Texte copié');    break;
      case 'copy-raw':  await copyToClipboard(raw);         showToast('✓ Markdown copié'); break;
      case 'copy-code': await copyToClipboard(code ?? ''); showToast('✓ Code copié');     break;
      case 'quote':
        if (onQuote) onQuote(formatAsQuote(plain.slice(0, 400)));
        break;
      case 'copy-md': {
        const blob = new Blob([raw], { type: 'text/markdown' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `message-${message.id.slice(0, 8)}.md`;
        a.click();
        URL.revokeObjectURL(url);
        showToast('✓ Fichier téléchargé');
        break;
      }
    }
  }, [message.content, message.id, onQuote, showToast]);

  // ── Messages système : pas de menu contextuel ──────────────────────────────
  if (isSystem) {
    return (
      <div className="message-bubble bubble-system" role="status">
        <span className="bubble-system-icon" aria-hidden="true">&#x26A0;</span>
        <p className="bubble-system-text">{message.content}</p>
      </div>
    );
  }

  // Pré-streaming : aucun contenu encore → bulle complète avec orbes
  if (isStreaming && !message.content) {
    return (
      <div className="message-bubble bubble-assistant">
        <div className="bubble-avatar-gem" aria-hidden="true" />
        <StreamingIndicator tool={message.activeTool} mode="full" />
      </div>
    );
  }

  return (
    <div
      className={`message-bubble ${isUser ? 'bubble-user' : 'bubble-assistant'}`}
      onContextMenu={!isStreaming ? openMenu : undefined}
      data-ctx-open={menu.open ? 'true' : undefined}
    >
      {!isUser && (
        <div className="bubble-avatar-gem" aria-hidden="true" />
      )}  

      <div className="bubble-content" aria-live={isStreaming ? 'polite' : undefined}>
        {/* Bouton «⋯» discret — même logique que clic droit */}
        {!isStreaming && (
          <button
            className="ctx-trigger"
            onClick={openMenu}
            aria-label="Actions sur ce message"
            title="Actions"
            tabIndex={-1}
          >
            ⋯
          </button>
        )}

        {isUser ? (
          <p className="bubble-text">{message.content}</p>
        ) : (
          <MarkdownRenderer content={message.content} isStreaming={isStreaming} />
        )}

        {/* Curseur clignotant */}
        {isStreaming && message.content && (
          <span className="bubble-cursor" aria-hidden="true">&#x258D;</span>
        )}

        {/* UI-THINK-01 : indicateur inline pendant streaming de texte */}
        {isStreaming && message.content && (
          <StreamingIndicator tool={message.activeTool} mode="inline" />
        )}

        {message.txBadge && (
          <TxBadge
            badge={message.txBadge}
            onRollback={onTxRollback}
          />
        )}

        {message.specBadge && (
          <SpecBadge
            badge={message.specBadge}
            onView={() => onSpecView?.(message.specBadge!.specId, message.specBadge)}
            onExport={() => exportSpec(
              message.specBadge!,
              message.specBadge!.body_md ?? `# ${message.specBadge!.title}\n\n_Corps non disponible._`
            )}
          />
        )}

        {/* UI-MODEL-01 : badge modèle en bas de la bulle assistant */}
        {!isStreaming && message.role === 'assistant' && message.modelName && (
          <div className="bubble-model-badge" title={`Généré par ${message.modelName}`}>
            <span className="bubble-model-icon" aria-hidden="true">◆</span>
            <span className="bubble-model-name">{message.modelName}</span>
          </div>
        )}
      </div>

      {/* Menu contextuel */}
      {menu.open && !isStreaming && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          actions={buildActions()}
          onAction={handleAction}
          onClose={closeMenu}
        />
      )}

      {/* Toast confirmation */}
      {toast && <div className="ctx-toast">{toast}</div>}
    </div>
  );
}
