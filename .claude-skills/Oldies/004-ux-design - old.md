# ADHAM DESKTOP — DESIGN SYSTEM SPEC (rétro-ingénierie 2026-04-21)
# Source : adham_dual_theme_dark_light.html (4 pages : Layout, Composants, Welcome, Design System)
# Objectif : guide implémentation pour migrer la maquette HTML vers Electron/React

---

## 1. NOMS DE THÈMES
- Sombre : **"Terminal Forge"** (`class="dark"`)
- Clair  : **"Forge Papier"**  (`class="light"`)

---

## 2. DESIGN TOKENS (CSS variables — source de vérité : themes.css)

### Dark — "Terminal Forge"
```css
--bg0: #050509;       /* Void — barre titre, sidebar fond */
--bg1: #08080F;       /* Base — fond chat */
--bg2: #0D0D1A;       /* Panel — modales, palette commandes */
--bg3: #131320;       /* Surface — logo welcome */
--bg4: #1A1A2E;       /* Elevated — input, code bg */
--glass: rgba(255,255,255,0.035);
--b1:   rgba(255,255,255,0.055); /* bordure subtile */
--b2:   rgba(255,255,255,0.09);  /* bordure visible */
--b-acc: rgba(245,158,11,0.35);  /* bordure accent */
--t0: #F0F0F8;  /* texte principal */
--t1: #A8A8C0;  /* texte secondaire */
--t2: #5A5A78;  /* texte désactivé/meta */
--t3: #2E2E44;  /* texte fantôme */
--acc: #F59E0B;              /* ambre vif */
--acc-dim: rgba(245,158,11,0.12);
--acc-glow: rgba(245,158,11,0.06);
--acc-soft: #2A1F08;
--ok:   #34D399; --err:  #F87171; --info: #60A5FA; --warn: #FBBF24;
--code-bg: #04040B;
--shadow: 0 8px 32px rgba(0,0,0,0.7);
```

### Light — "Forge Papier"
```css
--bg0: #EEEAE2;  --bg1: #F5F2EC;  --bg2: #F8F6F1;
--bg3: #FFFFFF;  --bg4: #EDE9E0;
--glass: rgba(0,0,0,0.025);
--b1:   rgba(100,80,40,0.10);
--b2:   rgba(100,80,40,0.18);
--b-acc: rgba(180,83,9,0.40);
--t0: #1C1510;  --t1: #4A3F30;  --t2: #8A7A66;  --t3: #BFB5A8;
--acc: #B45309;              /* ambre brûlé */
--acc-dim: rgba(180,83,9,0.09);
--acc-glow: rgba(180,83,9,0.05);
--acc-soft: #FEF3C7;
--ok:   #047857; --err:  #B91C1C; --info: #1D4ED8; --warn: #B45309;
--code-bg: #EDE9DF;
--shadow: 0 4px 24px rgba(60,40,10,0.14);
```

---

## 3. TYPOGRAPHIE

| Rôle | Font | Taille | Poids | Notes |
|---|---|---|---|---|
| Display | Inter | 22px | 300 / **600** | letter-spacing: -0.04em |
| Titre | Inter | 14px | 500 | — |
| Corps | Inter | 12.5px | 400 | line-height: 1.65 |
| Meta / code inline | JetBrains Mono | 11px | 400 | color: --acc |
| Caption / labels | Inter | 9–9.5px | 600 | uppercase, letter-spacing: 0.10–0.12em |
| Pill / badge | JetBrains Mono | 9.5–10px | 500 | — |
| Hints / ghost | JetBrains Mono | 9px | 400 | color: --t3 |

---

## 4. LAYOUT PRINCIPAL

```
TitleBar (height: 34px, bg: --bg0)
└── macOS dots | gem | "Adham" | MCP pill | [spacer] | model | action btns

AppGrid (grid: 52px 1fr 240px)
├── Sidebar  (52px, bg: --bg0)
├── ChatPanel (flex-col, bg: --bg1)
└── ContextPanel (240px, bg: --bg0)
```

---

## 5. COMPOSANTS — SPECS

