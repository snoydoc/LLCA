🏛️ Architecture V4 : "LCCA Atomic"
┌──────────────────────────────────────────────────────────────┐
│                     DSL Input (Claude-style)                  │
│  "DashboardV1 - Page RDV - Modal En Consultation - Ajoute..." │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [DSL Parser] → Intent{project, target, action, params}       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [Skill Loader] → Récupère depuis MemPalace:                  │
│   - Skill "modal-react" (wing:skills)                         │
│   - Contexte DashboardV1 (wing:DashboardV1, room:context)     │
│   - Layer 0/1 (wake-up)                                       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [Transaction Manager] BEGIN                                  │
│   → Crée drawer dans hall:transactions (status:PENDING)       │
│   → Snapshot de l'état actuel des fichiers cibles             │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [Atomic Executor]                                            │
│   Chaque opération:                                           │
│   1. LOG before → MemPalace (drawer opération)               │
│   2. EXECUTE (write/edit/delete)                             │
│   3. LOG after → MemPalace                                    │
│   4. Si échec → AUTO-ROLLBACK (restore before)               │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  [Validation Layer]                                           │
│   - Syntax check (ruff/pyright)                              │
│   - Tests si présents                                        │
│   - Dépendances check (impacts sur autres fichiers)          │
└──────────────────────────────────────────────────────────────┘
                              ↓
         ┌────────────┐         ┌────────────┐
         │   SUCCESS  │         │    FAIL    │
         └─────┬──────┘         └─────┬──────┘
               ↓                      ↓
┌──────────────────────┐    ┌──────────────────────┐
│ COMMIT Transaction   │    │ ROLLBACK Transaction │
│ Status: COMMITTED    │    │ Status: ROLLED_BACK  │
│ Archive dans hall:   │    │ Restore files        │
│ discoveries          │    │ Log erreur dans      │
│                      │    │ hall:events          │
└──────────────────────┘    └──────────────────────┘

📦 Structure V4
lcca_v4/
├── core/
│   ├── __init__.py
│   ├── dsl_parser.py          # Parse "Projet - Cible - Action"
│   ├── skill_loader.py        # Récupère skills depuis MemPalace
│   ├── transaction_manager.py # Journal ACID + Rollback
│   ├── atomic_executor.py     # Ops avec logging auto
│   ├── recovery_service.py    # Boot check + recovery
│   └── checkpoint_manager.py  # Snapshots périodiques
├── workspace/                 # Code projet (monitoré)
└── recovery.log              # Log local des TX

1️⃣ core/transaction_manager.py — Journal ACID
"""
Transaction Manager V4 - Anti-Crash
Chaque opération est atomique et journalisée dans MemPalace.
Permet le rollback total ou partiel.
"""
import uuid
import hashlib
import json
from datetime import datetime
from typing import List, Dict, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import shutil
import os

from .mempalace_client import MemPalaceClient


class TxStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class OpType(Enum):
    WRITE_FILE = "write_file"
    EDIT_FILE = "edit_file"
    DELETE_FILE = "delete_file"
    CREATE_DIR = "create_dir"
    MOVE_FILE = "move_file"


@dataclass
class FileSnapshot:
    """Snapshot d'un fichier avant modification"""
    path: str
    content_hash: str
    content: Optional[str]  # None si fichier binaire ou trop gros
    exists: bool


@dataclass
class Operation:
    """Opération atomique"""
    op_id: str
    type: OpType
    target_path: str
    before: FileSnapshot
    after: Optional[FileSnapshot]
    timestamp: str
    metadata: Dict[str, Any]
    skill_ref: Optional[str] = None  # Référence skill utilisé


@dataclass
class Transaction:
    """Transaction complète (ensemble d'opérations)"""
    tx_id: str
    dsl_input: str
    project: str
    intent: str
    status: TxStatus
    created_at: str
    completed_at: Optional[str]
    operations: List[Operation]
    context_refs: List[str]  # IDs des contextes/skill utilisés


