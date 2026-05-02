# 🏥 Sprint 08 — MediBot Adapter (Bonus)

> **Durée estimée** : 3 jours  
> **Statut** : ⚪ À FAIRE  
> **Priorité** : 🟢 Basse (Bonus — dépend de Sprint 07 terminé)  
> **Dépend de** : Sprint 04 (Orchestrateur), Sprint 05 (MemPalace), Sprint 07 (CLI stable)  
> **Objectif** : Connecter LCCA V5 Fusion au projet MediBot existant (`D:\MediBot`) via un orchestrateur spécialisé et l'adaptateur MemPalace existant.

---

## 🎯 Objectifs du Sprint

Ce sprint bonus adapte LCCA pour travailler directement sur le projet MediBot sans reconfiguration manuelle :
- Se connecte au MemPalace MediBot existant (`D:\MediBot\Mempalace`)
- Charge les specs MediBot pour enrichir automatiquement le contexte
- Indexe le code MediBot dans `workspace/`
- Fournit un entry point dédié `main_medi.py`

> **Note** : Ce sprint est non-bloquant. LCCA V5 Fusion est fully fonctionnel sans cela (Sprint 07 = livraison stable). Ce sprint ne fait qu'améliorer l'expérience pour le projet MediBot spécifiquement.

---

## 📋 Tâches

### TASK-08-01 — `ExistingMemPalaceAdapter` — Finalisation
**Priorité** : 🟠 Haute  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/mempalace_adapter.py`

**Description** :  
Finaliser et tester l'adaptateur qui se connecte au MemPalace MCP existant à `D:\MediBot\Mempalace`. Cf. spec V5 — section `core/mempalace_adapter.py`.

**Points d'attention par rapport à la spec** :

1. **API ChromaDB ≥ 0.4** : Remplacer l'ancienne API `Settings(chroma_db_impl=...)` par `PersistentClient(path=...)` :
```python
# ❌ Ancienne API (spec V5 — obsolète)
self.client = chromadb.Client(Settings(
    chroma_db_impl="duckdb+parquet",
    persist_directory=chroma_path
))

# ✅ Nouvelle API (≥ 0.4)
self.client = chromadb.PersistentClient(path=chroma_path)
```

2. **Détection auto du chemin** — ordre de priorité :
```python
CANDIDATE_PATHS = [
    Path(r"D:\MediBot\Mempalace\memory_palace"),  # Sous-dossier palace
    Path(r"D:\MediBot\Mempalace"),                  # Racine
    Path.home() / ".mempalace" / "palace",          # Fallback standard
]
```

3. **Lecture seule du palace existant** : L'adapter ne doit **jamais supprimer** de données du palace MediBot. Les `mine_content()` vont dans une collection dédiée `lcca_v5_*` pour ne pas polluer les collections MediBot existantes.

**Collections isolées pour LCCA** :
```python
# Collections LCCA dans le palace MediBot (préfixe lcca_ pour isolation)
self.lcca_collections = {
    "transactions": palace.get_or_create_collection("lcca_transactions"),
    "index": palace.get_or_create_collection("lcca_ast_index"),
    "sessions": palace.get_or_create_collection("lcca_sessions")
}
```

**Critères d'acceptation** :
- [ ] Connexion à `D:\MediBot\Mempalace` si le dossier existe (sinon fallback silencieux)
- [ ] Collections `lcca_*` créées sans modifier les collections MediBot existantes
- [ ] `_load_specs()` charge tous les `.md` du dossier `specs/`
- [ ] `wake_up_medi()` retourne l'identity MediBot + specs pertinentes
- [ ] `ExistingMemPalaceAdapter` est un sous-type de `MemPalaceClient` (Liskov)

---

### TASK-08-02 — `MediBotOrchestrator` — Orchestrateur spécialisé
**Priorité** : 🟠 Haute  
**Effort** : 1 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `core/orchestrator_medi.py`

**Description** :  
Sous-classe de `LCCAV5Fusion` pré-configurée pour MediBot : workspace pointant vers le code MediBot, MemPalace existant, et enrichissement automatique du contexte médical.

**Configuration automatique** :
```python
class MediBotOrchestrator(LCCAV5Fusion):
    
    MEDI_WORKSPACE = Path(r"D:\MediBot")  # Workspace MediBot réel
    
    def __init__(self):
        # 1. Connexion au palace existant
        self.palace = ExistingMemPalaceAdapter()
        
        # 2. Workspace = code MediBot (non pas le workspace LCCA vide)
        self.workspace = self.MEDI_WORKSPACE
        
        # 3. Initialisation composants avec palace MediBot
        self.tx_manager = TransactionManager(self.palace, str(self.workspace))
        self.indexer = ASTIndexer(str(self.workspace))
        self.patcher = SmartPatcher(str(self.workspace))
        self.planner = MultiFilePlanner(self.indexer, self.palace)
        self.recovery = RecoveryService(self.tx_manager)
        
        # 4. Chargement contexte MediBot
        self.medi_context = self.palace.wake_up_medi()
        
        # 5. Indexation du code MediBot
        log.info(f"Indexation workspace MediBot: {self.workspace}")
        self.indexer.index_repository()
        
        # 6. Recovery
        orphans = self.recovery.boot_check()
        if orphans:
            self.recovery.auto_recover_pending(orphans)