### TitleBar
- Hauteur : 34px | fond : `--bg0` | bordure bas : `--b1`
- **macOS dots** : rouge `#FF5F57`, jaune `#FEBC2E`, vert `#28C840` — Ø10px
- **Gem** : `clip-path: polygon(50% 0%, 100% 38%, 82% 100%, 18% 100%, 0% 38%)` — 13×13px, `--acc`, `drop-shadow(0 0 5px --acc)`
- **Nom** : "Adham" 11px 600 uppercase letterspacing 0.07em
- **MCP pill** : border `--b1`, radius 100px, dot vert pulsant (Ø5px, box-shadow `--ok`)
- **Modèle** : JetBrains Mono 9.5px, `--t3`
- **Btns action** : 26×26px radius 6px, hover `--glass`; bouton ✕ : `--err`
- **Toggle thème** : ☀ (dark→light) | 🌙 (light→dark)

### Sidebar (52px)
- fond : `--bg0` | bordure droite : `--b1`
- **sb-btn** : 34×34px radius 9px | `.on` : bg `--acc-dim`, color `--acc`, barre gauche 2px `--acc`
- **sb-session** : 26×26px radius 7px, JetBrains Mono 9px | `.on` : bg `--acc-dim`, border `--b-acc`, color `--acc`
- **Divider** : 20px large, 1px, `--b1`
- Icônes nav : 💬 chat | 📁 fichiers | 📐 spec | ? aide | ⚙ settings

### ChatPanel
- fond : `--bg1` | messages : `padding: 4px 16px`, gap 9px (avatar + contenu)
- **Avatar utilisateur** : 22×22px radius 6px, bg `--acc-dim`, border `--b-acc`, lettre "A" en `--acc`
- **Avatar Adham** : bg `--glass`, border `--b1`, couleur `--t2`, symbole `⬡`
- **Meta** : JetBrains Mono 9.5px — rôle `--t1` bold, timestamp `--t3`
- **Texte user** : 12.5px `--t0` | **Texte Adham** : 12.5px `--t1`
- **Code inline** `.ic` : JetBrains Mono 11px, bg `--bg4`, border `--b1`, radius 4px, color `--acc`

### Code Block
- border `--b1`, radius 8px, bg `--code-bg`
- **Header** : flex, padding 5px 10px, bg `--glass`, border-bottom `--b1`
  - label langue : JetBrains Mono 9.5px `--acc` bold
  - nom fichier : JetBrains Mono 9.5px `--t3`, margin-left auto
- **Body** : padding 10px 12px, JetBrains Mono 11px, line-height 1.6
- **Coloration syntaxique** :
  | Token | Dark | Light |
  |---|---|---|
  | keyword | `#FF7B72` | `#A21C30` |
  | function | `#D2A8FF` | `#6D28D9` |
  | string | `#A5D6FF` | `#047857` |
  | comment | `#4A5568` italic | `#9C8F7A` italic |
  | number | `#79C0FF` | `#1D4ED8` |

### TX Badge
- pill 100px, bg `--glass`, border `--b1`, JetBrains Mono 9.5px, `--t2`
- dot Ø5px `--ok` | tx_id `--t1` bold | "N fichier · COMMIT"

### Spec Badge (`.spb`)
- bg `--glass`, border `--b1`, **border-left 2px `--acc`**, radius 8px
- Icône 📐 `--acc` 14px | titre 11.5px 500 `--t0` | meta JetBrains Mono 9.5px `--t2`
- **Score pill** : JetBrains Mono 10.5px 600, `--ok`, bg `rgba(ok,0.1)`, border `rgba(ok,0.2)`, radius 100px

### Streaming Indicator
- bg `--bg4`, border `--b1`, radius 12px, padding 7px 12px, margin 4px 16px
- 3 orbs Ø5px, animation pulse (scale 1→1.5, opacity 0.3→0.9, 1.5s), stagger 0.2s
- Texte JetBrains Mono 11px `--t2`

### InputZone
- border-top `--b1`, bg `--bg1`, padding 9px 14px
- **Wrapper `.iw`** : bg `--bg4`, border `--b2`, radius 13px, padding 8px 10px
  - `:focus-within` → border `--b-acc`
- **Textarea** : Inter 12.5px, placeholder `--t3`
- **Kbd hint** `.ik` : JetBrains Mono 9.5px, border `--b1`, radius 4px
- **Send btn** : 28×28px radius 7px, bg `--acc`, color `--bg0`, "↑"
- **Hint bar** : JetBrains Mono 9px `--t3` centré — "↩ envoyer · ⇧↩ nouvelle ligne · Esc annuler"

