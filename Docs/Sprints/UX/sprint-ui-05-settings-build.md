# Sprint UI-05 — Settings + Thème light + Modes layout + Build Windows
<!-- AI-READY | Sprint UI-05 | Version 1.0.0 | 2026-04-18 -->

## Contexte & objectif

Sprint de finalisation. On complète tout ce qui rend l'application utilisable
au quotidien et distribuable : SettingsModal, thème light, les 3 modes layout
(Standard/Compact/Focus), les préférences persistées, et l'installeur Windows.
C'est aussi le sprint du polish : animations, accessibilité WCAG AA, `prefers-reduced-motion`.

**Prérequis** : Sprint UI-04 vert.
**Livrable** : Installeur NSIS `LCCA-Desktop-Setup-1.0.0.exe`, application complète.

---

## Périmètre

| # | Fichier | Type | Description |
|---|---------|------|-------------|
| 1 | `src/components/SettingsModal.tsx` | CREATE | Modal paramètres complète |
| 2 | `src/stores/settingsStore.ts` | UPDATE | Persistence electron-store / IPC |
| 3 | `src/styles/globals.css` | UPDATE | Thème light + animations + WCAG |
| 4 | `src/components/Layout.tsx` | UPDATE | 3 modes (standard/compact/focus) |
| 5 | `src/styles/themes.css` | CREATE | Variables light theme |
| 6 | `src/styles/animations.css` | CREATE | fadeInUp, slideIn, pulse, reduced-motion |
| 7 | `electron/main.ts` | UPDATE | IPC settings persist/load + auto-detect python |
| 8 | `ui/electron-builder.yml` | CREATE | Config packaging Windows |
| 9 | `ui/assets/icon.ico` | NOTE | Icône Windows (fichier à fournir manuellement) |
| 10 | `src/components/App.tsx` | UPDATE | Chargement settings au démarrage |

---

## Tâche 1 — SettingsModal

### `src/components/SettingsModal.tsx`

Spec : `spec-ui-03-composants.md` section 7.