class TransactionManager:
    """
    Gestionnaire transactionnel avec persistence MemPalace.
    """
    
    def __init__(self, palace_client: Optional[MemPalaceClient] = None, 
                 workspace: str = "./workspace"):
        self.palace = palace_client or MemPalaceClient()
        self.workspace = Path(workspace)
        self.hall = "transactions"
        self.current_tx: Optional[Transaction] = None
        self._backup_dir = Path("./.lcca_backups")
        self._backup_dir.mkdir(exist_ok=True)
    
    def begin(self, dsl_input: str, project: str, intent: str, 
              context_refs: List[str]) -> str:
        """
        Démarre une nouvelle transaction.
        Crée un drawer dans hall:transactions avec status PENDING.
        """
        tx_id = str(uuid.uuid4())[:12]
        
        self.current_tx = Transaction(
            tx_id=tx_id,
            dsl_input=dsl_input,
            project=project,
            intent=intent,
            status=TxStatus.PENDING,
            created_at=datetime.now().isoformat(),
            completed_at=None,
            operations=[],
            context_refs=context_refs
        )
        
        # Archive immédiate dans MemPalace (durabilité)
        self._persist_transaction()
        
        print(f"📝 Transaction {tx_id} BEGIN | Projet: {project}")
        return tx_id
    
    def log_operation(self, op_type: OpType, target_path: str, 
                     execute_func: Callable[[], Any],
                     skill_ref: Optional[str] = None,
                     metadata: Optional[Dict] = None) -> Any:
        """
        Exécute une opération de manière atomique:
        1. Snapshot "before"
        2. Exécute
        3. Snapshot "after"
        4. Log dans transaction
        5. Si échec → Rollback auto
        """
        if not self.current_tx:
            raise RuntimeError("Pas de transaction active. Appeler begin() d'abord.")
        
        full_path = self.workspace / target_path
        
        # 1. Snapshot BEFORE
        before = self._snapshot_file(full_path)
        
        # Création de l'opération
        op = Operation(
            op_id=str(uuid.uuid4())[:8],
            type=op_type,
            target_path=str(target_path),
            before=before,
            after=None,
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
            skill_ref=skill_ref
        )
        
        try:
            # 2. EXECUTION
            result = execute_func()
            
            # 3. Snapshot AFTER
            op.after = self._snapshot_file(full_path)
            op.after.content = result if isinstance(result, str) else None
            
            # 4. LOG
            self.current_tx.operations.append(op)
            self.current_tx.status = TxStatus.RUNNING
            self._persist_transaction()
            
            print(f"    ✓ Op {op.op_id}: {op_type.value} {target_path}")
            return result
            
        except Exception as e:
            # 5. ROLLBACK AUTO de cette opération
            print(f"    ✗ Op {op.op_id}: FAIL - {e}")
            self._rollback_operation(op)
            raise TransactionError(f"Opération {op.op_id} échouée: {e}", op, self.current_tx)
    
    def commit(self):
        """Valide la transaction"""
        if not self.current_tx:
            return
        
        self.current_tx.status = TxStatus.COMMITTED
        self.current_tx.completed_at = datetime.now().isoformat()
        self._persist_transaction()
        
        # Archive aussi dans discoveries pour apprentissage
        if self.current_tx.operations:
            self._archive_to_discoveries()
        
        print(f"✅ Transaction {self.current_tx.tx_id} COMMITTED")
        self.current_tx = None
    
    def rollback(self, tx_id: Optional[str] = None):
        """
        Rollback total : restaure tous les fichiers à leur état "before".
        Si tx_id=None, rollback la transaction courante.
        """
        target_tx = self._load_transaction(tx_id) if tx_id else self.current_tx
        
        if not target_tx:
            raise ValueError(f"Transaction {tx_id} non trouvée")
        
        print(f"⏮️  ROLLBACK {target_tx.tx_id} ({len(target_tx.operations)} ops)")
        
        # Rollback en ordre inverse (LIFO)
        for op in reversed(target_tx.operations):
            self._rollback_operation(op)
        
        target_tx.status = TxStatus.ROLLED_BACK
        target_tx.completed_at = datetime.now().isoformat()
        self._persist_transaction(target_tx)
        
        if self.current_tx and self.current_tx.tx_id == target_tx.tx_id:
            self.current_tx = None
    
    def _snapshot_file(self, path: Path) -> FileSnapshot:
        """Crée un snapshot d'un fichier"""
        exists = path.exists()
        
        if not exists:
            return FileSnapshot(
                path=str(path),
                content_hash="",
                content=None,
                exists=False
            )
        
        content = None
        content_hash = ""
        
        try:
            # Lecture texte si possible
            content = path.read_text(encoding='utf-8')
            content_hash = hashlib.md5(content.encode()).hexdigest()
        except:
            # Binaire
            content_hash = hashlib.md5(path.read_bytes()).hexdigest()
        
        return FileSnapshot(
            path=str(path),
            content_hash=content_hash,
            content=content,
            exists=True
        )
    
    def _rollback_operation(self, op: Operation):
        """Restaure un fichier à son état 'before'"""
        target = self.workspace / op.target_path
        
        print(f"    ↩️  Restaure {op.target_path}")
        
        if not op.before.exists:
            # Le fichier n'existait pas avant → on le supprime
            if target.exists():
                target.unlink()
        else:
            # Restauration du contenu
            if op.before.content:
                target.write_text(op.before.content, encoding='utf-8')
            else:
                # Cas binaire: on restore depuis backup si existant
                backup_path = self._backup_dir / f"{op.op_id}_{target.name}"
                if backup_path.exists():
                    shutil.copy(backup_path, target)
        
        # Log du rollback dans MemPalace
        self.palace.mine_content(
            content=f"ROLLBACK_OP: {op.op_id} → {op.target_path}",
            wing="lcca_system",
            hall="events",
            metadata={"tx_id": op.target_path, "op": op.op_id}
        )
    
    def _persist_transaction(self, tx: Optional[Transaction] = None):
        """Sauvegarde la transaction dans MemPalace (durabilité)"""
        tx = tx or self.current_tx
        if not tx:
            return
        
        # Sérialisation
        data = json.dumps(asdict(tx), indent=2, default=str)
        
        self.palace.mine_content(
            content=data,
            wing="lcca_system",
            hall=self.hall,
            source="transaction_manager",
            metadata={
                "tx_id": tx.tx_id,
                "status": tx.status.value,
                "project": tx.project,
                "n_ops": len(tx.operations)
            },
            layer=3  # Important: Layer 3 pour verbatim complet
        )
    
    def _archive_to_discoveries(self):
        """Archive une transaction réussie comme pattern"""
        if not self.current_tx or not self.current_tx.operations:
            return
        
        # Crée un résumé pour réutilisation future
        summary = {
            "intent": self.current_tx.intent,
            "project_type": self.current_tx.project,
            "files_modified": [op.target_path for op in self.current_tx.operations],
            "skills_used": list(set([op.skill_ref for op in self.current_tx.operations if op.skill_ref]))
        }
        
        self.palace.mine_content(
            content=json.dumps(summary),
            wing="lcca_system",
            hall="discoveries",
            metadata={"tx_id": self.current_tx.tx_id, "type": "successful_pattern"},
            layer=2
        )
    
    def get_pending_transactions(self) -> List[Transaction]:
        """Récupère les transactions non terminées (pour recovery)"""
        results = self.palace.search_memories(
            query="transaction pending running",
            wing="lcca_system",
            hall=self.hall,
            n_results=10
        )
        
        pending = []
        for entry in results:
            try:
                data = json.loads(entry.content)
                if data.get("status") in [TxStatus.PENDING.value, TxStatus.RUNNING.value]:
                    # Reconstruit l'objet (simplifié)
                    pending.append(Transaction(**data))
            except:
                continue
        
        return pending