### ContextPanel (240px)
- bg `--bg0`, border-left `--b1`
- **Section header** : flex, padding 6px 10px, bg `--bg0` sticky
  - titre : 9px 600 uppercase letterspacing 0.1em `--t2`
  - action : 11px `--t3` cursor pointer (ex: "↺")
- **File tree item** `.fi` : JetBrains Mono 10.5px, padding 2px 10px, hover `--glass`
  - nom fichier `--t1` | dossier `--t2` | badge modifié `--acc` 8px
  - indent sous-dossier : `padding-left: 18px`
- **Spec card** `.sc` : padding 5px 10px, hover `--glass`
  - titre 11px 500 `--t0` | meta JetBrains Mono 9.5px `--t3`
  - icône état : ✅ validée | ⚠️ score < 0.8
- **MCP Bar** (bas panel) : JetBrains Mono 9.5px `--t2`, dot `--ok`, version pill border `--b1` 9px `--t3`

### Boutons
- **Primaire** `.btn-p` : bg `--acc`, color `--bg0`, radius 7px, 11px 600
- **Secondaire** `.btn-s` : bg `--glass`, border `--b2`, color `--t1`, radius 7px
- **Danger** `.btn-d` : bg fond `--err` dim, border `--err`, color `--err` (⚠ Redémarrer)

### Badges sémantiques
```
.badge : inline-flex, padding 3px 9px, radius 100px, JetBrains Mono 10px 500
badge-ok  : rgba(ok,0.1)  border rgba(ok,0.2)  color --ok   → "✓ Commit"
badge-acc : --acc-dim     border --b-acc         color --acc  → "⬡ Spec"
badge-err : rgba(err,0.1) border rgba(err,0.2)  color --err  → "✕ Erreur"
badge-inf : rgba(info,0.1) border rgba(info,0.2) color --info → "🌐 Web"
```
Light : bg/border ajustés avec les valeurs `--ok/#047857`, `--err/#B91C1C`, `--info/#1D4ED8`.

### Command Palette
- bg `--bg2`, border `--b2`, radius 12px, shadow `--shadow`
- **Input** : padding 10px 14px, border-bottom `--b1`
  - icône ⌕ `--t2` | input Inter 13px `--t0` | ESC pill JetBrains Mono 9.5px border `--b1`
- **Groupe** : 9px 600 uppercase letterspacing 0.1em `--t3`, padding 6px 9px 3px
- **Item** : padding 7px 9px, radius 7px, flex gap 8px
  - hover/`.sel` : bg `--glass` | `.sel` : bg `--acc-dim`
  - icône 12px centré 18px | nom Inter 12px flex-1 | raccourci JetBrains Mono 9.5px bg `--bg4` border `--b1`

### Form inputs
- bg `--bg4`, border `--b2`, radius 7px, padding 6px 10px, JetBrains Mono 12px `--t0`
- `:focus` → border `--b-acc`

### Toggle switch
- Track : 34×18px, bg `--bg4`, border `--b2`, radius 9px
- `.on` : bg `--acc`, border transparent
- Thumb : Ø12px, bg `--t2` | `.on` → left 18px, bg `--bg0`

---

## 6. WELCOME SCREEN

- Fond : `--bg1` | Grille CSS : `44px × 44px`
  - Dark : `rgba(255,255,255,0.018)` | Light : `rgba(100,80,40,0.07)`
- **Glow central** : radial-gradient ellipse 340×220px, top 30% centré
  - Dark : `rgba(245,158,11,0.05)` | Light : `rgba(180,83,9,0.06)`
- **Logo container** : 60×60px radius 16px, bg `--bg3`, border `--b2`, shadow `--shadow`
  - Animation : `float 4s ease-in-out infinite` (translateY 0 → -5px → 0)
- **Gem dans logo** : 26×26px, `--acc`, `drop-shadow(0 0 8px --acc)`
- **Titre** : 22px 300 letterspacing -0.04em, `--t0`, mot "Adham" en 600 `--acc`
- **Sous-titre** : JetBrains Mono 11.5px `--t2`, centré, line-height 1.7
- **Chips** : JetBrains Mono 10.5px, padding 4px 11px, radius 100px, bg `--bg4`, border `--b2`
  - hover : border `--b-acc`, color `--acc`, bg `--acc-dim`
  - Préfixe `@` en `--acc` | chips : @spec, @eval, @web, @file, Ctrl+K