```tsx
interface SettingsSection {
  title: string;
  children: React.ReactNode;
}

function Section({ title, children }: SettingsSection) {
  return (
    <div className="settings-section">
      <h3 className="settings-section-title">{title}</h3>
      {children}
    </div>
  );
}

export function SettingsModal({ onClose }: { onClose: () => void }) {
  const settings = useSettingsStore();

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-content settings-modal" role="dialog" aria-label="Paramètres">
        <div className="modal-header">
          <h2>⚙ Paramètres</h2>
          <button onClick={onClose} aria-label="Fermer">×</button>
        </div>

        <div className="settings-body">
          <Section title="Apparence">
            <div className="settings-row">
              <label>Thème</label>
              <div className="radio-group" role="radiogroup" aria-label="Thème">
                <label>
                  <input type="radio" name="theme" value="dark"
                    checked={settings.theme === 'dark'}
                    onChange={() => settings.setTheme('dark')} />
                  🌙 Sombre
                </label>
                <label>
                  <input type="radio" name="theme" value="light"
                    checked={settings.theme === 'light'}
                    onChange={() => settings.setTheme('light')} />
                  ☀ Clair
                </label>
              </div>
            </div>

            <div className="settings-row">
              <label>Taille du texte</label>
              <div className="radio-group" role="radiogroup" aria-label="Taille texte">
                {(['sm', 'md', 'lg'] as const).map(size => (
                  <label key={size}>
                    <input type="radio" name="fontSize" value={size}
                      checked={settings.fontSize === size}
                      onChange={() => settings.setFontSize(size)} />
                    {size === 'sm' ? 'Petit' : size === 'md' ? 'Normal' : 'Grand'}
                  </label>
                ))}
              </div>
            </div>

            <div className="settings-row">
              <label>Disposition</label>
              <select value={settings.panelMode}
                      onChange={e => settings.setPanelMode(e.target.value as any)}
                      aria-label="Mode disposition">
                <option value="standard">Standard (3 panneaux)</option>
                <option value="compact">Compact (sidebar icônes)</option>
                <option value="focus">Focus (chat seul)</option>
              </select>
            </div>
          </Section>

          <Section title="Performances">
            <div className="settings-row">
              <label htmlFor="streamingDelay">
                Délai streaming
                <span className="settings-hint">ms par token (0 = instantané)</span>
              </label>
              <div className="settings-input-group">
                <input id="streamingDelay" type="number" min={0} max={100} step={5}
                       value={settings.streamingDelay}
                       onChange={e => settings.setStreamingDelay(Number(e.target.value))} />
                <span>ms</span>
              </div>
            </div>
          </Section>

          <Section title="Serveur LCCA">
            <div className="settings-row">
              <label htmlFor="workspacePath">Dossier workspace</label>
              <div className="settings-input-group">
                <input id="workspacePath" type="text" value={settings.workspacePath}
                       onChange={e => settings.setWorkspacePath(e.target.value)} />
                <button onClick={handleBrowseWorkspace} aria-label="Parcourir">📁</button>
              </div>
            </div>

            <div className="settings-row">
              <label htmlFor="pythonPath">Exécutable Python</label>
              <div className="settings-input-group">
                <input id="pythonPath" type="text" value={settings.pythonPath}
                       placeholder="Auto-détecté" readOnly />
                <button onClick={handleDetectPython} aria-label="Détecter Python">⟳</button>
              </div>
            </div>

            <div className="settings-row">
              <label htmlFor="autoStart">Démarrage automatique du serveur</label>
              <input id="autoStart" type="checkbox" checked={settings.autoStartServer}
                     onChange={e => settings.setAutoStartServer(e.target.checked)} />
            </div>
          </Section>

          <Section title="À propos">
            <p className="settings-about">LCCA Desktop v1.0.0</p>
            <p className="settings-about">McpServer V7.2 — LCCA V7.2.0</p>
            <p className="settings-about">100% local — aucune connexion externe</p>
          </Section>
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="btn-primary">Fermer</button>
        </div>
      </div>
    </div>
  );
}
```

**Handlers** :
```typescript
async function handleBrowseWorkspace() {
  // Utiliser le dialog Electron (IPC)
  const path = await (window as any).lcca.browseDirectory();
  if (path) settings.setWorkspacePath(path);
}

async function handleDetectPython() {
  const path = await (window as any).lcca.detectPython();
  if (path) settings.setPythonPath(path);
}
```

Ajouter dans `preload.ts` :
```typescript
browseDirectory: () => ipcRenderer.invoke('dialog:browseDirectory'),
detectPython:    () => ipcRenderer.invoke('settings:detectPython'),
```

Ajouter dans `main.ts` :
```typescript
ipcMain.handle('dialog:browseDirectory', async () => {
  const result = await dialog.showOpenDialog(win!, { properties: ['openDirectory'] });
  return result.filePaths[0] ?? null;
});

ipcMain.handle('settings:detectPython', async () => {
  // Chercher dans l'ordre : venv\Scripts\python.exe, venv\bin\python, where python
  const candidates = [
    join(workspacePath, 'venv', 'Scripts', 'python.exe'), // Windows
    join(workspacePath, 'venv', 'bin', 'python'),         // Linux/Mac
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  return null;
});
```

---

## Tâche 2 — Persistence settings

### IPC settings dans `main.ts`

```typescript
import Store from 'electron-store'; // à ajouter dans package.json
const store = new Store();

ipcMain.handle('settings:save', (_event, settings: object) => {
  store.set('settings', settings);
});

ipcMain.handle('settings:load', () => {
  return store.get('settings') ?? null;
});
```

Ajouter `"electron-store": "^8.1.0"` dans `package.json`.

### `settingsStore.ts` — persist() + load()

```typescript
persist: async () => {
  const state = useSettingsStore.getState();
  await (window as any).lcca.invoke('settings:save', {
    theme: state.theme,
    panelMode: state.panelMode,
    fontSize: state.fontSize,
    streamingDelay: state.streamingDelay,
    autoStartServer: state.autoStartServer,
    workspacePath: state.workspacePath,
    pythonPath: state.pythonPath,
  });
},

load: async () => {
  const saved = await (window as any).lcca.invoke('settings:load');
  if (saved) useSettingsStore.setState({ ...saved });
},
```

