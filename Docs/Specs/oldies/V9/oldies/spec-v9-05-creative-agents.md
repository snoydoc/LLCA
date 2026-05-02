# Spec V9-05 — Agents Créatifs & Fonctionnalités Avancées
<!-- AI-READY | LCCA V9 | Agents Créatifs | Version 9.0.0-draft | 2026-04-20 -->

## Abstract

Six propositions créatives pour LCCA V9, couvrant : l'audit autonome de codebase (QAAgent),
l'auto-documentation (DocAgent), la collaboration humain-agent (mode Pair Programmer),
le dashboard analytique, la synthèse vocale locale, et la mémoire épisodique graphique.
Chaque spec est indépendante et peut être implémentée dans n'importe quel ordre.

---

## Sprint V9-05-A — QAAgent : Audit autonome continu

### Contexte et motivations

Le `skill 005-debt-tracker.md` est mis à jour manuellement en fin de session. Cette friction
entraîne des dettes non documentées et des sessions qui démarrent sans vision claire de l'état
du codebase. Un `QAAgent` autonome surveille le codebase en arrière-plan, détecte les dettes
nouvelles, et publie des `TaskContract` sur le bus A2A.

Il s'intègre dans la hiérarchie V8 comme un 6ème agent (aux côtés de ObserverAgent) avec
une boucle indépendante de la KarpathyLoop principale.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/agents/qa_agent.py` | CREATE — QAAgent + QAReport dataclass |
| `core/agents/__init__.py` | PATCH — export QAAgent + QAReport |
| `config.py` | PATCH — `QA_SCAN_INTERVAL_HOURS = 24`, `QA_DEBT_THRESHOLD_WARN = 7`, `QA_DEBT_THRESHOLD_CRIT = 10` |
| `tests/test_qa_agent.py` | CREATE — 12 tests |

### Spécification : `QAReport` dataclass

```python
@dataclass
class QAReport:
    """
    Rapport d'audit qualité produit par QAAgent.

    Champs :
        debts_found      : liste de dettes détectées (sévérité, module, description)
        files_scanned    : nombre de fichiers analysés
        total_size_kb    : taille totale scannée
        critical_count   : dettes CRITIQUE
        warn_count       : dettes WARN
        info_count       : dettes INFO
        timestamp        : horodatage ISO de l'audit
        action_contracts : task_ids des contrats publiés sur le bus
    """
    debts_found      : list[dict]
    files_scanned    : int
    total_size_kb    : float
    critical_count   : int
    warn_count       : int
    info_count       : int
    timestamp        : str
    action_contracts : list[str] = field(default_factory=list)

    def has_critical(self) -> bool:
        return self.critical_count > 0

    def summary(self) -> str:
        return (
            f"QA scan: {self.files_scanned} fichiers, "
            f"{self.critical_count} CRITIQUE / {self.warn_count} WARN / {self.info_count} INFO"
        )
```

### Spécification : `QAAgent` — règles d'audit

```python
# Règles d'audit statique — chacune retourne (sévérité, description) ou None
_QA_RULES: list[Callable] = [
    _rule_file_too_large,      # > 10KB → WARN, > 20KB → CRITIQUE
    _rule_hardcoded_path,      # "D:\\..." dans le code → WARN
    _rule_print_in_production, # print() hors tests → INFO
    _rule_fstring_in_log,      # log.info(f"...") → INFO
    _rule_missing_docstring,   # classe ou fonction publique sans docstring → INFO
    _rule_bare_except,         # except: (sans type) → WARN
    _rule_direct_file_write,   # file.write() sans snapshot → CRITIQUE
    _rule_hardcoded_python,    # "python" hardcodé → CRITIQUE
    _rule_duplicate_constant,  # même constante dans 2+ fichiers → WARN
]

def _rule_file_too_large(filepath: str, content: str, size_kb: float) -> "tuple | None":
    if size_kb > 20:
        return ("CRITIQUE", f"Fichier {size_kb:.1f}KB > 20KB — refactorisation urgente")
    if size_kb > 10:
        return ("WARN", f"Fichier {size_kb:.1f}KB > 10KB — candidat refacto")
    return None

def _rule_hardcoded_python(filepath: str, content: str, size_kb: float) -> "tuple | None":
    import re
    if re.search(r'["\']python["\']', content) and "tests/" not in filepath:
        return ("CRITIQUE", "\"python\" hardcodé — utiliser sys.executable")
    return None