- **Version badge** : dot Ø4px `--ok` + texte JetBrains Mono 9.5px `--t3`

---

## 7. ANIMATIONS & TRANSITIONS

| Élément | Animation | Durée |
|---|---|---|
| Gem logo welcome | `float` : translateY 0→-5px→0 | 4s ease-in-out ∞ |
| Streaming orbs | `orb` : scale 1→1.5, opacity 0.3→0.9 | 1.5s ∞, stagger 0.2s |
| Sidebar btn hover | color + bg | 0.15s |
| Input focus | border-color | 0.2s |
| Toggle thumb | left + bg | 0.2s |
| TitleBar btn hover | bg + color | 0.15s |

---

## 8. SCROLLBAR

Toutes les zones scrollables : `::-webkit-scrollbar { display: none }` (scroll invisible).

---

## 9. RACCOURCIS CLAVIER (documentés dans l'UI)

| Raccourci | Action |
|---|---|
| `Ctrl+K` | Ouvrir Command Palette |
| `↩` | Envoyer message |
| `⇧↩` | Nouvelle ligne |
| `Esc` | Annuler / fermer palette |
| `@spec` | Générer une spec |
| `@validate` | Valider une spec |
| `@eval` | Évaluer qualité code |
| `@web` | Recherche web |
| `@run` | Sandbox run |
| `@file` | Opération fichier |

---

## 10. MAPPING COMPOSANTS → FICHIERS REACT EXISTANTS

| Composant HTML | Fichier React actuel | Action requise |
|---|---|---|
| `.tb` TitleBar | `TitleBar.tsx` | Vérifier gem + pill + dots + toggle thème |
| `.sb` Sidebar | `Sidebar.tsx` | Vérifier sb-session + barre active |
| `.chat` ChatPanel | `ChatPanel.tsx` | — |
| `.msg` Message | `MessageBubble.tsx` | Avatar ⬡, meta format |
| `.cb` Code block | `CodeBlock.tsx` | Coloration syntaxique par thème |
| `.txb` TX badge | `TxBadge.tsx` | — |
| `.spb` Spec badge | `SpecBadge.tsx` | border-left acc, score pill |
| `.si` Streaming | `StreamingIndicator.tsx` | 3 orbs + animation |
| `.iz` Input zone | `InputZone.tsx` | wrapper focus + hint bar |
| `.ctx` Context panel | `ContextPanel.tsx` | File tree + spec cards + MCP bar |
| `.cpal` Command palette | `CommandPalette.tsx` | Groups + sel state + kbd |
| `.badge` Badges | inline dans composants | 4 variantes ok/acc/err/inf |
| Welcome screen | `WelcomeScreen.tsx` | Grid + glow + float + chips |
| — | `themes.css` | SOURCE DE VÉRITÉ tokens (voir §2) |

---

## 11. PROCHAINS SPRINTS SUGGÉRÉS (issues détectées à la rétro-ingénierie)

| ID | Composant | Gap identifié | Priorité |
|---|---|---|---|
| UI-DS-01 | `themes.css` | Vérifier que TOUS les tokens §2 sont présents et corrects | CRITIQUE |
| UI-DS-02 | `CodeBlock.tsx` | Coloration syntaxique doit être conditionnelle par thème | WARN |
| UI-DS-03 | `SpecBadge.tsx` | Score pill doit utiliser `--ok` (pas hardcodé vert) | WARN |
| UI-DS-04 | `WelcomeScreen.tsx` | Animation `float` sur logo container (pas juste la gem) | INFO |
| UI-DS-05 | `Sidebar.tsx` | Composant `.sb-session` (S1/S2/S3) absent ou non stylé | INFO |
| UI-DS-06 | `ContextPanel.tsx` | MCP bar en bas (position `margin-top: auto`) | INFO |
| UI-DS-07 | `CommandPalette.tsx` | Groupes (`cpal-grp`) + raccourcis (`cpal-kb`) par commande | INFO |
| UI-DS-08 | Général | Scrollbar invisible partout (webkit-scrollbar: none) | INFO |
