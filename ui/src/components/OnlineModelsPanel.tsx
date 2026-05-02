// OnlineModelsPanel.tsx — ROUTER-04
// Panneau de configuration des modeles en ligne (Kimi, OpenRouter, etc.)
// Integre dans SettingsModal.tsx comme section "Modeles en ligne".
//
// Invariants :
//   - Les cles API ne transitent jamais vers ce composant (has_key = booleen masque)
//   - L'activation d'un provider ecrit dans online_models.json via IPC
//   - Le test de connexion est fait cote main process (cle jamais dans le renderer)
import { useState, useEffect, useCallback } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface ProviderPublic {
  id:             string;
  name:           string;
  description:    string;
  online:         boolean;
  roles:          string[];
  min_complexity: number;
  has_key:        boolean;  // true = cle presente dans electron-store (valeur masquee)
}

interface RoutingConfig {
  enabled:           boolean;
  fallback_to_local: boolean;
  thresholds?: {
    use_heavy_local: number;
    use_online:      number;
    force_online:    number;
  };
}

type TestStatus = 'idle' | 'testing' | 'ok' | 'error';

// ── Sous-composant : carte d'un provider ─────────────────────────────────────

function ProviderCard({
  provider,
  onToggle,
  onSetKey,
  onTest,
}: {
  provider:  ProviderPublic;
  onToggle:  (id: string, enabled: boolean) => void;
  onSetKey:  (id: string, key: string) => void;
  onTest:    (id: string) => void;
}) {
  const [editingKey, setEditingKey] = useState(false);
  const [keyInput,   setKeyInput]   = useState('');
  const [testStatus, setTestStatus] = useState<TestStatus>('idle');
  const [testMsg,    setTestMsg]    = useState('');

  const handleSaveKey = () => {
    if (keyInput.trim()) {
      onSetKey(provider.id, keyInput.trim());
      setKeyInput('');
    }
    setEditingKey(false);
  };

  const handleTest = async () => {
    setTestStatus('testing');
    setTestMsg('');
    const lcca = (window as unknown as { lcca: { onlineModels: { testProvider: (id: string) => Promise<{ ok: boolean; latency_ms?: number; error?: string }> } } }).lcca;
    const result = await lcca.onlineModels.testProvider(provider.id);
    if (result.ok) {
      setTestStatus('ok');
      setTestMsg(`✓ Connecte (${result.latency_ms ?? 0}ms)`);
    } else {
      setTestStatus('error');
      setTestMsg(`✗ ${result.error ?? 'Erreur reseau'}`);
    }
    // Reset apres 4s
    setTimeout(() => { setTestStatus('idle'); setTestMsg(''); }, 4000);
  };

  // Badge statut
  const badge = () => {
    if (testStatus === 'testing') return <span className="om-badge om-badge--testing">Test…</span>;
    if (testStatus === 'ok')      return <span className="om-badge om-badge--ok">{testMsg}</span>;
    if (testStatus === 'error')   return <span className="om-badge om-badge--error">{testMsg}</span>;
    if (!provider.online)         return <span className="om-badge om-badge--off">Desactive</span>;
    if (!provider.has_key)        return <span className="om-badge om-badge--warn">Cle manquante</span>;
    return <span className="om-badge om-badge--ready">Pret</span>;
  };

  return (
    <div className={`om-card ${provider.online ? 'om-card--active' : 'om-card--inactive'}`}>
      {/* Ligne titre + toggle + test */}
      <div className="om-card-header">
        <span className="om-card-name">🌐 {provider.name}</span>
        <div className="om-card-controls">
          {badge()}
          <label className="om-toggle" title={provider.online ? 'Desactiver' : 'Activer'}>
            <input
              type="checkbox"
              checked={provider.online}
              onChange={e => onToggle(provider.id, e.target.checked)}
              aria-label={`${provider.online ? 'Desactiver' : 'Activer'} ${provider.name}`}
            />
            <span className="om-toggle-slider" />
          </label>
          <button
            className="om-btn-test"
            onClick={handleTest}
            disabled={!provider.online || !provider.has_key || testStatus === 'testing'}
            title="Tester la connexion"
            aria-label={`Tester la connexion avec ${provider.name}`}
          >
            {testStatus === 'testing' ? '⟳' : 'Tester'}
          </button>
        </div>
      </div>

      {/* Description + meta */}
      <p className="om-card-desc">{provider.description}</p>
      <div className="om-card-meta">
        <span>Roles : {provider.roles.join(', ')}</span>
        <span>Complexite min : {provider.min_complexity}/10</span>
      </div>

      {/* Zone cle API */}
      <div className="om-key-row">
        <span className="om-key-label">Cle API :</span>
        {editingKey ? (
          <>
            <input
              type="password"
              className="om-key-input"
              value={keyInput}
              onChange={e => setKeyInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSaveKey(); if (e.key === 'Escape') setEditingKey(false); }}
              placeholder="Coller la cle API ici…"
              autoFocus
              aria-label="Cle API"
            />
            <button className="om-btn-sm" onClick={handleSaveKey}>Enregistrer</button>
            <button className="om-btn-sm om-btn-sm--cancel" onClick={() => setEditingKey(false)}>Annuler</button>
          </>
        ) : (
          <>
            <span className="om-key-mask">{provider.has_key ? '••••••••••••' : '(aucune)'}</span>
            <button
              className="om-btn-sm"
              onClick={() => setEditingKey(true)}
              aria-label={`Modifier la cle API de ${provider.name}`}
            >
              {provider.has_key ? 'Modifier' : 'Ajouter'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Composant principal ───────────────────────────────────────────────────────

export function OnlineModelsPanel() {
  const [providers,      setProviders]      = useState<ProviderPublic[]>([]);
  const [routing,        setRouting]        = useState<RoutingConfig>({ enabled: false, fallback_to_local: true });
  const [loading,        setLoading]        = useState(true);
  const [savingRouting,  setSavingRouting]  = useState(false);

  const lcca = (window as unknown as {
    lcca: {
      onlineModels: {
        getConfig:         () => Promise<{ providers: ProviderPublic[]; routing: RoutingConfig }>;
        setEnabled:        (id: string, enabled: boolean) => Promise<{ ok: boolean }>;
        setRoutingEnabled: (enabled: boolean) => Promise<{ ok: boolean }>;
        setKey:            (id: string, key: string) => Promise<{ ok: boolean }>;
        testProvider:      (id: string) => Promise<{ ok: boolean; latency_ms?: number; error?: string }>;
      };
    };
  }).lcca;

  const load = useCallback(async () => {
    try {
      const cfg = await lcca.onlineModels.getConfig();
      setProviders(cfg.providers ?? []);
      setRouting(cfg.routing ?? { enabled: false, fallback_to_local: true });
    } catch (err) {
      console.error('[OnlineModelsPanel] load error:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleToggle = async (id: string, enabled: boolean) => {
    await lcca.onlineModels.setEnabled(id, enabled);
    await load();
  };

  const handleSetKey = async (id: string, key: string) => {
    await lcca.onlineModels.setKey(id, key);
    await load();
  };

  const handleToggleRouting = async () => {
    setSavingRouting(true);
    await lcca.onlineModels.setRoutingEnabled(!routing.enabled);
    await load();
    setSavingRouting(false);
  };

  if (loading) {
    return <p className="om-loading">Chargement des providers…</p>;
  }

  return (
    <div className="om-panel">
      {/* Toggle routing global */}
      <div className="om-routing-row">
        <div className="om-routing-info">
          <strong>Routing automatique</strong>
          <span className="settings-hint">
            Selectionne automatiquement le modele selon la complexite de la tache
          </span>
        </div>
        <label className="om-toggle" title={routing.enabled ? 'Desactiver le routing' : 'Activer le routing'}>
          <input
            type="checkbox"
            checked={routing.enabled}
            onChange={handleToggleRouting}
            disabled={savingRouting}
            aria-label="Activer ou desactiver le routing automatique"
          />
          <span className="om-toggle-slider" />
        </label>
      </div>

      {routing.enabled && routing.thresholds && (
        <p className="om-routing-hint">
          Local leger : score &lt; {routing.thresholds.use_heavy_local * 10} &nbsp;|&nbsp;
          Local lourd : {routing.thresholds.use_heavy_local * 10}–{routing.thresholds.use_online * 10 - 1} &nbsp;|&nbsp;
          Online : &ge; {routing.thresholds.use_online * 10}
        </p>
      )}

      <div className="om-separator" />

      {/* Liste des providers */}
      {providers.length === 0 ? (
        <p className="om-empty">Aucun provider configure dans online_models.json</p>
      ) : (
        providers.map(p => (
          <ProviderCard
            key={p.id}
            provider={p}
            onToggle={handleToggle}
            onSetKey={handleSetKey}
            onTest={() => {}}  // le test est gere dans la carte elle-meme
          />
        ))
      )}

      <p className="om-footer-hint">
        Pour ajouter un provider : editer <code>online_models.json</code> a la racine du projet.
      </p>
    </div>
  );
}
