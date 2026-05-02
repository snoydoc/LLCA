============================================================
Fichier : 23-addendum-v8-corrections-post-critique.md
============================================================

# Addendum V8.1 — Corrections Post-Critique Architecture
&lt;!-- AI-READY | Corrections roadmap V8 | Version 8.0.1-rc1 | 2026-04-19 --&gt;

## Vue d'ensemble

Ce document formalise les corrections obligatoires issues de l'analyse critique de la roadmap V8 (fichier 22). Il annule et remplace les sections incohérentes du fichier 22 et ajoute les spécifications manquantes avant tout développement V8.

&gt; **Principe fondateur** : Aucune correction ci-dessous ne modifie la logique métier des 237 tests V5 ni des tests V7. Les changements sont des ajouts structurels ou des précisions de spécification.

---

## 1. Corrections bloquantes (issue de l'analyse critique)

### 1.1 A2A Bus local — Atomicité et fiabilité

#### Problème
Le bus fichier JSON dans `memory/a2a/inbox/{agent}/` expose un risque de :
- Écriture concurrente (deux producteurs, un consommateur)
- Lecture d'un fichier partiellement écrit (crash pendant `write_text`)
- Fuite de messages (jamais consommés, inbox qui grossit)

#### Décision
**Remplacement par une queue SQLite3 avec transactions ACID.** Cohérent avec la stack Python (pas de dépendance externe), atomique, et queryable.

#### Spécification

