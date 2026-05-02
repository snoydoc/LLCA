# Skill: LLCA / Adham — UI Architecture & Design System

## 1. Mission
Tu es l'architecte UI de **Adham** (LL Coding Agent), une interface de chat developer-first 
en Electron/React. Ton objectif : produire des composants React/TS impeccables, cohérents 
entre les thèmes "Terminal Forge" (dark) et "Forge Papier" (light), avec une esthétique 
"IDE premium" — minimaliste, dense d'information, et jamais "bootstrap-esque".

---

## 2. Philosophie Visuelle (décisions immuables)

| Principe | Application |
|---|---|
| **Fondations sombres** | Dark = défaut. Light = variation. Toujours concevoir en dark d'abord. |
| **Monospace pour la donnée** | JetBrains Mono pour tout ce qui est technique (code, meta, IDs, badges, raccourcis). |
| **Inter pour l'interface** | Inter pour les titres, corps, labels. Jamais de serif. |
| **Ambre comme seul accent** | `#F59E0B` (dark) / `#B45309` (light). Pas de bleu primaire, pas de violet accent. |
| **Bordures &gt; Ombres** | La structure vient des bordures subtiles (`--b1`, `--b2`), pas des ombres portées massives. |
| **Scroll invisible** | `::-webkit-scrollbar { display: none }` sur toute zone scrollable. |
| **Densité** | Padding réduit, tailles de police petites (9–14px), radius modérés (6–13px). |

---

## 3. Tokens Essentiels (source de vérité)

### Palette Sémantique
Backgrounds :  bg0 (titre/sidebar) → bg1 (chat) → bg2 (modales) → bg3 (surfaces) → bg4 (inputs/code)
Textes      :  t0 (principal) → t1 (secondaire) → t2 (désactivé) → t3 (fantôme)
Bordures    :  b1 (subtile) → b2 (visible) → b-acc (accent ambre)
Accents     :  acc (ambre) / ok (vert) / err (rouge) / info (bleu) / warn (jaune)

### Thème Dark — "Terminal Forge"
- **Fonds** : `#050509` → `#08080F` → `#0D0D1A` → `#131320` → `#1A1A2E`
- **Textes** : `#F0F0F8` / `#A8A8C0` / `#5A5A78` / `#2E2E44`
- **Accents** : `#F59E0B` (ambre vif)
- **Code bg** : `#04040B`

### Thème Light — "Forge Papier"  
- **Fonds** : `#EEEAE2` → `#F5F2EC` → `#F8F6F1` → `#FFFFFF` → `#EDE9E0`
- **Textes** : `#1C1510` / `#4A3F30` / `#8A7A66` / `#BFB5A8`
- **Accents** : `#B45309` (ambre brûlé)
- **Code bg** : `#EDE9DF`

> **Règle d'or** : Aucune valeur hardcodée. Tout passe par les CSS variables du `themes.css`. 
> Si un token n'existe pas, le créer plutôt que hardcoder.

---

## 4. Architecture de Layout
┌─ TitleBar (34px, bg0) ─────────────────────────────┐
│ [●●●] ⬡ Adham  [MCP●]          model   [⚙] [✕]    │
├─ Sidebar ─┬─ ChatPanel ───────────────┬─ Context ─┤
│   (52px)  │                         │  (240px)  │
│  [💬]     │   Messages / Welcome    │  Files    │
│  [📁]     │                         │  Specs    │
│  [📐]     │   InputZone             │  MCP      │
│  [?]      │                         │           │
│  [⚙]      │                         │           │
└───────────┴─────────────────────────┴───────────┘


**Contraintes layout :**
- Sidebar et ContextPanel ont `bg0`, bordures `b1` de séparation.
- ChatPanel a `bg1`, c'est la zone de contenu principale.
- TitleBar a `bg0`, bordure bas `b1`.

---

## 5. Composants — Spécifications par Pattern

### A. TitleBar
- **macOS dots** : `#FF5F57`, `#FEBC2E`, `#28C840` — 10px, uniquement visuel.
- **Gem** : pentagone via `clip-path`, 13×13px, couleur `acc`, glow `acc`.
- **MCP pill** : bordure `b1`, radius 100px, dot vert pulsant (`ok`).
- **Toggle thème** : ☀ (dark→light) / 🌙 (light→dark).
- **Boutons action** : 26×26px, radius 6px, hover `glass`. Le ✕ utilise `err`.

### B. Sidebar
- **Boutons nav** : 34×34px, radius 9px. État actif = fond `acc-dim`, texte `acc`, barre gauche 2px `acc`.
- **Sessions** : 26×26px, radius 7px, JetBrains Mono 9px. État actif = fond `acc-dim`, bordure `b-acc`.
- **Divider** : 20px wide, 1px, couleur `b1`.

### C. Messages
- **Avatar user** : 22×22px, radius 6px, fond `acc-dim`, bordure `b-acc`, lettre "A" en `acc`.
- **Avatar Adham** : fond `glass`, bordure `b1`, symbole `⬡`, couleur `t2`.
- **Meta** : JetBrains Mono 9.5px — rôle en `t1` bold, timestamp en `t3`.
- **Texte user** : Inter 12.5px `t0`.
- **Texte Adham** : Inter 12.5px `t1`.
- **Code inline** : JetBrains Mono 11px, fond `bg4`, bordure `b1`, radius 4px, couleur `acc`.

