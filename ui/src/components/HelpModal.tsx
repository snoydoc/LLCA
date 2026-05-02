// HelpModal.tsx — BUGFIX MODAL-01 : modale Aide (absente jusqu'ici)
import { useRef } from 'react';
import { useFocusTrap } from '../hooks/useFocusTrap';

interface ShortcutRowProps {
  keys: string[];
  label: string;
}
function ShortcutRow({ keys, label }: ShortcutRowProps) {
  return (
    <div className="help-shortcut-row">
      <span className="help-shortcut-label">{label}</span>
      <span className="help-shortcut-keys">
        {keys.map((k, i) => (
          <span key={i}>
            <kbd className="help-kbd">{k}</kbd>
            {i < keys.length - 1 && <span className="help-kbd-sep">+</span>}
          </span>
        ))}
      </span>
    </div>
  );
}

export function HelpModal({ onClose }: { onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, true);

  return (
    <div
      className="modal-overlay"
      onClick={e => e.target === e.currentTarget && onClose()}
      aria-hidden="false"
    >
      <div
        ref={dialogRef}
        className="modal-content help-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Aide LCCA"
        onKeyDown={e => e.key === 'Escape' && onClose()}
      >
        {/* En-tête */}
        <div className="modal-header">
          <h2>❓ Aide — LCCA Desktop</h2>
          <button onClick={onClose} aria-label="Fermer l'aide">×</button>
        </div>

        {/* Corps */}
        <div className="settings-body">

          {/* Commandes chat */}
          <div className="settings-section">
            <h3 className="settings-section-title">Commandes chat</h3>
            <div className="help-cmd-list">
              <div className="help-cmd-row"><code>@web &lt;query&gt;</code><span>Recherche web DuckDuckGo + synthèse</span></div>
              <div className="help-cmd-row"><code>@spec &lt;intent&gt;</code><span>Générer une spec technique</span></div>
              <div className="help-cmd-row"><code>@validate &lt;spec_id&gt;</code><span>Valider une spec (id 12 chars hex)</span></div>
              <div className="help-cmd-row"><code>@eval &lt;code&gt;</code><span>Évaluer la qualité du code</span></div>
              <div className="help-cmd-row"><code>@mem &lt;query&gt;</code><span>Rechercher dans la mémoire LCCA</span></div>
              <div className="help-cmd-row"><code>@file &lt;query&gt;</code><span>Rechercher dans le projet</span></div>
              <div className="help-cmd-row"><code>```python … ```</code><span>Exécuter en sandbox</span></div>
            </div>
          </div>

          {/* Raccourcis clavier */}
          <div className="settings-section">
            <h3 className="settings-section-title">Raccourcis clavier</h3>
            <div className="help-shortcuts">
              <ShortcutRow keys={['Ctrl', 'K']}        label="Palette de commandes" />
              <ShortcutRow keys={['Ctrl', ',']}         label="Paramètres" />
              <ShortcutRow keys={['F1']}                label="Aide" />
              <ShortcutRow keys={['Ctrl', 'N']}         label="Nouvelle session" />
              <ShortcutRow keys={['Ctrl', 'L']}         label="Effacer le chat" />
              <ShortcutRow keys={['Ctrl', '\\']}        label="Afficher/masquer le panneau contexte" />
              <ShortcutRow keys={['Ctrl', 'Shift', 'F']} label="Mode focus (chat seul)" />
              <ShortcutRow keys={['Ctrl', 'Shift', 'T']} label="Basculer thème clair/sombre" />
              <ShortcutRow keys={['Entrée']}            label="Envoyer le message" />
              <ShortcutRow keys={['Maj', 'Entrée']}     label="Saut de ligne" />
              <ShortcutRow keys={['Échap']}             label="Annuler / fermer" />
            </div>
          </div>

          {/* Outils MCP */}
          <div className="settings-section">
            <h3 className="settings-section-title">Outils MCP disponibles</h3>
            <div className="help-cmd-list">
              <div className="help-cmd-row"><code>llm_chat</code><span>Conversation avec Ollama (RAG auto)</span></div>
              <div className="help-cmd-row"><code>web_search</code><span>Recherche web multi-sources</span></div>
              <div className="help-cmd-row"><code>generate_spec</code><span>Génération spec technique (SpecDirectPattern)</span></div>
              <div className="help-cmd-row"><code>validate_spec</code><span>Validation R01-R15</span></div>
              <div className="help-cmd-row"><code>edit_batch</code><span>Écriture ACID dans le workspace</span></div>
              <div className="help-cmd-row"><code>sandbox_run</code><span>Exécution Python isolée</span></div>
              <div className="help-cmd-row"><code>evaluate_quality</code><span>Score qualité AST (0-100)</span></div>
              <div className="help-cmd-row"><code>memory_search</code><span>Recherche ChromaDB (5 collections)</span></div>
              <div className="help-cmd-row"><code>project_search</code><span>Recherche symboles AST workspace</span></div>
              <div className="help-cmd-row"><code>analyze_error</code><span>Analyse et suggestion correctif</span></div>
            </div>
          </div>

          {/* À propos */}
          <div className="settings-section">
            <h3 className="settings-section-title">À propos</h3>
            <p className="settings-about">LCCA Desktop v1.0.0 — 100% local, aucune connexion externe</p>
            <p className="settings-about">McpServer V7.2 · Ollama · ChromaDB · LibCST</p>
          </div>

        </div>

        {/* Pied */}
        <div className="modal-footer">
          <button className="btn-primary" onClick={onClose}>Fermer</button>
        </div>
      </div>
    </div>
  );
}