```python
# core/a2a_bus.py
import sqlite3
import json
import threading
from dataclasses import dataclass, asdict
from typing import Optional, List
from datetime import datetime, timezone
from config import BASE_DIR

A2A_DB_PATH = BASE_DIR / "memory" / "a2a_bus.sqlite"

@dataclass
class A2AMessage:
    id: Optional[int]
    to_agent: str
    from_agent: str
    task_id: str
    payload: dict          # TaskContract sérialisé
    receipt_hash: Optional[str]
    created_at: str
    consumed_at: Optional[str]

class A2ALocalBus:
    """
    Bus A2A local via SQLite3. Garantit :
    - Atomicité lecture/écriture (BEGIN IMMEDIATE)
    - Consommation unique (DELETE après lecture)
    - Pas de fichier partiel (transaction rollback)
    """
    _lock = threading.Lock()
    
    def __init__(self, db_path=A2A_DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS a2a_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    to_agent TEXT NOT NULL,
                    from_agent TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    receipt_hash TEXT,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_to_agent_consumed 
                ON a2a_messages(to_agent, consumed_at)
            """)
            conn.commit()
    
    def send(self, to: str, from_: str, task_id: str, payload: dict) -&gt; int:
        """Retourne l'id du message inséré."""
        msg = A2AMessage(
            id=None,
            to_agent=to,
            from_agent=from_,
            task_id=task_id,
            payload=payload,
            receipt_hash=None,
            created_at=datetime.now(timezone.utc).isoformat(),
            consumed_at=None
        )
        
        with self._lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO a2a_messages 
                   (to_agent, from_agent, task_id, payload, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (msg.to_agent, msg.from_agent, msg.task_id,
                 json.dumps(msg.payload, ensure_ascii=False), msg.created_at)
            )
            conn.commit()
            return cursor.lastrowid
    
    def receive(self, agent: str, timeout_sec: int = 0) -&gt; Optional[A2AMessage]:
        """
        Consommation unique : le message est supprimé immédiatement après lecture.
        Si timeout_sec &gt; 0, boucle jusqu'à trouver un message (polling simple).
        """
        import time
        start = time.time()
        
        while True:
            with self._lock, sqlite3.connect(self.db_path) as conn:
                conn.isolation_level = "IMMEDIATE"
                cursor = conn.execute(
                    """SELECT id, from_agent, task_id, payload, receipt_hash, created_at
                       FROM a2a_messages 
                       WHERE to_agent = ? AND consumed_at IS NULL
                       ORDER BY id ASC LIMIT 1""",
                    (agent,)
                )
                row = cursor.fetchone()
                
                if row:
                    msg = A2AMessage(
                        id=row[0],
                        to_agent=agent,
                        from_agent=row[1],
                        task_id=row[2],
                        payload=json.loads(row[3]),
                        receipt_hash=row[4],
                        created_at=row[5],
                        consumed_at=None
                    )
                    # Marquer consommé puis supprimer dans la même transaction
                    conn.execute(
                        "DELETE FROM a2a_messages WHERE id = ?",
                        (msg.id,)
                    )
                    conn.commit()
                    return msg
            
            if timeout_sec &gt; 0 and (time.time() - start) &lt; timeout_sec:
                time.sleep(0.1)
                continue
            
            return None
    
    def get_queue_depth(self, agent: str) -&gt; int:
        """Observabilité : nombre de messages en attente."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM a2a_messages WHERE to_agent = ? AND consumed_at IS NULL",
                (agent,)
            )
            return cursor.fetchone()[0]

Règle invariante V8 ajoutée :
V8-Règle-21 : Toute communication inter-agent passe par A2ALocalBus. Aucun agent n'accède directement au filesystem d'un autre agent.
1.2 SkillLibrary — Contrôle du budget contexte
Problème
render_as_prompt() injecte tous les skills pertinents. Risque de dépasser MAX_CONTEXT_TOKENS (8000) si la bibliothèque croît.
Décision
Injection contrôlée : top 3 skills par similarité, corps tronqué à 20 lignes, résumé pré-calculé.
Spécification
# core/skill_library.py

@dataclass
class Skill:
    skill_id: str
    name: str
    signature: str
    body: str
    body_summary: str      # Résumé LLM ≤ 3 lignes (généré à la création)
    test_cases: List[dict]
    source_spec: str
    usage_count: int
    success_rate: float

class SkillLibrary:
    MAX_SKILLS_PER_PROMPT = 3
    MAX_BODY_LINES = 20
    
    def render_as_prompt(self, skills: List[Skill]) -> str:
        if len(skills) > self.MAX_SKILLS_PER_PROMPT:
            skills = skills[:self.MAX_SKILLS_PER_PROMPT]
        
        lines = ["# Skills disponibles pour cette tâche\n"]
        
        for s in skills:
            body_display = self._truncate_body(s.body, self.MAX_BODY_LINES)
            lines.append(f"## {s.name}")
            lines.append(f"Signature: {s.signature}")
            lines.append(f"Résumé: {s.body_summary}")
            lines.append("```python")
            lines.append(body_display)
            lines.append("```")
            lines.append("")
        
        prompt = "\n".join(lines)
        
        # Vérification budget tokens (règle V5)
        estimated_tokens = len(prompt) // 4
        if estimated_tokens > MAX_CONTEXT_TOKENS * 0.3:  # Max 30% du budget
            # Fallback : signature + summary uniquement
            return self._render_minimal(skills)
        
        return prompt
    
    def _truncate_body(self, body: str, max_lines: int) -> str:
        lines = body.splitlines()
        if len(lines) <= max_lines:
            return body
        truncated = lines[:max_lines]
        truncated.append(f"# ... ({len(lines) - max_lines} lignes tronquées)")
        return "\n".join(truncated)
    
    def _render_minimal(self, skills: List[Skill]) -> str:
        lines = ["# Signatures de skills pertinents\n"]
        for s in skills:
            lines.append(f"- {s.signature}  # {s.body_summary}")
        return "\n".join(lines)
    
    def generate_summary(self, body: str) -> str:
        """
        Appelé une seule fois à la création du skill.
        Peut utiliser Ollama local (qwen) pour résumer.
        """
        # Fallback si Ollama indisponible : première ligne + docstring
        lines = body.strip().splitlines()
        docstring = ""
        in_docstring = False
        for line in lines:
            if '"""' in line or "'''" in line:
                in_docstring = not in_docstring
                continue
            if in_docstring:
                docstring += line.strip()
        return docstring[:200] or lines[0][:200]

1.3 Karpathy Loop — Anti-régression et convergence sûre
Problème
Optimisation sur une seule métrique = risque de surapprentissage (code qui passe le test cible mais casse le reste). Pas de détection de stagnation.
Décision
Deux métriques obligatoires : succès fonctionnel + qualité statique
Test de non-régression : exécution de la suite de tests existante avant validation
Arrêt après 3 itérations sans amélioration (règle 18 V8)
Spécification
# core/karpathy_loop.py
from dataclasses import dataclass
from typing import Callable, List, Tuple
from core.code_evaluator import CodeEvaluator

@dataclass
class KarpathyMetrics:
    functional_score: float  # 0-1 (tests passent)
    quality_score: int       # 0-100 (CodeEvaluator)
    regression_passed: bool  # Ancienne suite OK ?
    
    @property
    def composite(self) -> float:
        """Score composite pondéré. Functional pèse 60%, quality 40%."""
        if not self.regression_passed:
            return 0.0
        return (self.functional_score * 0.6) + (self.quality_score / 100 * 0.4)

