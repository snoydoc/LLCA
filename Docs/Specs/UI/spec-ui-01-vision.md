# Spec UI-01 — Vision Produit & Design System
<!-- AI-READY | Interface graphique LCCA Desktop | Version 1.0.0 | 2026-04-18 -->

## 1. Vision produit

**LCCA Desktop** est une interface graphique locale inspirée de Claude Desktop, conçue
pour piloter l'agent de codage LCCA V7.2 via son serveur MCP. Elle offre une expérience
conversationnelle fluide couplée à un panneau de contexte professionnel (fichiers, specs,
mémoire, transactions en cours).

> **Principe fondateur** :
> L'interface ne doit jamais cacher la machine — elle la rend lisible.
> Chaque action LLM est traçable, chaque transaction annulable, chaque spec consultable.

### Ce que LCCA Desktop n'est PAS
- ❌ Un IDE complet (pas d'éditeur de code inline — VS Code reste l'éditeur)
- ❌ Un client cloud (100% local, zéro telemetry externe)
- ❌ Une interface généraliste (optimisée LCCA uniquement)

---

## 2. UX Goals

### G1 — Conversation naturelle
L'utilisateur tape une commande en langage naturel ou DSL LCCA. L'interface transmet
via MCP, streame la réponse token par token, et affiche le résultat formaté (Markdown,
blocs de code avec coloration syntaxique).

### G2 — Contexte toujours visible
Un panneau latéral permanent affiche :
- Les fichiers du workspace ouverts/modifiés
- Les specs actives (`lcca_specs`)
- Les transactions en cours ou récentes
- L'état du serveur MCP (connecté / déconnecté / erreur)

### G3 — Transparence des transactions
Chaque commit de transaction affiche un badge coloré avec :
- TX ID (tronqué 8 chars)
- Fichiers modifiés (liste)
- Statut : ✅ Commité / ↩ Rollback / ⚠ Partiel

### G4 — Zéro friction
- Démarrage automatique du McpServer au lancement
- Reconnexion silencieuse si le serveur redémarre
- Historique des sessions persisté localement (JSON)
- Raccourcis clavier complets (table en section 6)

---

## 3. Principes de design

### 3.1 Densité d'information adaptative
- Mode **Compact** : chat seul, panneau contexte réduit à une barre latérale d'icônes
- Mode **Standard** : 3 panneaux (sidebar nav | chat | contexte) — défaut
- Mode **Focus** : chat plein écran, tout masqué sauf input