### D. Code Block
- Fond `code-bg`, bordure `b1`, radius 8px.
- **Header** : fond `glass`, bordure bas `b1`, padding 5px 10px.
  - Langue : JetBrains Mono 9.5px `acc` bold.
  - Nom fichier : JetBrains Mono 9.5px `t3`, aligné à droite.
- **Body** : padding 10px 12px, JetBrains Mono 11px, line-height 1.6.
- **Syntax highlighting** (conditionnel par thème) :
  - Dark : keyword `#FF7B72`, function `#D2A8FF`, string `#A5D6FF`, comment `#4A5568` italic, number `#79C0FF`
  - Light : keyword `#A21C30`, function `#6D28D9`, string `#047857`, comment `#9C8F7A` italic, number `#1D4ED8`

### E. Badges & Pills
Tous les badges utilisent le pattern : `inline-flex`, padding `3px 9px`, radius 100px, JetBrains Mono 10px 500.
- **badge-ok** : fond `rgba(ok,0.1)`, bordure `rgba(ok,0.2)`, texte `ok`
- **badge-acc** : fond `acc-dim`, bordure `b-acc`, texte `acc`
- **badge-err** : fond `rgba(err,0.1)`, bordure `rgba(err,0.2)`, texte `err`
- **badge-inf** : fond `rgba(info,0.1)`, bordure `rgba(info,0.2)`, texte `info`

### F. Spec Badge (`.spb`)
- Fond `glass`, bordure `b1`, **bordure-gauche 2px `acc`**, radius 8px.
- Icône 📐 `acc` 14px | titre 11.5px 500 `t0` | meta JetBrains Mono 9.5px `t2`.
- **Score pill** : JetBrains Mono 10.5px 600, couleur `ok`, fond `rgba(ok,0.1)`.

### G. Streaming Indicator
- Fond `bg4`, bordure `b1`, radius 12px.
- 3 orbes Ø5px, animation pulse infinie (scale 1→1.5, opacity 0.3→0.9, 1.5s, stagger 0.2s).
- Texte "Adham réfléchit..." JetBrains Mono 11px `t2`.

### H. InputZone
- Bordure haut `b1`, fond `bg1`, padding 9px 14px.
- **Wrapper `.iw`** : fond `bg4`, bordure `b2`, radius 13px, padding 8px 10px.
  - `:focus-within` → bordure `b-acc`.
- **Textarea** : Inter 12.5px, placeholder `t3`. Pas de bordure visible sur le textarea lui-même.
- **Kbd hints** : JetBrains Mono 9.5px, bordure `b1`, radius 4px.
- **Send btn** : 28×28px, radius 7px, fond `acc`, texte `bg0`, icône "↑".
- **Hint bar** : centrée, JetBrains Mono 9px `t3` — "↩ envoyer · ⇧↩ nouvelle ligne · Esc annuler".

### I. ContextPanel (240px)
- **Section headers** : 9px 600 uppercase, letter-spacing 0.1em, `t2`, sticky, fond `bg0`.
- **File tree** : JetBrains Mono 10.5px, hover `glass`. Dossiers en `t2`, fichiers en `t1`, modifiés en `acc`.
- **Spec cards** : hover `glass`, titre 11px 500 `t0`, meta `t3`. Icône état : ✅ ou ⚠️.
- **MCP Bar** (bas du panel) : `margin-top: auto`, JetBrains Mono 9.5px `t2`, dot `ok`.

### J. Command Palette
- Fond `bg2`, bordure `b2`, radius 12px, shadow `shadow`.
- **Input** : padding 10px 14px, bordure bas `b1`, icône ⌕ `t2`, input Inter 13px `t0`.
- **Groupes** : 9px 600 uppercase `t3`, letter-spacing 0.1em.
- **Items** : padding 7px 9px, radius 7px, flex gap 8px.
  - Hover/sélection : fond `glass` ou `acc-dim` si `.sel`.
  - Raccourci : JetBrains Mono 9.5px, fond `bg4`, bordure `b1`.

### K. Welcome Screen
- Fond `bg1` avec grille CSS 44×44px (dark: `rgba(255,255,255,0.018)`, light: `rgba(100,80,40,0.07)`).
- **Glow central** : radial-gradient ellipse 340×220px, top 30% (dark: `rgba(245,158,11,0.05)`, light: `rgba(180,83,9,0.06)`).
- **Logo container** : 60×60px, radius 16px, fond `bg3`, bordure `b2`, shadow.
  - Animation `float` : translateY 0→-5px→0, 4s ease-in-out infinite.
- **Gem** : 26×26px dans le logo, `acc`, glow `acc`.
- **Titre** : 22px 300, letter-spacing -0.04em, `t0`. Le mot "Adham" en 600 `acc`.
- **Sous-titre** : JetBrains Mono 11.5px `t2`, centré, line-height 1.7.
- **Chips** : JetBrains Mono 10.5px, radius 100px, fond `bg4`, bordure `b2`.
  - Hover : bordure `b-acc`, couleur `acc`, fond `acc-dim`.
  - Chips : @spec, @eval, @web, @file, Ctrl+K.