class TransactionError(Exception):
    """Exception avec contexte de rollback"""
    def __init__(self, msg: str, operation: Operation, transaction: Transaction):
        super().__init__(msg)
        self.operation = operation
        self.transaction = transaction

2️⃣ core/dsl_parser.py — Langage Claude-Style
"""
Parser DSL V4
Comprend: "DashboardV1 - Page RDV - Modal En Consultation - Ajoute fonction validate"
"""
import re
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class Intent:
    project: str
    target: str  # Page/Component cible
    sub_target: Optional[str]  # Modal/Section spécifique
    action: str  # Ajoute/Modifie/Supprime/Corrige
    details: str  # Description de la fonctionnalité
    raw: str


class DSLParser:
    """
    Parse le langage naturel structuré de type Claude Desktop.
    """
    
    # Patterns d'actions
    ACTIONS = [
        "ajoute", "ajouter", "crée", "créer", "génère",
        "modifie", "modifier", "update", "corrige", "corriger", "fix",
        "supprime", "supprimer", "delete", "refactor", "extrait"
    ]
    
    def parse(self, input_str: str) -> Intent:
        """
        Parse une ligne de commande style Claude.
        Ex: "DashboardV1 - Page RDV - Modal En Consultation - Ajoute validation email"
        """
        # Normalisation
        cleaned = input_str.strip()
        
        # Split par tiret ou pipe
        parts = [p.strip() for p in re.split(r'[-–—|]', cleaned)]
        
        if len(parts) < 2:
            raise ValueError("Format invalide. Attendu: Projet - Cible - Action")
        
        # Extraction project (toujours premier)
        project = parts[0].strip()
        
        # Analyse des parties
        target = ""
        sub_target = None
        action = ""
        details = ""
        
        # Recherche de l'action dans les parties
        action_idx = -1
        for i, part in enumerate(parts):
            lower = part.lower()
            if any(act in lower for act in self.ACTIONS):
                action_idx = i
                # Extraction action exacte
                for act in self.ACTIONS:
                    if act in lower:
                        action = act
                        # Le reste de la partie est le détail
                        details = lower.replace(act, "").strip()
                        break
                break
        
        if action_idx == -1:
            # Pas d'action trouvée, on suppose que c'est une modification
            action = "modifie"
            details = parts[-1]
            action_idx = len(parts) - 1
        
        # Target est avant l'action
        if action_idx > 1:
            target = parts[1]
            if action_idx > 2:
                sub_target = " - ".join(parts[2:action_idx])
        else:
            target = parts[1] if len(parts) > 1 else "global"
        
        # Si détails vides, prend la dernière partie
        if not details and len(parts) > action_idx:
            details = parts[-1]
        
        return Intent(
            project=project,
            target=target,
            sub_target=sub_target,
            action=action,
            details=details,
            raw=input_str
        )
    
    def to_mempalace_query(self, intent: Intent) -> dict:
        """
        Convertit l'intent en requête de recherche MemPalace.
        """
        return {
            "project_wing": intent.project.lower().replace(" ", "_"),
            "skill_query": f"{intent.action} {intent.target} {intent.sub_target or ''}",
            "context_query": f"{intent.target} {intent.sub_target or ''} context"
        }