class KarpathyLoop:
    MAX_STAGNATION = 3
    
    def iterate(
        self,
        base_code: str,
        evaluate_fn: Callable[[str], KarpathyMetrics],
        mutate_fn: Callable[[str, float], str],  # code, temperature -> variant
        max_iterations: int = 20
    ) -> Tuple[str, KarpathyMetrics]:
        """
        Boucle d'amélioration avec anti-stagnation et non-régression.
        """
        best_code = base_code
        best_metrics = evaluate_fn(base_code)
        stagnation = 0
        
        for i in range(max_iterations):
            if stagnation >= self.MAX_STAGNATION:
                break
            
            temperature = 0.3 + (i * 0.05)  # Exploration croissante
            variant = mutate_fn(best_code, temperature)
            metrics = evaluate_fn(variant)
            
            if metrics.composite > best_metrics.composite:
                best_code = variant
                best_metrics = metrics
                stagnation = 0
            else:
                stagnation += 1
        
        return best_code, best_metrics

    def evaluate_with_regression(
        self,
        candidate_code: str,
        target_file: str,
        sandbox_fn: Callable,
        existing_tests_fn: Callable
    ) -> KarpathyMetrics:
        """
        Évalue un candidat avec test de non-régression.
        """
        # 1. Sandbox cible
        functional_ok, _, _ = sandbox_fn(candidate_code)
        
        # 2. Qualité statique
        evaluator = CodeEvaluator()
        quality = evaluator.evaluate(candidate_code, filename=target_file)
        
        # 3. Non-régression (obligatoire)
        regression_ok = existing_tests_fn()
        
        return KarpathyMetrics(
            functional_score=1.0 if functional_ok else 0.0,
            quality_score=quality.score,
            regression_passed=regression_ok
        )

1.4 Dépréciation de NLOrchestrator — Transition en douceur
Problème
Suppression brutale de NLOrchestrator et main_nl.py = rupture de rétrocompatibilité.
Décision
V8.0 : NLOrchestrator déprécié avec DeprecationWarning, redirection vers AgenticAdapter
V8.1 : Suppression effective après migration
Spécification
# core/nl_orchestrator_v8_adapter.py
import warnings
from core.agents.architect import ArchitectAgent
from core.a2a_bus import A2ALocalBus

class NLOrchestratorV8Adapter:
    """
    Adaptateur rétrocompatible. Transfère les requêtes NL vers l'Architect via A2A.
    """
    def __init__(self):
        warnings.warn(
            "NLOrchestrator est déprécié en V8. Utilisez AgenticAdapter ou le bus A2A.",
            DeprecationWarning,
            stacklevel=2
        )
        self.bus = A2ALocalBus()
        self.architect = "architect"
    
    def run(self, command: str) -> dict:
        # Envoi au bus A2A pour traitement par l'Architect
        self.bus.send(
            to=self.architect,
            from_="nl_adapter",
            task_id=f"nl_{hash(command) % 10000}",
            payload={"intent": command, "source": "nl_legacy"}
        )
        
        # Attente du résultat (timeout 60s)
        msg = self.bus.receive("nl_adapter", timeout_sec=60)
        if msg:
            return msg.payload
        return {"success": False, "error": "Timeout agentique"}

1.5 RecoveryPolicy par agent — Spécification manquante
Spécification ajoutée
# core/agents/recovery_policy.py
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class RecoveryPolicy:
    """
    Politique de récupération par agent. 
    Chaque agent expose sa politique dans son AgentCard.
    """
    max_retries: int = 1
    retry_delay_sec: float = 0.5
    fallback_agent: Optional[str] = None   # ex: "architect" pour escalation
    on_failure: str = "rollback"           # "rollback" | "retry" | "escalate"
    retry_conditions: List[str] = None     # ["SyntaxError", "Timeout"]
    
    def __post_init__(self):
        assert self.on_failure in ("rollback", "retry", "escalate")
        if self.retry_conditions is None:
            self.retry_conditions = []
    
    def should_retry(self, error_type: str, attempt: int) -> bool:
        if self.on_failure != "retry":
            return False
        if attempt >= self.max_retries:
            return False
        return error_type in self.retry_conditions or not self.retry_conditions