def _rule_direct_file_write(filepath: str, content: str, size_kb: float) -> "tuple | None":
    import re
    if re.search(r'\.write_text\(|\.write\(', content) and "tests/" not in filepath:
        if "snapshot" not in content and "write_text" in content:
            return ("CRITIQUE", "write_text() sans snapshot TransactionManager détecté")
    return None
```

### Intégration dans le pipeline V8

```python
class QAAgent(BaseAgent):
    """
    Agent d'audit qualité autonome.

    run_scan() : scan complet du workspace → QAReport
    run_task() : traite un contrat "qa_audit" depuis le bus A2A
    schedule() : démarre un thread daemon qui scanne toutes les N heures

    Contraintes :
    - Ne modifie JAMAIS de fichier (lecture seule)
    - Publie des TaskContracts pour les CRITIQUE (target_agent="architect")
    - Stocke le rapport dans lcca_context via memory_store
    """

    @classmethod
    def create(cls, bus: A2ALocalBus, mcp_caller=None) -> "QAAgent":
        card = AgentCard(
            name="qa",
            version="9.0.0",
            capabilities=["audit", "debt_detection", "memory_store"],
            mcp_tools=AGENT_MCP_ALLOWLIST.get("qa", ["memory_search", "memory_store"]),
            recovery_policy=RecoveryPolicy(max_retries=1, retry_delay=60.0),
            description="Audit continu de la qualité du codebase LCCA",
        )
        return cls(card=card, bus=bus, mcp_caller=mcp_caller)

    def run_scan(self, workspace: "Path | None" = None) -> QAReport:
        """Scan complet synchrone. Utilisable sans bus A2A."""
        ...

    def schedule(self, interval_hours: float = 24.0) -> "threading.Thread":
        """Démarre un thread daemon de scan périodique."""
        import threading
        def _loop():
            import time
            while True:
                try:
                    report = self.run_scan()
                    log.info("[qa] %s", report.summary())
                except Exception as exc:
                    log.error("[qa] scan error: %s", exc)
                time.sleep(interval_hours * 3600)
        t = threading.Thread(target=_loop, daemon=True, name="qa-agent-scheduler")
        t.start()
        return t