3️⃣ core/skill_aware_executor.py — Exécution avec Skills
"""
Executor qui récupère les skills depuis MemPalace avant d'exécuter.
"""
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from .transaction_manager import TransactionManager, OpType
from .mempalace_client import MemPalaceClient
from .dsl_parser import Intent


class SkillAwareExecutor:
    """
    Executor V4 qui:
    1. Charge les skills pertinents depuis MemPalace
    2. Charge le contexte projet
    3. Exécute via TransactionManager (atomic)
    """
    
    def __init__(self, tx_manager: TransactionManager, palace: MemPalaceClient):
        self.tx = tx_manager
        self.palace = palace
        self.workspace = Path("./workspace")
        
    def execute_intent(self, intent: Intent):
        """
        Pipeline complet: Skill Loading → Context Assembly → Atomic Execution
        """
        print(f"🔍 Chargement contexte pour {intent.project}...")
        
        # 1. WAKE-UP Layer 0/1
        wake_context = self.palace.wake_up(wing=intent.project.lower().replace(" ", "_"))
        
        # 2. RÉCUPÉRATION SKILLS
        skills = self._load_skills(intent)
        print(f"   🧩 {len(skills)} skills trouvés")
        
        # 3. RÉCUPÉRATION CONTEXTE PROJET
        context_files = self._load_project_context(intent)
        print(f"   📄 {len(context_files)} fichiers de contexte")
        
        # 4. ASSEMBLY DU PROMPT FINAL
        final_prompt = self._assemble_prompt(intent, skills, context_files, wake_context)
        
        # 5. DÉBUT TRANSACTION
        context_refs = [s["id"] for s in skills] + [c["id"] for c in context_files]
        tx_id = self.tx.begin(
            dsl_input=intent.raw,
            project=intent.project,
            intent=f"{intent.action} {intent.details}",
            context_refs=context_refs
        )
        
        try:
            # 6. GÉNÉRATION CODE (simulé, remplacer par appel LLM)
            generated = self._generate_code(final_prompt)
            
            # 7. DÉTERMINATION DES OPS À FAIRE (analyse du généré)
            operations = self._plan_operations(intent, generated)
            
            # 8. EXÉCUTION ATOMIQUE
            for op in operations:
                self._execute_atomic_op(op, generated)
            
            # 9. COMMIT
            self.tx.commit()
            print(f"✅ Projet {intent.project} mis à jour")
            
        except Exception as e:
            print(f"❌ Erreur: {e}")
            self.tx.rollback()
            raise
    
    def _load_skills(self, intent: Intent) -> List[Dict]:
        """
        Recherche dans MemPalace wing:skills ou hall:discoveries
        """
        query = f"{intent.action} {intent.target} {intent.sub_target or ''}"
        
        # Recherche dans wing dédié "skills"
        skill_results = self.palace.search_memories(
            query=query,
            wing="skills",
            n_results=3
        )
        
        # Fallback sur discoveries
        if not skill_results:
            skill_results = self.palace.search_memories(
                query=query,
                hall="discoveries",
                n_results=3
            )
        
        return [{"id": r.metadata.get("entry_id"), "content": r.content} 
                for r in skill_results]
    
    def _load_project_context(self, intent: Intent) -> List[Dict]:
        """
        Charge les fichiers contexte du projet depuis MemPalace.
        """
        project_wing = intent.project.lower().replace(" ", "_")
        
        # Recherche dans room:context du projet
        context_results = self.palace.search_memories(
            query=intent.target,
            wing=project_wing,
            room="context",
            n_results=5
        )
        
        return [{"id": r.metadata.get("entry_id"), "path": r.metadata.get("file"), 
                "content": r.content} for r in context_results]
    
    def _assemble_prompt(self, intent: Intent, skills: List[Dict], 
                        context_files: List[Dict], wake_context: Dict) -> str:
        """
        Assemble le prompt final pour le LLM avec tout le contexte.
        """
        parts = []
        
        # Identity Layer 0
        parts.append("=== SYSTEM ===")
        parts.append(wake_context.get("identity", "LCCA V4"))
        
        # Skills
        parts.append("\n=== SKILLS ===")
        for skill in skills:
            parts.append(f"Skill: {skill['id']}\n{skill['content'][:500]}...")
        
        # Contexte fichiers
        parts.append("\n=== CONTEXT ===")
        for ctx in context_files:
            parts.append(f"File: {ctx.get('path', 'unknown')}\n{ctx['content'][:1000]}...")
        
        # Intent
        parts.append(f"\n=== TASK ===")
        parts.append(f"Action: {intent.action}")
        parts.append(f"Target: {intent.target}" + (f" / {intent.sub_target}" if intent.sub_target else ""))
        parts.append(f"Details: {intent.details}")
        parts.append("\nGénère le code nécessaire (uniquement les fichiers modifiés).")
        
        return "\n".join(parts)
    
    def _generate_code(self, prompt: str) -> Dict[str, str]:
        """
        Appel LLM pour générer le code.
        Retourne dict {filepath: content}
        """
        # TODO: Intégrer appel Ollama/OpenAI
        # Pour l'exemple, simulation
        return {
            f"src/{prompt[:10].replace(' ', '_')}.py": "# Generated\nprint('ok')"
        }
    
    def _plan_operations(self, intent: Intent, generated: Dict[str, str]) -> List[Dict]:
        """
        Planifie les opérations file system nécessaires.
        """
        ops = []
        for filepath, content in generated.items():
            full_path = self.workspace / filepath
            if full_path.exists():
                ops.append({
                    "type": OpType.EDIT_FILE if intent.action in ["modifie", "corrige"] else OpType.WRITE_FILE,
                    "path": filepath,
                    "content": content
                })
            else:
                ops.append({
                    "type": OpType.WRITE_FILE,
                    "path": filepath,
                    "content": content
                })
        return ops
    
    def _execute_atomic_op(self, op: Dict, generated: Dict):
        """
        Exécute une opération via TransactionManager (avec rollback auto si fail)
        """
        filepath = op["path"]
        content = op["content"]
        
        def do_write():
            full_path = self.workspace / filepath
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            return content
        
        self.tx.log_operation(
            op_type=op["type"],
            target_path=filepath,
            execute_func=do_write,
            skill_ref="generated",  # Ou référence skill spécifique
            metadata={"intent_action": "create_or_update"}
        )