# Politiques par défaut
ARCHITECT_POLICY = RecoveryPolicy(
    max_retries=2,
    on_failure="escalate",
    fallback_agent=None  # L'architecte est le dernier recours
)

CODER_POLICY = RecoveryPolicy(
    max_retries=1,
    on_failure="rollback",
    fallback_agent="architect",
    retry_conditions=["SyntaxError"]
)

REVIEWER_POLICY = RecoveryPolicy(
    max_retries=0,
    on_failure="escalate",
    fallback_agent="architect"
)

TESTER_POLICY = RecoveryPolicy(
    max_retries=2,
    on_failure="retry",
    retry_conditions=["Timeout", "ResourceExhausted"]
)

1.6 lcca_receipts — Gestion sécurisée des clés HMAC
Problème
Clé HMAC non spécifiée, stockage non défini, pas de rotation.
Décision
Clé stockée dans .secret/a2a_key (hors git)
Commande CLI lcca rotate-keys pour rotation
Anciens receipts invalidés = acceptable (audit local uniquement)
Spécification
# core/receipt_store.py
import hmac
import hashlib
import secrets
from pathlib import Path
from config import BASE_DIR

SECRET_DIR = BASE_DIR / ".secret"
KEY_PATH = SECRET_DIR / "a2a_key"

def _ensure_key() -> bytes:
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        key = secrets.token_hex(32).encode()
        KEY_PATH.write_bytes(key)
        # Protection filesystem (Unix)
        import os
        os.chmod(KEY_PATH, 0o600)
    return KEY_PATH.read_bytes()

def sign_receipt(task_id: str, output_hash: str) -> str:
    key = _ensure_key()
    payload = f"{task_id}:{output_hash}".encode()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()

def verify_receipt(task_id: str, output_hash: str, signature: str) -> bool:
    expected = sign_receipt(task_id, output_hash)
    return hmac.compare_digest(expected, signature)

def rotate_key() -> int:
    """
    Régénère la clé HMAC. Retourne le nombre de receipts invalidés.
    C'est une opération de maintenance manuelle.
    """
    # Invalider tous les receipts existants
    receipt_dir = BASE_DIR / "memory" / "receipts"
    count = 0
    if receipt_dir.exists():
        for f in receipt_dir.glob("*.json"):
            f.rename(f.with_suffix(".invalid"))
            count += 1
    
    # Nouvelle clé
    KEY_PATH.unlink(missing_ok=True)
    _ensure_key()
    return count

2. Améliorations suggérées (intégrées à la spec)
2.1 Agent Observer — Maintenance mémoire
# core/agents/observer.py
class ObserverAgent:
    """
    Agent passif. Pas dans le pipeline critique.
    S'exécute périodiquement (ou sur demande) pour :
    - Dédoublonner les skills (même signature)
    - Archiver les receipts de plus de 30 jours
    - Compacter les réflexions obsolètes
    - Générer les résumés de skills manquants
    """
    def deduplicate_skills(self):
        """Supprime les skills avec signature identique, garde le plus récent."""
        pass
    
    def archive_old_receipts(self, days: int = 30):
        """Déplace les vieux receipts dans receipts_archive/."""
        pass

2.2 Skill — Import direct sans réécriture
# core/skill_library.py

def inject_skill_as_module(self, skill: Skill, namespace: dict):
    """
    Injecte un skill dans un namespace Python (globals/locals)
    pour exécution sandbox sans réécriture LLM.
    """
    exec(compile(skill.body, f"<skill_{skill.name}>", "exec"), namespace)

2.3 Karpathy Loop — Métrique de nouveauté
# core/karpathy_loop.py

def novelty_score(self, candidate: str, previous: List[str]) -> float:
    """
    1.0 = complètement nouveau, 0.0 = déjà vu.
    Empêche la convergence vers un optimum local déjà exploré.
    """
    import difflib
    if not previous:
        return 1.0
    
    similarities = [difflib.SequenceMatcher(None, candidate, p).ratio() 
                    for p in previous]
    return 1.0 - max(similarities)

2.4 Journal de décisions agents
# core/agent_decision_log.py
@dataclass
class AgentDecision:
    timestamp: str
    agent: str
    task_id: str
    decision: str          # "decompose" | "reuse_skill" | "retry"
    rationale: str         # Pourquoi cette décision
    context_summary: str   # 200 caractères du contexte

class DecisionLogger:
    PATH = BASE_DIR / "logs" / "agent_decisions.jsonl"
    
    def log(self, decision: AgentDecision):
        with open(self.PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(decision), ensure_ascii=False) + "\n")