Transition via raccourci `Ctrl+\` ou bouton toggle.

### 3.2 Thèmes
Deux thèmes inclus, basculables en settings :

**Dark (défaut)** — inspiré Claude Desktop :
```
--bg-primary:      #1a1a2e   /* fond général */
--bg-secondary:    #16213e   /* panneaux latéraux */
--bg-surface:      #0f3460   /* cartes, bulles contexte */
--bg-input:        #1e1e2e   /* zone de saisie */
--accent:          #e94560   /* rouge-rose LCCA */
--accent-soft:     #533483   /* violet actions secondaires */
--text-primary:    #eaeaea
--text-secondary:  #a8a8b3
--text-muted:      #666680
--border:          #2a2a4a
--success:         #4ade80
--warning:         #fbbf24
--error:           #f87171
--code-bg:         #0d1117
```

**Light** :
```
--bg-primary:      #f8f9fa
--bg-secondary:    #ffffff
--bg-surface:      #e9ecef
--bg-input:        #ffffff
--accent:          #e94560
--accent-soft:     #7c3aed
--text-primary:    #1a1a2e
--text-secondary:  #4a4a6a
--text-muted:      #9494aa
--border:          #dee2e6
--success:         #16a34a
--warning:         #d97706
--error:           #dc2626
--code-bg:         #f6f8fa
```

### 3.3 Typographie
```
--font-sans:   'Inter', 'Segoe UI', system-ui, sans-serif
--font-mono:   'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace
--font-size-xs:    11px
--font-size-sm:    13px
--font-size-base:  14px
--font-size-md:    15px
--font-size-lg:    18px
--font-size-xl:    22px
--line-height-base: 1.6
--line-height-code: 1.5
```

### 3.4 Espacement & grille
```
--radius-sm:   4px
--radius-md:   8px
--radius-lg:   12px
--radius-xl:   16px
--space-xs:    4px
--space-sm:    8px
--space-md:    16px
--space-lg:    24px
--space-xl:    32px
```

---

## 4. Layout général

```
┌──────────────────────────────────────────────────────────────────┐
│  TITLE BAR (custom, draggable)                          [ _ □ × ]│
│  ● LCCA Desktop  v7.2   [●] MCP Connected   [🌙] [⚙]           │
├────┬─────────────────────────────────────┬───────────────────────┤
│    │                                     │                       │
│    │          CHAT PANEL                 │   CONTEXT PANEL       │
│ S  │                                     │                       │
│ I  │  ┌─────────────────────────────┐   │  ┌─────────────────┐  │
│ D  │  │ [assistant bubble]          │   │  │ 📁 Workspace    │  │
│ E  │  │                             │   │  │   core/          │  │
│ B  │  └─────────────────────────────┘   │  │   ├ spec_entry  │  │
│ A  │                                     │  │   └ mcp_server  │  │
│ R  │  ┌─────────────────────────────┐   │  ├─────────────────┤  │
│    │  │ [user bubble]               │   │  │ 📋 Specs actives│  │
│    │  └─────────────────────────────┘   │  │   2 specs       │  │
│    │                                     │  ├─────────────────┤  │
│    │  ┌─────────────────────────────┐   │  │ 🔄 Transactions │  │
│    │  │ [tx badge] ✅ tx_a3b4c5d6   │   │  │   tx_a3b4... ✅ │  │
│    │  └─────────────────────────────┘   │  └─────────────────┘  │
│    │                                     │                       │
├────┼─────────────────────────────────────┤                       │
│    │  ┌─────────────────────────────┐   │                       │
│    │  │ ▷  Tapez une commande...    │   │                       │
│    │  │                         [↑] │   │                       │
│    │  └─────────────────────────────┘   │                       │
│    │  [🔎 Spec] [📁 Fichier] [⚡ DSL]   │                       │
└────┴─────────────────────────────────────┴───────────────────────┘
```

Dimensions indicatives (fenêtre 1440×900) :
- **Sidebar** : 52px (icônes) — extensible à 200px (labels)
- **Chat panel** : flex-grow (min 500px)
- **Context panel** : 280px fixe (masquable)
- **Input zone** : 100px fixe en bas du chat

---

## 5. Personas & cas d'usage principaux

### Persona 1 — Le développeur LCCA quotidien
**Profil** : utilise LCCA depuis le terminal, veut une interface pour visualiser les TX.
**Cas d'usage prioritaires** :
- Taper une commande DSL, voir le résultat en Markdown
- Consulter le diff des fichiers modifiés dans le panneau contexte
- Annuler une transaction d'un clic (rollback)

### Persona 2 — L'utilisateur langage naturel
**Profil** : ne connaît pas le DSL LCCA, veut parler en français naturel.
**Cas d'usage prioritaires** :
- Décrire une tâche ("refactorise la classe X pour injecter les dépendances")
- Voir la spec générée avant que le code soit produit
- Valider ou rejeter la spec proposée

### Persona 3 — Le reviewer d'architecture
**Profil** : veut auditer les specs et transactions passées.
**Cas d'usage prioritaires** :
- Parcourir les specs stockées dans `lcca_specs`
- Lire le détail d'une spec (body_md en Markdown rendu)
- Exporter une spec en `.md`

---

## 6. Raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| `Enter` | Envoyer le message |
| `Shift+Enter` | Saut de ligne dans l'input |
| `Ctrl+L` | Effacer le chat courant |
| `Ctrl+N` | Nouvelle session |
| `Ctrl+\` | Toggle panneau contexte |
| `Ctrl+Shift+F` | Mode Focus (plein écran chat) |
| `Ctrl+K` | Palette de commandes |
| `Ctrl+Z` | Rollback dernière TX (avec confirmation) |
| `Ctrl+,` | Ouvrir settings |
| `Ctrl+Shift+T` | Toggle thème dark/light |
| `↑` / `↓` | Naviguer dans l'historique des commandes |
| `Escape` | Annuler la saisie courante |

---

## 7. États de l'interface

### État MCP
| Indicateur | Couleur | Description |
|------------|---------|-------------|
| ● Connecté | `--success` | McpServer actif, prêt |
| ◌ Connexion... | `--warning` (pulse) | Démarrage ou reconnexion |
| ✕ Déconnecté | `--error` | Serveur arrêté ou crash |

### État LLM (Ollama)
| Indicateur | Couleur | Description |
|------------|---------|-------------|
| 🤖 Ollama actif | `--success` | Modèle chargé, réponses LLM |
| 🔲 Mode stub | `--warning` | Ollama absent, réponses stub |

### État input
- **Idle** : placeholder "Tapez une commande ou décrivez une tâche…"
- **Streaming** : spinner animé, input désactivé
- **Erreur** : border `--error`, message inline sous l'input
- **Spec en attente** : badge "📋 Spec générée — valider ?" au-dessus de l'input

---

## 8. Accessibilité

- Contraste minimum WCAG AA (4.5:1 texte normal, 3:1 texte large)
- Navigation clavier complète (Tab, Shift+Tab, Enter, Escape)
- `aria-label` sur tous les boutons icône
- `role="log"` sur le panneau chat (lecteur d'écran)
- `aria-live="polite"` sur les bulles de réponse en streaming
- Taille de police minimum : 11px (--font-size-xs), recommandée : 14px

<!-- AI-READY | Spec UI-01 Vision & Design System | Version 1.0.0 | 2026-04-18 -->