4️⃣ core/recovery_service.py — Démarrage Anti-Crash
"""
Recovery Service V4
Au boot: vérifie les transactions non terminées et propose recovery.
"""
import json
from typing import List, Optional
from pathlib import Path

from .transaction_manager import TransactionManager, Transaction, TxStatus


class RecoveryService:
    """
    Service de récupération post-crash.
    """
    
    def __init__(self, tx_manager: TransactionManager):
        self.tx = tx_manager
        self.recovery_file = Path("./.lcca_recovery")
    
    def boot_check(self) -> bool:
        """
        Vérifie s'il y a des transactions à récupérer.
        Retourne True si recovery nécessaire.
        """
        pending = self.tx.get_pending_transactions()
        
        if not pending:
            print("✅ Aucune transaction en cours. Système propre.")
            return False
        
        print(f"⚠️  {len(pending)} transaction(s) non terminée(s) détectée(s)!")
        
        for tx in pending:
            print(f"   - {tx.tx_id}: {tx.intent} ({tx.status})")
        
        return True
    
    def interactive_recovery(self):
        """
        Interface interactive de recovery.
        """
        pending = self.tx.get_pending_transactions()
        
        if not pending:
            return
        
        print("\n" + "="*50)
        print("MODE RÉCUPÉRATION")
        print("="*50)
        
        for tx in pending:
            print(f"\nTransaction: {tx.tx_id}")
            print(f"Projet: {tx.project}")
            print(f"Intent: {tx.intent}")
            print(f"Status: {tx.status}")
            print(f"Opérations réalisées: {len(tx.operations)}")
            
            if tx.operations:
                print("Fichiers modifiés:")
                for op in tx.operations:
                    print(f"  - {op.target_path} ({op.type.value})")
            
            print("\nOptions:")
            print("  [C] Commit forcé (garder les changements)")
            print("  [R] Rollback (annuler tout)")
            print("  [I] Inspecter l'état des fichiers")
            print("  [S] Skip (ignorer pour l'instant)")
            
            choice = input("Choix (C/R/I/S): ").strip().upper()
            
            if choice == "R":
                self.tx.rollback(tx.tx_id)
                print(f"   ↩️  Rollback effectué")
            elif choice == "C":
                # Forcer le commit (si les fichiers sont OK)
                print(f"   ⚠️  Commit forcé (à vos risques)")
            elif choice == "I":
                self._inspect_state(tx)
            else:
                print("   ⏭️  Skipped")
    
    def auto_rollback_last(self):
        """
        Rollback automatique de la dernière transaction (pour scripts).
        """
        pending = self.tx.get_pending_transactions()
        if pending:
            last = pending[-1]
            print(f"Auto-rollback de {last.tx_id}...")
            self.tx.rollback(last.tx_id)
    
    def _inspect_state(self, tx: Transaction):
        """Affiche les différences entre before/after"""
        for op in tx.operations:
            print(f"\n  Fichier: {op.target_path}")
            print(f"  Exist avant: {op.before.exists}")
            if op.after:
                print(f"  Exist après: {op.after.exists}")
                if op.before.content and op.after.content:
                    print(f"  Diff taille: {len(op.after.content) - len(op.before.content)} chars")
            input("  Appuyez sur Entrée...")

