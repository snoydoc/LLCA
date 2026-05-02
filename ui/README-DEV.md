# LCCA Desktop — Guide développeur

## Démarrage rapide

```powershell
cd D:\LLMCodeAgent\ui
npm run dev
```

Electron + Vite démarre en mode développement. Le renderer (React) bénéficie du HMR
instantané. Le main process et le preload sont compilés en TypeScript et rechargés
automatiquement quand un fichier change dans `electron/`.

---

## Rechargement à chaud (HMR)

### Renderer (`src/`)
Rechargé **instantanément** sans redémarrage — hot module replacement Vite standard.

### Main process (`electron/main.ts`, `electron/mcp-bridge.ts`, etc.)
Rechargé **automatiquement** par electron-vite watch (configuré dans `electron.vite.config.ts`).
Electron est relancé après chaque modification de fichier dans `electron/`.

> **Note** : le rechargement du main process entraîne un redémarrage du process Python MCP.
> Attendre que la barre de statut affiche « Connecté » avant d'envoyer une commande.

### Preload (`electron/preload.ts`)
Rechargé automatiquement avec le main process.

---

## Redémarrage manuel du serveur MCP

Si le serveur Python MCP se retrouve dans un état incohérent (crash, timeout) :

**Via l'UI** : Paramètres (⚙) → Section "Serveur LCCA — MCP Python" → bouton **↺ Redémarrer**

**Via IPC depuis la DevTools console** :
```javascript
await window.lcca.restartServer()
```

**Via PowerShell** (si l'UI est inaccessible) :
```powershell
# Tuer le process Python et relancer npm run dev
Get-Process python | Stop-Process -Force
```

---

## Redémarrage Electron complet

Nécessaire uniquement si `main.ts` lui-même est modifié d'une façon qui ne peut pas
être rechargée à chaud (ex: changement de la configuration de la `BrowserWindow`).

```powershell
# Dans le terminal npm run dev : Ctrl+C, puis :
npm run dev
```

---

## Variables d'environnement utiles

| Variable | Usage |
|---|---|
| `LCCA_PYTHON` | Forcer un exécutable Python spécifique (ex: `D:\mon\venv\python.exe`) |
| `ELECTRON_RENDERER_URL` | Injecté automatiquement par electron-vite en dev |
| `NODE_ENV` | `development` en dev, `production` en build |
| `OLLAMA_NEW_ENGINE` | Forcé à `0` (désactive le nouveau moteur CUDA, Quadro M2000M) |
| `OLLAMA_NUM_GPU` | Forcé à `0` (mode CPU) |

---

## Structure des process

```
npm run dev
├── Electron main process  (electron/main.ts)
│   └── McpBridge          (electron/mcp-bridge.ts)
│       └── Python MCP     (core/mcp_server.py)  ← process fils
└── Vite dev server        (renderer React HMR)
    └── BrowserWindow      (src/)
```

---

## Build production

```powershell
.\build-prod.ps1
```

Voir le contenu du script pour les 5 étapes détaillées (typecheck → build → dist).
