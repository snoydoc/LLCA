# Sprint PROD-01 — Build & Packaging Windows
# Créé : 2026-04-19
# Statut : ✅ TERMINÉ

## 🎯 Objectif
Produire un installeur Windows `.exe` fonctionnel via `npm run dist`.
L'app doit se lancer, connecter le MCP Python, et afficher l'UI correctement.

## 📋 Tâches

### Pré-requis vérifiés
- [x] `AdhamIcon.ico` existant dans `imgs/` (converti manuellement — 4.19 KB)
- [x] `out/` à jour (electron-vite build précédent valide)
- [x] `node_modules/` présent

### Corrections appliquées

| # | Fichier | Problème | Fix |
|---|---------|----------|-----|
| 1 | `electron/main.ts` | Chemin renderer prod incorrect : `../out/renderer` depuis `out/main/` | → `../../renderer` |
| 2 | `electron/main.ts` | Icône runtime `.png` → `.ico` | → `AdhamIcon.ico` |
| 3 | `electron-builder.yml` | `node_modules/**/*` dans files → emballe devDependencies | Supprimé (electron-builder gère auto) |
| 4 | `electron-builder.yml` | `installerHeaderIcon` → erreur NSIS (format attendu 150×57px) | Supprimé |
| 5 | `package.json` | Champs `author` et `description` manquants (peut bloquer electron-builder) | Ajoutés |
| 6 | `make_ico.py` | Généraitdans `assets/icon.ico` au lieu de `imgs/AdhamIcon.ico` | Corrigé |
| 7 | `ui/assets/` | Dossier `buildResources` inexistant | Créé avec README.md |

### Fichiers créés
- `ui/build-prod.ps1` — Script PowerShell guidé en 5 étapes (ICO check → npm install → build → dist → résultat)
- `ui/assets/README.md` — Documentation du dossier buildResources
- `Docs/Sprints/sprint-prod-01-build-windows.md` — Ce fichier

## 🚀 Procédure de build

```powershell
# Depuis D:\LLMCodeAgent\ui\
.\build-prod.ps1
```

Ou manuellement :
```powershell
cd D:\LLMCodeAgent\ui
npm run build          # Compile TS + React → out/
npm run dist           # Packaging → dist/Adham Desktop Setup 1.0.0.exe
```

## 🏗️ Architecture du build

```
electron-vite build
  → out/main/main.js          (Electron main process)
  → out/preload/preload.js    (contextBridge)
  → out/renderer/index.html   (React app compilée)

electron-builder --win
  → Lit package.json (main: "out/main/main.js")
  → Emballe out/ + dependencies (pas devDependencies)
  → Icône : imgs/AdhamIcon.ico
  → Installeur NSIS : dist/Adham Desktop Setup 1.0.0.exe
```

## ⚠️ Blocages connus & solutions

| Symptôme | Cause probable | Solution |
|----------|---------------|----------|
| Fenêtre blanche au lancement | Chemin renderer incorrect | Vérifier `join(__dirname, '../../renderer/index.html')` |
| "MCP introuvable" au lancement | Workspace path absent de settings | Configurer Settings → Workspace dans l'UI |
| Icône manquante dans taskbar | `.ico` absent ou corrompu | `python make_ico.py` |
| Build lent (>10 min) | Premier build = téléchargement Electron binaries | Normal, subsequent builds < 2 min |
| Erreur NSIS installer | NSIS non installé | `npm run dist:dir` (sans installeur NSIS) |

## 🔒 Contraintes prod

- **Workspace** : l'app utilise `store.get('settings').workspacePath` avec fallback `D:\\LLMCodeAgent`
  → Configurable via Settings dans l'UI après installation
- **Python/venv** : `mcp-bridge.ts` cherche `{workspace}/venv/Scripts/python.exe`
  → Variable d'env `LCCA_PYTHON` pour override
- **Ollama** : doit être lancé manuellement avant d'ouvrir l'app
  → Pas de vérification au démarrage (silencieux, retry)

## 📊 Résultat attendu

```
dist/
├── Adham Desktop Setup 1.0.0.exe   (~120-180 MB avec Electron)
└── win-unpacked/                    (optionnel avec dist:dir)
    ├── Adham Desktop.exe
    └── resources/
        └── app.asar
```