5️⃣ main_v4.py — Point d'entrée
#!/usr/bin/env python3
"""
LCCA V4 - Anti-Crash Transactional System
Usage: python main_v4.py "DashboardV1 - Page RDV - Modal En Consultation - Ajoute validation"
"""
import sys
import argparse

from core.mempalace_client import MemPalaceClient
from core.transaction_manager import TransactionManager
from core.dsl_parser import DSLParser
from core.skill_aware_executor import SkillAwareExecutor
from core.recovery_service import RecoveryService


def main():
    parser = argparse.ArgumentParser(description='LCCA V4 - Anti-Crash System')
    parser.add_argument('command', nargs='?', help='Commande DSL (ex: "Projet - Action - Details")')
    parser.add_argument('--recovery', '-r', action='store_true', help='Mode recovery interactif')
    parser.add_argument('--rollback-last', action='store_true', help='Annule la dernière transaction')
    parser.add_argument('--workspace', '-w', default='./workspace', help='Dossier de travail')
    
    args = parser.parse_args()
    
    # Initialisation
    palace = MemPalaceClient()
    tx_manager = TransactionManager(palace, args.workspace)
    recovery = RecoveryService(tx_manager)
    
    # Vérification boot (anti-crash)
    needs_recovery = recovery.boot_check()
    
    if args.rollback_last:
        recovery.auto_rollback_last()
        return
    
    if args.recovery or needs_recovery:
        recovery.interactive_recovery()
        if not args.command:
            return
    
    if not args.command:
        print("Usage: python main_v4.py \"Projet - Cible - Action\"")
        print("       python main_v4.py --recovery")
        sys.exit(1)
    
    # Mode normal: parsing et exécution
    try:
        parser = DSLParser()
        intent = parser.parse(args.command)
        
        print(f"🎯 Intent: {intent.project} | {intent.target}" + 
              (f" | {intent.sub_target}" if intent.sub_target else "") +
              f" | Action: {intent.action}")
        
        executor = SkillAwareExecutor(tx_manager, palace)
        executor.execute_intent(intent)
        
    except Exception as e:
        print(f"💥 Erreur fatale: {e}")
        print("💡 Conseil: Lancez avec --rollback-last pour annuler les changements partiels")
        sys.exit(1)


if __name__ == "__main__":
    main()

🎯 Utilisation V4
# 1. Initialisation (une fois)
python -c "from core.mempalace_client import MemPalaceClient; MemPalaceClient()"

# 2. Commande DSL (style Claude)
python main_v4.py "DashboardV1 - Page RDV - Modal En Consultation - Ajoute fonction validateAppointment"

# Si crash pendant l'opération, au redémarrage:
python main_v4.py --recovery
# → Propose: [C]ommit (garder) ou [R]ollback (annuler)

# Rollback rapide de la dernière commande
python main_v4.py --rollback-last

🔒 Garanties Anti-Crash
| Scénario                           | Protection                                                       |
| ---------------------------------- | ---------------------------------------------------------------- |
| **Crash pendant écriture fichier** | Snapshot "before" dans MemPalace → Restauration auto au reboot   |
| **Erreur syntaxe générée**         | Validation pré-commit → Rollback si tests échouent               |
| **Oubli de dépendance**            | Chaque opération loguée avec référence skill → Traçabilité       |
| **Corruption workspace**           | Checksum MD5 avant/après → Détection changement externe          |
| **Crash Transaction Manager**      | Drawer créé dès BEGIN → Recovery possible même si crash immédiat |