```

---

## Sprint V9-05-B — DocAgent : Auto-documentation

### Contexte et motivations

Les skills `.claude-skills/*.md` sont mis à jour manuellement en fin de session. Cette
tâche répétitive est parfaitement automatisable : un `DocAgent` lit le diff git, les
receipts de la session, et met à jour automatiquement les fichiers de documentation.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/agents/doc_agent.py` | CREATE — DocAgent |
| `scripts/post-commit.ps1` | CREATE — git hook PowerShell déclenche DocAgent |
| `tests/test_doc_agent.py` | CREATE — 8 tests |

### Spécification : `DocAgent`

```python
class DocAgent(BaseAgent):
    """
    Agent de documentation automatique.

    Responsabilités :
    1. Lire le diff git de la session (git diff HEAD~1 --name-only)
    2. Pour chaque fichier modifié dans core/ :
       - Vérifier les docstrings manquantes via ASTIndexer
       - Générer les docstrings manquantes via LLMGenerator (modèle 3b)
    3. Mettre à jour les skills .md (patterns appris, arborescence, sprint context)
    4. Mettre à jour README.md si nouveaux modules créés

    Contraintes :
    - Utilise UNIQUEMENT le modèle léger (OLLAMA_MODEL_LIGHT = 3b)
    - Max 5 fichiers par session (évite les runs trop longs)
    - Ne touche JAMAIS à core/ directement — utilise McpEditBatch (via MCP tool edit_batch)
    - Toujours demander confirmation avant modification des skills .md
      (flag DOCAGENT_AUTO_CONFIRM = False par défaut)
    """

    # Patterns de docstrings à générer
    _DOCSTRING_PROMPT = (
        "Génère UNE SEULE docstring Python en français technique pour la fonction/classe suivante.\n"
        "Format obligatoire :\n"
        '    """\n'
        "    <description en 1-2 phrases>\n\n"
        "    Args:\n"
        "        <param>: <type> — <description>\n\n"
        "    Returns:\n"
        "        <type> — <description>\n"
        '    """\n\n'
        "Code à documenter :\n"
    )

    def run_task(self, contract: TaskContract) -> AgentResult:
        """Traite un contrat de documentation depuis le bus A2A."""
        ...

    def document_file(self, filepath: "Path") -> dict:
        """
        Ajoute les docstrings manquantes dans un fichier Python.

        Returns:
            dict {file, added: int, skipped: int, errors: int}
        """
        ...

    def update_skill(self, skill_path: "Path", new_pattern: str) -> bool:
        """
        Ajoute un pattern dans un skill .md (section ## PATTERNS APPRIS).
        Si DOCAGENT_AUTO_CONFIRM = False, publie sur bus et attend confirmation.
        """
        ...
```

### Script git hook `scripts/post-commit.ps1`

```powershell
# post-commit.ps1 — Déclenche DocAgent après chaque commit
# Copier dans .git/hooks/post-commit (sans extension) et rendre exécutable
#
# Usage : git commit -m "Sprint V9-05-B"
# → DocAgent analyse le diff et met à jour la doc

$PY = "D:\LLMCodeAgent\venv\Scripts\python.exe"
$SCRIPT = "D:\LLMCodeAgent\scripts\run_doc_agent.py"

if (Test-Path $SCRIPT) {
    Write-Host "[DocAgent] Démarrage post-commit..." -ForegroundColor Cyan
    & $PY $SCRIPT --from-git-hook
}
```

---

## Sprint V9-05-C — Mode Pair Programmer (Human-in-the-Loop)

### Contexte et motivations

La KarpathyLoop est entièrement autonome. Certains utilisateurs préfèrent valider chaque
itération avant de continuer. Le mode Pair Programmer pause le pipeline après chaque
itération Reviewer et attend une réponse de l'UI (IPC Electron).

### Fichiers à modifier

| Fichier | Opération |
|---------|-----------|
| `core/agents/agent_orchestrator.py` | PATCH — mode HITL (Human-in-the-Loop) |
| `ui/electron/main.ts` | PATCH — handler `ipcMain.handle('hitl:respond', ...)` |
| `ui/electron/preload.ts` | PATCH — exposition `window.lcca.hitlRespond()` |
| `ui/src/components/ChatPanel.tsx` | PATCH — affichage diff + boutons Continuer/Modifier/Accepter |
| `config.py` | PATCH — `HITL_ENABLED = False` (opt-in) |

### Spécification : `AgentOrchestrator` — mode HITL

```python
# Nouveau paramètre dans __init__
def __init__(
    self,
    ...
    hitl_callback: "Callable[[str, str, int], str] | None" = None,
) -> None:
    """
    hitl_callback : callable(code, reflection, iteration) → str
        Reçoit le code et la réflexion de l'itération courante.
        Retourne : "continue" | "accept" | "modify:<new_intent>"
        Si None : mode autonome (comportement actuel).
    """
    self._hitl = hitl_callback
    ...

# Dans la boucle KarpathyLoop, après ReviewerAgent :
if self._hitl is not None and not reviewer_result.success:
    decision = self._hitl(generated_code, reflection, iteration)
    if decision == "accept":
        success = True
        break
    elif decision.startswith("modify:"):
        intent = decision[7:]  # nouvel intent fourni par l'humain
    # "continue" → boucle normale
```

### Spécification UI — composant `HITLPanel`

```typescript
// ui/src/components/HITLPanel.tsx
interface HITLPanelProps {
  code: string;
  reflection: string;
  iteration: number;
  onContinue: () => void;
  onAccept: () => void;
  onModify: (newIntent: string) => void;
}

// Affiche :
// 1. Diff coloré du code (itération N)
// 2. Réflexion du Reviewer (raison du rejet)
// 3. Trois boutons : "Continuer", "Accepter tel quel", "Modifier l'intent"
// 4. Zone de texte pour "Modifier l'intent" (si bouton cliqué)
```

---

## Sprint V9-05-D — Dashboard Analytics

### Contexte et motivations

`telemetry.py` écrit des JSONL rotatifs dans `logs/`. `receipt_store.py` stocke des
ExecutionReceipts HMAC avec `quality_score`, `task_id`, `intent`. Ces données permettent
un dashboard de productivité complet.

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `core/mcp_tools_schema.py` | PATCH — tool `get_analytics` (13ème tool) |
| `core/mcp_tool_handlers.py` | PATCH — `_tool_get_analytics()` |
| `ui/src/components/AnalyticsPanel.tsx` | CREATE — dashboard React recharts |
| `ui/src/stores/analyticsStore.ts` | CREATE — Zustand store analytics |

### Spécification : tool `get_analytics`

```python
def _tool_get_analytics(params: dict) -> dict:
    """
    Retourne les métriques LCCA pour le dashboard UI.

    Returns:
        {
            "period_days": int,
            "total_transactions": int,
            "success_rate": float,         # 0.0-1.0
            "avg_quality_score": float,    # 0-100
            "avg_latency_ms": float,
            "models_used": {model: count},
            "tools_usage": {tool: count},
            "quality_trend": [             # derniers 30 jours
                {"date": "2026-04-20", "avg_score": 75.2}
            ],
            "karpathy_stats": {
                "avg_iterations": float,
                "stagnation_rate": float,
                "success_rate": float,
            }
        }
    """
    ...
```

### Métriques UI (recharts)

```typescript
// Composants recharts dans AnalyticsPanel :
// 1. LineChart : qualité moyenne par jour (30 derniers jours)
// 2. BarChart  : outils MCP les plus utilisés (top 5)
// 3. PieChart  : répartition modèles (3b vs 7b vs 14b)
// 4. Stat cards : total TX, taux succès, latence moyenne, score moyen
```

---

## Sprint V9-05-E — Mémoire Épisodique (graphe de décisions)

### Contexte et motivations

Les skills .md capturent des patterns mais pas les **décisions architecturales** (pourquoi
on a choisi X et pas Y). Un graphe de connaissance épisodique permet de tracer l'historique
décisionnel complet et de le requêter en langage naturel.

### Architecture

```
Nœuds (entités) :
    Session         {date, sprint_name, engineer}
    Decision        {title, rationale, alternatives_rejected}
    Module          {path, version, last_modified}
    Pattern         {name, description, source_session}

Arêtes typées :
    Session → Decision  : "a_pris"
    Session → Module    : "a_modifié"
    Decision → Module   : "concerne"
    Decision → Decision : "a_remplacé" | "a_inspiré"
    Pattern → Decision  : "a_émergé_de"
```

### Fichiers à créer

| Fichier | Opération |
|---------|-----------|
| `core/episodic_memory.py` | CREATE — EpisodicMemory (DuckDB backend) |
| `core/episodic_types.py` | CREATE — Node, Edge, EpisodicQuery dataclasses |
| `config.py` | PATCH — `EPISODIC_DB_PATH` |

### Spécification : `EpisodicMemory`

```python
class EpisodicMemory:
    """
    Graphe de connaissance épisodique basé sur DuckDB.

    Usage :
        em = EpisodicMemory()
        em.add_decision(
            title="Choix libcst pour l'AST",
            rationale="libcst permet la modification sans perte de formatting",
            alternatives=["ast stdlib (lecture seule)", "rope (complexe)"],
            session_date="2026-04-16",
        )
        results = em.query("pourquoi libcst")
        # → [Decision(title="Choix libcst...", rationale="...")]
    """

    def add_decision(self, title: str, rationale: str,
                     alternatives: list[str], session_date: str) -> str:
        """Ajoute une décision architecturale. Retourne son ID."""
        ...

    def query(self, question: str, limit: int = 5) -> list[dict]:
        """
        Recherche textuelle dans le graphe (FTS DuckDB).
        Compatible avec une future intégration LLM (embeddings).
        """
        ...

    def get_session_timeline(self) -> list[dict]:
        """Chronologie des sessions avec leurs décisions."""
        ...
```

---

## Sprint V9-05-F — Synthèse Vocale Locale (TTS)

### Contexte et motivations

Quand LCCA tourne une tâche longue (generate_spec, KarpathyLoop), l'utilisateur ne regarde
pas l'écran. Une notification vocale à la fin ("Sprint terminé, 4 itérations, score 82")
améliore la productivité multi-tâches sans aucune API cloud.

**Moteur retenu : Kokoro-FastAPI** (MIT, offline, voix françaises, ~200MB)

### Fichiers à créer / modifier

| Fichier | Opération |
|---------|-----------|
| `ui/electron/main.ts` | PATCH — handler `ipcMain.handle('tts:speak', ...)` |
| `ui/electron/preload.ts` | PATCH — `window.lcca.ttsSay(text)` |
| `ui/src/hooks/useTts.ts` | CREATE — hook React pour les notifications vocales |
| `config.py` | PATCH — `TTS_ENABLED = False`, `TTS_ENGINE = "kokoro"`, `TTS_VOICE = "fr_f"` |
| `scripts/start-tts.ps1` | CREATE — démarre Kokoro en arrière-plan |

### Spécification : handler IPC `tts:speak`

```typescript
// main.ts — ajout dans la section handlers IPC
ipcMain.handle('tts:speak', async (_event, text: string) => {
  const ttsEnabled = store.get('ttsEnabled', false);
  if (!ttsEnabled) return { success: false, reason: 'TTS disabled' };

  const engine = store.get('ttsEngine', 'kokoro');
  if (engine === 'kokoro') {
    // Kokoro-FastAPI tourne localement sur port 8880
    try {
      const resp = await fetch('http://localhost:8880/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: store.get('ttsVoice', 'fr_f') }),
      });
      // Kokoro retourne un WAV — lire avec Electron shell
      const audioBuffer = await resp.arrayBuffer();
      // Jouer avec l'API Audio native Electron (pas d'import externe nécessaire)
      return { success: true };
    } catch (err) {
      log.warn('TTS error:', err);
      return { success: false, reason: String(err) };
    }
  }
  return { success: false, reason: 'Unknown engine' };
});
```

### Points de notification vocale

Les notifications vocales sont déclenchées à la fin de :
- `AgentOrchestrator.run()` → "Pipeline terminé : {iterations} itérations, score {quality}"
- `SpecGenerator.generate()` → "Spec générée : {title}"
- `QAAgent.run_scan()` (si CRITIQUE trouvé) → "Alerte qualité : {critical_count} problème(s) critique(s)"
- `TrainingPipeline.run()` → "Entraînement terminé : {pairs} paires, modèle {model_name}"

---

## Critères d'acceptation globaux V9-05

### QAAgent (V9-05-A)
- [ ] `QAAgent.run_scan()` analyse les fichiers core/ et retourne un `QAReport`
- [ ] `_rule_hardcoded_python("x.py", "'python'", 1.0)` retourne `("CRITIQUE", ...)`
- [ ] `_rule_file_too_large("x.py", "", 25.0)` retourne `("CRITIQUE", ...)`
- [ ] `QAAgent.schedule(interval_hours=0.001)` démarre un thread daemon sans crash
- [ ] `QAReport.has_critical()` retourne True si critical_count > 0
- [ ] `QAReport.summary()` retourne une chaîne non vide

### DocAgent (V9-05-B)
- [ ] `DocAgent.document_file(path)` retourne `{added: N, skipped: M, errors: 0}`
- [ ] Fichier sans docstrings → docstrings générées par LLM 3b
- [ ] `DOCAGENT_AUTO_CONFIRM = False` → pas de modification sans confirmation

### Pair Programmer (V9-05-C)
- [ ] `AgentOrchestrator(hitl_callback=lambda *a: "accept")` accepte le premier code
- [ ] `AgentOrchestrator(hitl_callback=None)` → comportement autonome inchangé (régression 0)
- [ ] `hitl_callback` retournant `"modify:new intent"` → nouvel intent utilisé à l'itération suivante

### Dashboard Analytics (V9-05-D)
- [ ] `_tool_get_analytics({})` retourne un dict avec toutes les clés attendues
- [ ] `AnalyticsPanel` se monte sans erreur avec des données vides (`total_transactions: 0`)
- [ ] `quality_trend` contient au plus 30 entrées

### Mémoire épisodique (V9-05-E)
- [ ] `EpisodicMemory().add_decision(...)` retourne un ID non vide
- [ ] `EpisodicMemory().query("libcst")` retourne les décisions contenant "libcst"
- [ ] DB créée automatiquement si absente

### TTS (V9-05-F)
- [ ] `window.lcca.ttsSay("test")` ne crash pas si TTS désactivé
- [ ] `TTS_ENABLED = False` → aucun appel réseau
- [ ] Kokoro absent → fallback silencieux (log.debug uniquement)