Appeler `load()` dans `App.tsx` au premier `useEffect`.
Appeler `persist()` dans chaque setter (debounce 300ms).

---

## Tâche 3 — Thème light

### `src/styles/themes.css`

```css
/* ── Thème DARK (défaut) ── */
:root, [data-theme="dark"] {
  --bg-primary:      #1a1a2e;
  --bg-secondary:    #16213e;
  --bg-surface:      #0f3460;
  --bg-input:        #1e1e2e;
  --accent:          #e94560;
  --accent-soft:     #533483;
  --text-primary:    #eaeaea;
  --text-secondary:  #a8a8b3;
  --text-muted:      #666680;
  --border:          #2a2a4a;
  --success:         #4ade80;
  --warning:         #fbbf24;
  --error:           #f87171;
  --code-bg:         #0d1117;
  /* highlight.js theme : github-dark */
  --hljs-theme:      'github-dark';
}

/* ── Thème LIGHT ── */
[data-theme="light"] {
  --bg-primary:      #f8f9fa;
  --bg-secondary:    #ffffff;
  --bg-surface:      #e9ecef;
  --bg-input:        #ffffff;
  --accent:          #e94560;
  --accent-soft:     #7c3aed;
  --text-primary:    #1a1a2e;
  --text-secondary:  #4a4a6a;
  --text-muted:      #9494aa;
  --border:          #dee2e6;
  --success:         #16a34a;
  --warning:         #d97706;
  --error:           #dc2626;
  --code-bg:         #f6f8fa;
  --hljs-theme:      'github';
}
```

### Application du thème

Dans `App.tsx` :
```tsx
useEffect(() => {
  document.documentElement.setAttribute('data-theme', theme);
}, [theme]);
```

Pour highlight.js : charger `github-dark.min.css` ou `github.min.css` dynamiquement
selon `--hljs-theme`. En pratique, inclure les deux et switcher via une classe sur `<html>`.

---

## Tâche 4 — Taille de police

Dans `App.tsx`, appliquer le multiplicateur de taille :

```tsx
useEffect(() => {
  const size = { sm: '12px', md: '14px', lg: '16px' }[fontSize];
  document.documentElement.style.setProperty('--font-size-base', size);
  // Recalculer les dépendants
  const xs  = { sm: '10px', md: '11px', lg: '13px' }[fontSize];
  const sm  = { sm: '11px', md: '13px', lg: '15px' }[fontSize];
  document.documentElement.style.setProperty('--font-size-xs', xs);
  document.documentElement.style.setProperty('--font-size-sm', sm);
}, [fontSize]);
```

---

## Tâche 5 — Modes layout (3 modes)

### `src/components/Layout.tsx` — implémentation complète

```tsx
export function Layout() {
  const { panelMode } = useSettingsStore();

  const gridTemplate = {
    standard: '52px 1fr 280px',
    compact:  '52px 1fr 0px',
    focus:    '0px  1fr 0px',
  }[panelMode];

  return (
    <div className="layout" style={{ gridTemplateColumns: gridTemplate }}
         data-mode={panelMode}>
      {panelMode !== 'focus' && <Sidebar />}
      <ChatPanel />
      {panelMode === 'standard' && <ContextPanel />}
    </div>
  );
}
```

CSS :
```css
.layout {
  display: grid;
  height: 100vh;
  overflow: hidden;
  transition: grid-template-columns 250ms ease-in-out;
}
@media (prefers-reduced-motion: reduce) {
  .layout { transition: none; }
}
```

**Raccourci `Ctrl+Shift+F`** : bascule entre `focus` et `standard`.
**`Ctrl+\`** : toggle entre `standard` et `compact`.

---

## Tâche 6 — Animations

### `src/styles/animations.css`

```css
/* fadeInUp — apparition bulles messages */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
.message-bubble { animation: fadeInUp 150ms ease-out; }