```

**Enrichissement automatique du contexte** :
```python
def _enrich_with_medi_context(self, intent: Intent) -> str:
    """
    Enrichit l'intent avec des specs MediBot pertinentes.
    Cherche dans les specs chargées par l'adapter.
    """
    relevant_specs = []
    keywords = [
        w.lower() for w in [intent.target, intent.sub_target, intent.details]
        if w
    ]
    
    for spec in self.palace.specs:
        content_lower = spec["content"].lower()
        if any(kw in content_lower for kw in keywords):
            # Prend les 300 premiers chars de la spec pertinente
            excerpt = spec["content"][:300].replace('\n', ' ')
            relevant_specs.append(f"[{spec['name']}]: {excerpt}")
    
    return "\n".join(relevant_specs[:2])  # Max 2 specs pour économiser tokens
```

**Critères d'acceptation** :
- [ ] `MediBotOrchestrator()` s'initialise si `D:\MediBot` existe
- [ ] Lève `FileNotFoundError` avec message clair si `D:\MediBot` introuvable
- [ ] Indexation du code MediBot complète au démarrage
- [ ] Enrichissement contexte ajoute les specs pertinentes au prompt

---

### TASK-08-03 — `main_medi.py` — Entry point MediBot
**Priorité** : 🟡 Normale  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `main_medi.py`

**Description** :  
Entry point dédié au projet MediBot avec mode interactif (REPL) et mode commande directe.

**Fonctionnalités** :
- Mode commande directe: `python main_medi.py "DashboardV1 - RDV - Ajoute export_pdf()"`
- Mode interactif REPL avec historique des commandes (dernières 20)
- Affichage du contexte MediBot chargé au démarrage
- Vérification connexion MemPalace avant tout

**Mode interactif** :
```python
def run_repl(orchestrator: MediBotOrchestrator):
    """REPL interactif avec historique."""
    history = []
    print("\n💡 Commandes spéciales: 'exit', 'status', 'history', 'dry:<commande>'")
    
    while True:
        try:
            cmd = input("\nMediBot> ").strip()
            
            if not cmd:
                continue
            if cmd.lower() in ['exit', 'quit', 'q']:
                print("À bientôt 👋")
                break
            if cmd.lower() == 'status':
                # Affiche stats workspace
                print(f"📁 {len(orchestrator.indexer.files)} fichiers indexés")
                print(f"🧠 {len(orchestrator.indexer.symbols_table)} symboles")
                continue
            if cmd.lower() == 'history':
                for i, h in enumerate(history[-20:], 1):
                    print(f"  {i:2d}. {h}")
                continue
            if cmd.lower().startswith('dry:'):
                orchestrator.dry_run(cmd[4:].strip())
                continue
            
            history.append(cmd)
            orchestrator.execute_with_medi_context(cmd)
            
        except KeyboardInterrupt:
            print("\nCtrl+C — taper 'exit' pour quitter")
        except Exception as e:
            log.error(f"Erreur: {e}")