. Corrections de cohérence interne
3.1 Fusion lcca_reflexions → lcca_failures
Correction : Pas de collection lcca_reflexions séparée. Le champ reflection est ajouté aux entrées lcca_failures.
# MemoryEntry pour lcca_failures (extension)
{
    "collection": "lcca_failures",
    "content": "...",           # Erreur brute
    "reflection": "...",        # Réflexion structurée (nouveau)
    "fix": "...",               # Correctif appliqué
    "verified": True,
    # ... métadonnées standard ...
}

3.2 generate_spec — Outil interne de l'Architect
Correction : generate_spec reste un outil interne (pas exposé au MCP client), utilisé exclusivement par ArchitectAgent pour produire des TaskContracts.
# core/agents/architect.py
class ArchitectAgent:
    def _generate_spec(self, intent: str, domain: str) -> SpecEntry:
        """Non exposé au MCP. Usage interne uniquement."""
        # ... logique de l'addendum 21 ...
        pass

3.3 main.py --mode=agentic — Spécification du point d'entrée
# main.py (ajout d'argument)
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["direct", "agentic"], default="direct")
    # ...
    
    if args.mode == "agentic":
        # Lancer les 4 agents + bus A2A
        from core.agents.agent_orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        orch.boot()
        orch.repl()  # REPL agentique
    else:
        # Mode direct V5/V7
        lcca = LCCAV5Fusion()
        # ...

4. Tests complémentaires V8 (ajouts à la suite fichier 22)
| Suite       | Fichier                   | Cas test                                                                          | Priorité |
| ----------- | ------------------------- | --------------------------------------------------------------------------------- | -------- |
| A2A         | `test_a2a_bus.py`         | `test_message_atomic_consumption` — deux threads consomment, un seul reçoit       | CRITIQUE |
| A2A         | `test_a2a_bus.py`         | `test_crash_during_write_recovery` — coupure pendant send, pas de message fantôme | CRITIQUE |
| A2A         | `test_a2a_bus.py`         | `test_agent_cannot_consume_from_other_inbox` — bus isolation                      | HAUTE    |
| Skills      | `test_skill_library.py`   | `test_prompt_budget_respected` — 30 skills trouvés, top 3 injectés                | HAUTE    |
| Skills      | `test_skill_library.py`   | `test_skill_deduplication` — deux skills même signature, un conservé              | MOYENNE  |
| Karpathy    | `test_karpathy_loop.py`   | `test_stops_after_3_no_improvement` — stagnation détectée                         | HAUTE    |
| Karpathy    | `test_karpathy_loop.py`   | `test_regression_failure_zero_score` — regression = score 0                       | HAUTE    |
| Recovery    | `test_recovery_policy.py` | `test_coder_retries_syntaxerror` — retry conditionnel                             | MOYENNE  |
| Security    | `test_receipt_store.py`   | `test_hmac_key_rotation_invalidates_old` — rotation fonctionne                    | MOYENNE  |
| Retrocompat | `test_nl_adapter.py`      | `test_nlorchestrator_v8_redirect` — ancien code fonctionne                        | HAUTE    |
| Intégration | `test_agentic_mode.py`    | `test_main_agentic_boots_all_agents` --mode=agentic OK                            | HAUTE    |

5. Checklist validation V8.1 (avant merge)
[ ] A2ALocalBus utilise SQLite3 (pas de fichier JSON partagé)
[ ] SkillLibrary.render_as_prompt() respecte le budget 30% tokens
[ ] KarpathyLoop arrêt après 3 stagnations, score composite double métrique
[ ] NLOrchestratorV8Adapter émet DeprecationWarning et redirige vers A2A
[ ] RecoveryPolicy définie pour chaque agent, exposée dans AgentCard
[ ] receipt_store.py utilise .secret/a2a_key (hors git, chmod 600)
[ ] rotate_key() documentée comme opération de maintenance manuelle
[ ] lcca_failures contient le champ reflection (pas de collection séparée)
[ ] ArchitectAgent._generate_spec est privé (pas exposé MCP)
[ ] main.py --mode=agentic démarre AgentOrchestrator
[ ] Les 237 tests V5 restent verts
[ ] Les tests V7 (Spec Layer) restent verts
[ ] Nouveaux tests V8.1 (section 4) passent
<!-- AI-READY | Addendum V8.1 corrections | 2026-04-19 -->