---

## 6. Formulaires & Contrôles

### Boutons
- **Primaire** : fond `acc`, texte `bg0`, radius 7px, 11px 600.
- **Secondaire** : fond `glass`, bordure `b2`, texte `t1`, radius 7px.
- **Danger** : fond `rgba(err,0.1)`, bordure `err`, texte `err`.

### Inputs
- Fond `bg4`, bordure `b2`, radius 7px, padding 6px 10px, JetBrains Mono 12px `t0`.
- `:focus` → bordure `b-acc`.

### Toggle Switch
- Track : 34×18px, fond `bg4`, bordure `b2`, radius 9px.
- `.on` : fond `acc`, bordure transparent.
- Thumb : Ø12px, fond `t2`. `.on` → left 18px, fond `bg0`.
- Transition : 0.2s sur left et background.

---

## 7. Animations & Micro-interactions

| Élément | Animation | Durée |
|---|---|---|
| Logo welcome | `float` translateY 0→-5px→0 | 4s ease-in-out ∞ |
| Streaming orbs | `pulse` scale 1→1.5, opacity 0.3→0.9 | 1.5s ∞, stagger 0.2s |
| Hover sidebar btn | color + background | 0.15s |
| Input focus | border-color | 0.2s |
| Toggle thumb | left + background | 0.2s |
| TitleBar btn hover | background + color | 0.15s |

---

## 8. Raccourcis & Commandes (à exposer dans l'UI)

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

## 9. Mapping Composants → Fichiers React

| Composant | Fichier | Vérification critique |
|---|---|---|
| TitleBar | `TitleBar.tsx` | Gem + MCP pill + toggle thème |
| Sidebar | `Sidebar.tsx` | sb-session + barre active `.on` |
| ChatPanel | `ChatPanel.tsx` | — |
| Message | `MessageBubble.tsx` | Avatar ⬡, meta format |
| Code Block | `CodeBlock.tsx` | Syntax highlighting conditionnel par thème |
| TX Badge | `TxBadge.tsx` | — |
| Spec Badge | `SpecBadge.tsx` | Border-left `acc`, score pill `ok` |
| Streaming | `StreamingIndicator.tsx` | 3 orbs + animation |
| Input | `InputZone.tsx` | Wrapper focus + hint bar |
| Context | `ContextPanel.tsx` | File tree + spec cards + MCP bar bottom |
| Command Palette | `CommandPalette.tsx` | Groupes + sel state + kbd hints |
| Welcome | `WelcomeScreen.tsx` | Grid + glow + float + chips |
| Tokens | `themes.css` | **SOURCE DE VÉRITÉ** — tous les tokens §3 |

---

## 10. Checklist de Qualité (valider avant de livrer)

- [ ] Aucune valeur couleur hardcodée — tout passe par `themes.css`
- [ ] Le dark mode est testé en premier, light mode en dérivation
- [ ] Les scrollbars sont invisibles partout
- [ ] JetBrains Mono est utilisé pour toute donnée technique
- [ ] Les badges sémantiques utilisent les 4 variantes standardisées
- [ ] Le CodeBlock adapte sa coloration syntaxique au thème actif
- [ ] L'InputZone a bien le comportement `:focus-within` sur son wrapper
- [ ] La Command Palette gère les états hover et sélection
- [ ] Le Welcome Screen a la grille + glow + animation float
- [ ] Le ContextPanel a la MCP bar positionnée en bas (`mt-auto`)

---

## 11. Anti-patterns (NE JAMAIS FAIRE)

- ❌ Utiliser du bleu `#3B82F6` comme couleur primaire — l'accent est AMBRE.
- ❌ Mettre des ombres lourdes sur chaque carte — utiliser les bordures.
- ❌ Hardcoder des valeurs de padding/margin sans token.
- ❌ Oublier le thème light sur un nouveau composant.
- ❌ Utiliser une police autre que Inter/JetBrains Mono.
- ❌ Laisser les scrollbars natives visibles.
- ❌ Créer un nouveau style de badge au lieu d'étendre les 4 existants.

---

## 12. Pattern — Boutons radio styled (ModeSection SI-06)

Pour un groupe de boutons radio-style (sélection exclusive) sans input radio HTML :

```tsx
// Bouton actif : fond accent-dim, bordure b-acc, texte accent
// Bouton inactif : fond bg-surface, bordure b1, texte text-secondary
// Clic → callback onCommand('mode X')
const isActive = m.id === currentMode;
<button style={{
  border: `1px solid ${isActive ? 'var(--b-acc)' : 'var(--b1)'}`,
  background: isActive ? 'var(--accent-dim)' : 'var(--bg-surface)',
  color: isActive ? 'var(--accent)' : 'var(--text-secondary)',
}}>
```

La RAM hint (ex. `~150 MB`) s'affiche en `var(--font-mono)` 10px `var(--text-muted)` ou `var(--accent)` si actif.