```

**Critères d'acceptation** :
- [ ] `python main_medi.py --help` affiche l'aide
- [ ] Mode direct: `python main_medi.py "commande"` → exécute et quitte
- [ ] Mode REPL: `python main_medi.py` → boucle interactive
- [ ] `history` dans le REPL affiche les 20 dernières commandes
- [ ] `dry:commande` dans le REPL → dry_run sans exécution

---

### TASK-08-04 — Tests de connexion MediBot
**Priorité** : 🟡 Normale  
**Effort** : 0.5 jour  
**Statut** : ⚪ À FAIRE

**Fichier cible** : `tests/test_medibot_adapter.py`

**Description** :  
Tests avec mocking du filesystem pour ne pas dépendre de la présence physique de `D:\MediBot`.

```python
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture
def mock_palace_path(tmp_path):
    """Crée une structure MemPalace factice pour les tests."""
    palace = tmp_path / "Mempalace" / "memory_palace"
    palace.mkdir(parents=True)
    
    # Fichiers requis
    (palace / "identity.txt").write_text("MediBot LCCA Identity")
    (palace / "chroma.sqlite3").write_bytes(b"")  # Placeholder
    
    specs = palace / "specs"
    specs.mkdir()
    (specs / "architecture.md").write_text("# MediBot Architecture\nModule RDV: gestion des rendez-vous")
    (specs / "rdv-spec.md").write_text("# Spec RDV\nvalidation email obligatoire")
    
    return palace


def test_adapter_loads_identity(mock_palace_path):
    """Identity chargée depuis identity.txt."""

def test_adapter_loads_specs(mock_palace_path):
    """Specs .md chargées depuis specs/."""

def test_adapter_fallback_if_no_palace(tmp_path):
    """Si palace introuvable → FileNotFoundError avec message clair."""

def test_wake_up_medi_returns_context(mock_palace_path):
    """wake_up_medi() retourne identity + specs."""

def test_lcca_collections_isolated(mock_palace_path):
    """Collections lcca_* créées sans toucher aux autres."""
```

**Critères d'acceptation** :
- [ ] `pytest tests/test_medibot_adapter.py` → 5/5 (sans nécessiter `D:\MediBot` réel)
- [ ] Tests utilisent des mocks pour ChromaDB (pas de vraie DB)

---

## 📊 Récapitulatif Sprint 08

| Task | Description | Effort | Statut |
|------|------------|--------|--------|
| TASK-08-01 | ExistingMemPalaceAdapter | 1j | ⚪ |
| TASK-08-02 | MediBotOrchestrator | 1j | ⚪ |
| TASK-08-03 | `main_medi.py` REPL | 0.5j | ⚪ |
| TASK-08-04 | Tests MediBot adapter | 0.5j | ⚪ |
| **TOTAL** | | **3j** | |

---

## ✅ Définition of Done (Sprint 08)

- [ ] `pytest tests/test_medibot_adapter.py` → 0 erreur
- [ ] `python main_medi.py --status` (si `D:\MediBot` existe) → connexion OK + stats
- [ ] `python main_medi.py` → mode REPL fonctionnel
- [ ] Collections `lcca_*` créées sans modifier le palace MediBot existant
- [ ] `003-project-context.md` mis à jour avec les nouveaux fichiers

---

## ⚠️ Contraintes & Risques

| Risque | Probabilité | Mitigation |
|--------|------------|------------|
| Code MediBot utilise des patterns libcst ne supporte pas | Moyenne | Tester sur fichiers réels avant Sprint 08 |
| Indexation `D:\MediBot` trop lente (beaucoup de fichiers) | Faible | Limiter l'indexation aux dossiers pertinents (exclude `venv/`, `node_modules/`) |
| Palace MediBot vide ou schema différent | Moyenne | `wake_up_medi()` doit être défensive (try/except sur chaque layer) |
| Conflits de noms entre collections LCCA et MediBot | Faible | Préfixe `lcca_` sur toutes les collections LCCA |

---

## 🔗 Navigation

⬅️ [Sprint 07 — CLI & Tests](sprint-07-cli-tests.md)  
🏁 Fin du planning — Projet LCCA V5 Fusion complet

---

## 📌 Post-Sprint 08 : Idées pour V2 (ne pas implémenter maintenant)

Ces idées sont listées ici pour ne pas les oublier, mais sont **hors scope** de la V1 :

- [ ] Intégration Ollama pour génération code automatique (remplacer le placeholder `_generate_code_for_op`)
- [ ] Interface GUI Tkinter avec visualisation du graphe de dépendances
- [ ] Sandbox Docker pour exécution du code généré en isolation
- [ ] Support multi-langage : JavaScript/TypeScript via Babel AST
- [ ] Mode collaboration : plusieurs instances LCCA sur le même workspace
- [ ] Export rapport HTML des transactions
