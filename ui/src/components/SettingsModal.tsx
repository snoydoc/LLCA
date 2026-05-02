// SettingsModal.tsx — Paramètres LCCA Desktop (Sprint UI-05 / REFACTO-UI-01)
// Logique IPC (browse workspace, detect Python) extraite dans hooks/useSettings.ts
// SI-06 : SelfImprovePanel intégré dans la section Auto-amélioration
import { useRef, useState, useEffect } from 'react';
import { useSettingsStore }  from '../stores/settingsStore';
import { useVoiceStore }     from '../stores/voiceStore';
import { useFocusTrap }      from '../hooks/useFocusTrap';
import { useSettings }       from '../hooks/useSettings';
import { SelfImprovePanel }   from './SelfImprovePanel';
import { OnlineModelsPanel } from './OnlineModelsPanel';

// ── Section helper ────────────────────────────────────────────────────────────
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="settings-section">
      <h3 className="settings-section-title">{title}</h3>
      {children}
    </div>
  );
}

// ── SettingsModal ─────────────────────────────────────────────────────────────
export function SettingsModal({ onClose }: { onClose: () => void }) {
  const settings  = useSettingsStore();
  const { sttEnabled, ttsEnabled, setSttEnabled, setTtsEnabled } = useVoiceStore();
  const dialogRef = useRef<HTMLDivElement>(null);
  const { detecting, restarting, handleBrowseWorkspace, handleDetectPython, handleRestartServer } = useSettings();

  // ── Profil utilisateur ──────────────────────────────────────────
  const [userName,     setUserName]     = useState('');
  const [nameSaved,    setNameSaved]    = useState(false);
  const [nameSaving,   setNameSaving]   = useState(false);

  // Charger le prénom au montage
  useEffect(() => {
    const lcca = (window as any).lcca;
    lcca?.userContext?.read().then((res: any) => {
      const name = res?.data?.identity?.name;
      if (name) setUserName(name);
    }).catch(() => {});
  }, []);

  const handleSaveName = async () => {
    const trimmed = userName.trim();
    setNameSaving(true);
    try {
      await (window as any).lcca.userContext.setName(trimmed);
      setNameSaved(true);
      setTimeout(() => setNameSaved(false), 2000);
    } catch { /* ignore */ } finally {
      setNameSaving(false);
    }
  };

  // Focus trap WCAG AA
  useFocusTrap(dialogRef, true);

  return (
    <div
      className="modal-overlay"
      onClick={e => e.target === e.currentTarget && onClose()}
      aria-hidden="false"
    >
      <div
        ref={dialogRef}
        className="modal-content settings-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Paramètres LCCA"
        onKeyDown={e => e.key === 'Escape' && onClose()}
      >
        {/* ── En-tête ─────────────────────────────────────────────────── */}
        <div className="modal-header">
          <h2>⚙ Paramètres</h2>
          <button onClick={onClose} aria-label="Fermer les paramètres">×</button>
        </div>

        {/* ── Corps ───────────────────────────────────────────────────── */}
        <div className="settings-body">

          {/* ── Profil ────────────────────────────────────────── */}
          <Section title="👤 Profil">
            <div className="settings-row">
              <label htmlFor="settings-username">
                Prénom
                <span className="settings-hint">Affiché dans l’écran d’accueil</span>
              </label>
              <div className="settings-input-group">
                <input
                  id="settings-username"
                  type="text"
                  value={userName}
                  onChange={e => { setUserName(e.target.value); setNameSaved(false); }}
                  onKeyDown={e => { if (e.key === 'Enter') handleSaveName(); }}
                  onBlur={handleSaveName}
                  placeholder="ex : Adham"
                  maxLength={40}
                  disabled={nameSaving}
                  aria-label="Votre prénom"
                />
                {nameSaved && (
                  <span style={{
                    fontSize:   11,
                    color:      'var(--success)',
                    fontFamily: 'var(--font-mono)',
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}>
                    ✓ Enregistré
                  </span>
                )}
              </div>
            </div>
          </Section>

          {/* Apparence */}
          <Section title="Apparence">
            <div className="settings-row">
              <label>Thème</label>
              <div className="radio-group" role="radiogroup" aria-label="Choisir le thème">
                <label>
                  <input
                    type="radio" name="theme" value="dark"
                    checked={settings.theme === 'dark'}
                    onChange={() => settings.setTheme('dark')}
                  />
                  <span aria-hidden="true">🌙</span> Sombre
                </label>
                <label>
                  <input
                    type="radio" name="theme" value="light"
                    checked={settings.theme === 'light'}
                    onChange={() => settings.setTheme('light')}
                  />
                  <span aria-hidden="true">☀</span> Clair
                </label>
              </div>
            </div>

            <div className="settings-row">
              <label>Taille du texte</label>
              <div className="radio-group" role="radiogroup" aria-label="Taille du texte">
                {(['sm', 'md', 'lg'] as const).map(size => (
                  <label key={size}>
                    <input
                      type="radio" name="fontSize" value={size}
                      checked={settings.fontSize === size}
                      onChange={() => settings.setFontSize(size)}
                    />
                    {size === 'sm' ? 'Petit' : size === 'md' ? 'Normal' : 'Grand'}
                  </label>
                ))}
              </div>
            </div>

            <div className="settings-row">
              <label htmlFor="settings-panelMode">Disposition</label>
              <select
                id="settings-panelMode"
                value={settings.panelMode}
                onChange={e => settings.setPanelMode(e.target.value as any)}
                aria-label="Mode de disposition des panneaux"
              >
                <option value="standard">Standard (3 panneaux)</option>
                <option value="compact">Compact (sidebar icônes)</option>
                <option value="focus">Focus (chat seul)</option>
              </select>
            </div>
          </Section>

          {/* Performances */}
          <Section title="Performances">
            <div className="settings-row">
              <label htmlFor="settings-streamingDelay">
                Délai streaming
                <span className="settings-hint">ms par token (0 = instantané)</span>
              </label>
              <div className="settings-input-group">
                <input
                  id="settings-streamingDelay"
                  type="number" min={0} max={100} step={5}
                  value={settings.streamingDelay}
                  onChange={e => settings.setStreamingDelay(Number(e.target.value))}
                  aria-label="Délai de streaming en millisecondes par token"
                />
                <span aria-hidden="true">ms</span>
              </div>
            </div>
          </Section>

          {/* Serveur LCCA */}
          <Section title="Serveur LCCA — MCP Python">
            <div className="settings-row">
              <label htmlFor="settings-workspace">Dossier workspace</label>
              <div className="settings-input-group">
                <input
                  id="settings-workspace"
                  type="text"
                  value={settings.workspacePath}
                  onChange={e => settings.setWorkspacePath(e.target.value)}
                  aria-label="Chemin du dossier workspace"
                />
                <button
                  onClick={handleBrowseWorkspace}
                  aria-label="Parcourir pour choisir le dossier workspace"
                  title="Parcourir"
                >
                  <span aria-hidden="true">📁</span>
                </button>
              </div>
            </div>

            <div className="settings-row">
              <label htmlFor="settings-python">Exécutable Python</label>
              <div className="settings-input-group">
                <input
                  id="settings-python"
                  type="text"
                  value={settings.pythonPath}
                  onChange={e => settings.setPythonPath(e.target.value)}
                  placeholder="Auto-détecté depuis le venv"
                  aria-label="Chemin vers l'exécutable Python"
                />
                <button
                  onClick={handleDetectPython}
                  disabled={detecting}
                  aria-label={detecting ? 'Détection en cours…' : 'Détecter Python automatiquement'}
                  title="Détecter Python"
                >
                  <span aria-hidden="true" className={detecting ? 'spin' : ''}>⟳</span>
                </button>
              </div>
            </div>

            <div className="settings-row">
              <label htmlFor="settings-autoStart">
                Démarrage automatique du serveur
              </label>
              <input
                id="settings-autoStart"
                type="checkbox"
                checked={settings.autoStartServer}
                onChange={e => settings.setAutoStartServer(e.target.checked)}
                aria-label="Démarrer le serveur MCP automatiquement au lancement"
              />
            </div>

            {/* TIMEOUT-RESTART-01 : redémarrage manuel du processus Python MCP */}
            <div className="settings-row">
              <label>
                Redémarrer le serveur
                <span className="settings-hint">Force la relance du processus Python MCP</span>
              </label>
              <button
                className="btn-danger"
                onClick={handleRestartServer}
                disabled={restarting}
                aria-label={restarting ? 'Redémarrage en cours…' : 'Redémarrer le serveur MCP Python'}
                title="Redémarrer le serveur MCP"
              >
                <span aria-hidden="true" className={restarting ? 'spin' : ''}>↺</span>
                {restarting ? ' Redémarrage…' : ' Redémarrer'}
              </button>
            </div>
          </Section>

          {/* Modèles en ligne */}
          <Section title="🌐 Modèles en ligne">
            <OnlineModelsPanel />
          </Section>

          {/* Auto-amélioration */}
          <Section title="🤖 Auto-amélioration">
            <SelfImprovePanel />
          </Section>

          {/* Voix — VOICE-10 */}
          <Section title="🎤 Voix">
            <div className="settings-row">
              <label htmlFor="settings-stt">
                Reconnaissance vocale (STT)
                <span className="settings-hint">faster-whisper local — port 8765</span>
              </label>
              <input
                id="settings-stt"
                type="checkbox"
                checked={sttEnabled}
                onChange={e => setSttEnabled(e.target.checked)}
                aria-label="Activer la reconnaissance vocale (STT)"
              />
            </div>
            <div className="settings-row">
              <label htmlFor="settings-tts">
                Synthèse vocale (TTS)
                <span className="settings-hint">Piper / Kokoro local — port 8766</span>
              </label>
              <input
                id="settings-tts"
                type="checkbox"
                checked={ttsEnabled}
                onChange={e => setTtsEnabled(e.target.checked)}
                aria-label="Activer la synthèse vocale (TTS)"
              />
            </div>
            {(sttEnabled || ttsEnabled) && (
              <p className="settings-hint" style={{ marginTop: 6 }}>
                Les services Python démarrent automatiquement. Raccourci micro : <kbd>Alt+V</kbd>.
              </p>
            )}
          </Section>

          {/* À propos */}
          <Section title="À propos">
            <p className="settings-about">LCCA Desktop v1.0.0</p>
            <p className="settings-about">McpServer V7 — LCCA V7.2.0</p>
            <p className="settings-about">100% local — connexion externe optionnelle (online_models.json)</p>
          </Section>

        </div>

        {/* ── Pied ────────────────────────────────────────────────────── */}
        <div className="modal-footer">
          <button className="btn-primary" onClick={onClose}>
            Fermer
          </button>
        </div>
      </div>
    </div>
  );
}