/* slideIn — TxBadge et SpecBadge */
@keyframes slideIn {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
.tx-badge, .spec-badge { animation: slideIn 200ms ease-out; }

/* fadeIn — modals */
@keyframes fadeIn {
  from { opacity: 0; }
  to   { opacity: 1; }
}
@keyframes scaleIn {
  from { opacity: 0; transform: scale(0.95); }
  to   { opacity: 1; transform: scale(1); }
}
.modal-overlay  { animation: fadeIn  150ms ease-out; }
.modal-content  { animation: scaleIn 150ms ease-out; }

/* pulse — status indicator */
@keyframes statusPulse {
  0%, 100% { box-shadow: 0 0 0 0 currentColor; }
  50%       { box-shadow: 0 0 0 4px transparent; }
}
.status-connecting { animation: statusPulse 2000ms ease-in-out infinite; }

/* Respect prefers-reduced-motion — WCAG 2.1 AA */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## Tâche 7 — Accessibilité (finitions WCAG AA)

Vérifications à effectuer sur tous les composants :

| Élément | Exigence | Correction si manquante |
|---------|----------|------------------------|
| Boutons icône | `aria-label` obligatoire | Ajouter `aria-label="..."` |
| MessageList | `role="log"` | Ajouter sur le conteneur |
| Bulles streaming | `aria-live="polite"` | Ajouter sur la bulle en cours |
| Modals | `role="dialog"` + `aria-modal="true"` + focus trap | Vérifier chaque modal |
| Focus trap modal | Tab ne sort pas de la modal | Implémenter `useFocusTrap()` |
| Contraste texte | Ratio ≥ 4.5:1 (texte normal) | Vérifier avec outil contrast checker |
| Navigation clavier | Tous les éléments interactifs atteignables au Tab | Vérifier tabIndex |
| Icônes décoratives | `aria-hidden="true"` | Ajouter sur émojis et icônes pures |

### `useFocusTrap` hook

```typescript
export function useFocusTrap(ref: React.RefObject<HTMLElement>, active: boolean) {
  useEffect(() => {
    if (!active || !ref.current) return;
    const el = ref.current;
    const focusable = el.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    first?.focus();

    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Tab') return;
      if (e.shiftKey) { if (document.activeElement === first) { e.preventDefault(); last.focus(); } }
      else            { if (document.activeElement === last)  { e.preventDefault(); first.focus(); } }
    }
    el.addEventListener('keydown', onKey);
    return () => el.removeEventListener('keydown', onKey);
  }, [active]);
}
```

Appliquer dans `SettingsModal`, `SpecDetailModal`, `FileViewModal`, `CommandPalette`.

---

## Tâche 8 — Build & packaging Windows

### `ui/electron-builder.yml`

```yaml
appId: com.lcca.desktop
productName: LCCA Desktop
copyright: LCCA

directories:
  buildResources: assets
  output: dist

files:
  - dist-electron/**/*
  - dist-renderer/**/*
  - node_modules/**/*

win:
  target:
    - target: nsis
      arch: [x64]
  icon: assets/icon.ico

nsis:
  oneClick: false
  allowToChangeInstallationDirectory: true
  installerIcon: assets/icon.ico
  uninstallerIcon: assets/icon.ico
  installerHeaderIcon: assets/icon.ico
  createDesktopShortcut: true
  createStartMenuShortcut: true
  shortcutName: LCCA Desktop

publish: null   # pas de mise à jour auto — distribution manuelle
```

### Script `package.json` (mise à jour)

```json
"scripts": {
  "dev":        "electron-vite dev",
  "build":      "electron-vite build",
  "dist":       "electron-builder --win",
  "dist:dir":   "electron-builder --win --dir",
  "typecheck":  "tsc --noEmit"
}
```

### Icône Windows

Fournir `ui/assets/icon.ico` (256×256, multi-resolution).
Format recommandé : ICO multi-taille (16, 32, 48, 64, 128, 256px).
Hexagone LCCA (⬡) avec couleur `#e94560` sur fond `#1a1a2e`.

### Commande build finale

```powershell
cd D:\LLMCodeAgent\ui
npm run build
npm run dist
# → D:\LLMCodeAgent\ui\dist\LCCA-Desktop-Setup-1.0.0.exe
```

---

## Tâche 9 — Tests manuels end-to-end (checklist finale)

### Flux complet à valider avant release

| Scénario | Étapes | Attendu |
|----------|--------|---------|
| **Premier lancement** | Ouvrir l'exe, pas de settings existants | Thème dark, workspace auto-détecté, McpServer démarré |
| **Connexion MCP** | Attendre 3s après lancement | ● Connecté dans TitleBar |
| **Chat basique** | Taper "liste les fichiers core/" + Enter | Réponse formatée, streaming visible |
| **Génération spec** | Taper "@spec refactoriser orchestrator domain:orchestration" | SpecBadge visible, spec dans ContextPanel/Specs |
| **Voir spec** | Cliquer [Voir] sur SpecBadge | SpecDetailModal avec Markdown rendu |
| **Exporter spec** | Cliquer [Exporter .md] | Téléchargement spec-xxx.md |
| **Sandbox** | Taper "run: print('hello LCCA')" | SandboxResult avec stdout |
| **Erreur timeout** | Désactiver Ollama, taper une commande | Message timeout après 30s |
| **Reconnexion** | Tuer le serveur Python manuellement | ErrorBanner → reconnexion auto → disparaît |
| **Rollback TX** | Simuler une TX committed, cliquer ↩ | Dialog confirmation → TX rolled_back |
| **Palette commandes** | Ctrl+K + taper "spec" | Actions filtrées, Enter lance |
| **Thème light** | Settings → Clair | Toute l'interface bascule |
| **Mode focus** | Ctrl+Shift+F | Sidebar et ContextPanel masqués |
| **Redémarrage** | Fermer et rouvrir | Sessions persistées, settings conservés |
| **Accessibilité** | Navigation Tab seule | Tous les éléments atteignables |
| **Reduced motion** | OS: réduire animations | Aucune animation (transitions 0.01ms) |

---

## Critères d'acceptance Sprint UI-05

| Critère | Validation |
|---------|-----------|
| SettingsModal ouvre et ferme (Ctrl+,) | Manuel |
| Changement thème → appliqué en temps réel | Manuel |
| Settings persistés après redémarrage Electron | Manuel |
| Thème light : contraste WCAG AA vérifié | Outil contrast |
| 3 modes layout fonctionnels avec transition | Manuel |
| Taille de police 3 niveaux | Manuel |
| Toutes les animations respectent prefers-reduced-motion | Manuel |
| Focus trap dans toutes les modals | Manuel |
| `npm run dist` produit l'exe sans erreur | Manuel |
| Installeur NSIS crée un shortcut bureau | Manuel |
| Application fonctionnelle après installation | Manuel |
| Checklist end-to-end complète ✓ | Manuel |

---

## Récapitulatif complet — 5 sprints UI

| Sprint | Livrable principal | Composants créés |
|--------|-------------------|-----------------|
| UI-01 | Shell Electron + MCP Bridge + Chat brut | TitleBar, Layout, ChatPanel, InputZone, Sidebar stub, ContextPanel stub |
| UI-02 | Markdown + TxBadge + SpecBadge + Sessions | MarkdownRenderer, CodeBlock, TxBadge, SpecBadge, StreamingIndicator, SessionList |
| UI-03 | ContextPanel complet | FileTree, SpecCard, SpecDetailModal, TxCard, FileViewModal |
| UI-04 | CommandPalette + Routing MCP + Erreurs | CommandPalette, ErrorBanner, router.ts, mcpFormatter.ts |
| UI-05 | Settings + Thème light + Build Windows | SettingsModal, animations.css, themes.css, useFocusTrap, installeur |

<!-- AI-READY | Sprint UI-05 Settings + Thème light + Build Windows | Version 1.0.0 | 2026-04-18 -->
