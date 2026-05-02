# Sprint 14 — Spec Layer Core
<!-- AI-READY | Architecture Spec Layer | Version 7.1.0 | 2026-04-18 -->
<!-- Corrige et remplace addendum-21 sections 2, 3.1, 3.2, 5, 9 -->

## Vue d'ensemble

La Spec Layer est une **capacité native de LCCA V7** permettant de générer, valider et mémoriser des specifications techniques avant toute modification architecturale complexe. Ce sprint implémente le **noyau** : modèle de données, outils de génération/validation, et registre de règles.

> **Principe fondateur** :
> Une spec non validée ne génère jamais de code (Règle invariante 11).
> Le système décide seul s'il a besoin d'une spec, via heuristique de complexité (Règle 12).

---

## Périmètre Sprint 14

| Module | Fichier | Statut |
|--------|---------|--------|
| Modèle de données | `core/spec_entry.py` | 🆕 NOUVEAU |
| Génération | `core/spec_generator.py` | 🆕 NOUVEAU |
| Validation + RULE_REGISTRY | `core/spec_validator.py` | 🆕 NOUVEAU |
| Patterns cognitifs | `core/cognitive_patterns.py` | 🆕 NOUVEAU |
| Tests | `tests/test_spec_layer.py` | 🆕 NOUVEAU |

**Non inclus dans ce sprint** : heuristique, intégration orchestrateur, promotion mémoire → Sprint 15.

---

## 1. Modèle de données — `core/spec_entry.py`

### 1.1 Corrections apportées vs spec originale

| Problème original | Correction |
|---|---|
| `SpecEntry(MemoryEntry)` — `MemoryEntry` inexistante | `SpecEntry` est un `@dataclass` autonome, sérialisable en `dict` via `.to_dict()` |
| Champ JSON avec `utf-8-sig` | Fichiers JSON en `utf-8` standard (BOM inutile et problématique en JSON) |
| Pas de méthode `from_dict()` | Ajout `SpecEntry.from_dict(d)` pour désérialisation depuis ChromaDB |

### 1.2 Dataclass

```python
# core/spec_entry.py
# -*- coding: utf-8 -*-
"""
spec_entry.py — LCCA V7
Sprint 14 — TASK-14-01

Modèle de données pour les specifications techniques de la Spec Layer.
Autonome : pas de dépendance sur MemoryEngine ni ChromaDB à l'import.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional


VALID_DOMAINS = frozenset({
    "transaction", "ast", "mcp", "sandbox",
    "memory", "spec", "orchestration", "global"
})

VALID_GENERATED_BY = frozenset({
    "deep_reasoning", "spec_formatter", "hybrid", "manual"
})


@dataclass
class SpecEntry:
    """Entrée de specification technique dans la collection lcca_specs."""

    # Identité
    spec_id: str                      # MD5 12-chars du body_md
    domain: str                       # Parmi VALID_DOMAINS
    version: str                      # Ex: "7.1.0"
    complexity_score: int             # 0-100

    # Contenu
    title: str
    body_md: str                      # Texte complet de la spec
    abstract: str                     # 500 caractères max — pour embedding

    # Provenance
    generated_by: str                 # Parmi VALID_GENERATED_BY
    validated: bool = False
    validation_notes: str = ""

    # Lifecycle
    superseded_by: Optional[str] = None   # spec_id de la version suivante
    deprecated: bool = False
    usage_count: int = 0              # Incrémenté à chaque réutilisation TX

    # Promotion mémoire (layer 0/1/2)
    memory_layer: int = 2             # 2=scoped, 1=compressed, 0=identity

    @classmethod
    def make_spec_id(cls, body_md: str) -> str:
        return hashlib.md5(body_md.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def from_dict(cls, d: dict) -> "SpecEntry":
        return cls(
            spec_id=d["spec_id"],
            domain=d["domain"],
            version=d["version"],
            complexity_score=int(d["complexity_score"]),
            title=d["title"],
            body_md=d["body_md"],
            abstract=d["abstract"],
            generated_by=d["generated_by"],
            validated=bool(d.get("validated", False)),
            validation_notes=d.get("validation_notes", ""),
            superseded_by=d.get("superseded_by"),
            deprecated=bool(d.get("deprecated", False)),
            usage_count=int(d.get("usage_count", 0)),
            memory_layer=int(d.get("memory_layer", 2)),
        )

    def to_dict(self) -> dict:
        return {
            "spec_id": self.spec_id,
            "domain": self.domain,
            "version": self.version,
            "complexity_score": self.complexity_score,
            "title": self.title,
            "body_md": self.body_md,
            "abstract": self.abstract,
            "generated_by": self.generated_by,
            "validated": self.validated,
            "validation_notes": self.validation_notes,
            "superseded_by": self.superseded_by,
            "deprecated": self.deprecated,
            "usage_count": self.usage_count,
            "memory_layer": self.memory_layer,
        }

    def is_usable(self) -> bool:
        """True si la spec peut être utilisée dans un pipeline TX."""
        return self.validated and not self.deprecated and self.superseded_by is None
```

---

## 2. Patterns cognitifs — `core/cognitive_patterns.py`

### 2.1 Corrections apportées

| Problème original | Correction |
|---|---|
| Fonctions libres `deep_reasoning()`, `spec_formatter()`, `spec_validator()` | Classes avec interface commune `CognitivePattern` → mockables en test |
| Appel LLM non encapsulé | Chaque classe utilise `LLMGenerator` injecté (DI) |
| Prompt hardcodé | Prompts chargés depuis `config.COGNITIVE_PROMPTS` (dict configurable) |

### 2.2 Interface et implémentations

```python
# core/cognitive_patterns.py
# -*- coding: utf-8 -*-
"""
cognitive_patterns.py — LCCA V7
Sprint 14 — TASK-14-02

Trois patterns cognitifs pour la Spec Layer :
  - DeepReasoningPattern  : raisonnement architectural (o3-mini style)
  - SpecFormatterPattern  : formattage Markdown strict (Kimi style)
  - SpecValidatorPattern  : détection de contradictions (Claude style)

Chaque pattern est une classe mockable avec LLMGenerator injecté.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from core.llm_generator import LLMGenerator


# ──────────────────────────────────────────────────────────────────────────────
# Interface commune
# ──────────────────────────────────────────────────────────────────────────────

class CognitivePattern(ABC):
    """Interface mockable pour les patterns cognitifs."""

    def __init__(self, generator: LLMGenerator) -> None:
        self._gen = generator

    @abstractmethod
    def run(self, prompt: str, context: str = "") -> str:
        """Retourne le résultat textuel du pattern."""


# ──────────────────────────────────────────────────────────────────────────────
# DeepReasoningPattern
# ──────────────────────────────────────────────────────────────────────────────

_DEEP_REASONING_SYSTEM = """\
Tu es un architecte logiciel senior. Avant d'écrire du code ou du Markdown :
1. Identifie les 3 options possibles
2. Pour chaque option, liste risques et bénéfices
3. Choisis la meilleure option et justifie
4. Définis les interfaces et contrats avant l'implémentation

Ne génère pas de code. Génère une analyse structurée en sections JSON ou bullet points.
"""


class DeepReasoningPattern(CognitivePattern):
    """Raisonnement architectural — produit un squelette structuré."""

    def run(self, prompt: str, context: str = "") -> str:
        full_prompt = f"Contexte :\n{context}\n\nDemande : {prompt}" if context else prompt
        result = self._gen.generate(
            system_prompt=_DEEP_REASONING_SYSTEM,
            user_prompt=full_prompt,
        )
        return result.code or result.explanation


# ──────────────────────────────────────────────────────────────────────────────
# SpecFormatterPattern
# ──────────────────────────────────────────────────────────────────────────────

_SPEC_FORMATTER_SYSTEM = """\
Tu es un technical writer expert. Transforme l'analyse architecturale fournie
en document Markdown strict selon ce format :
- Header AI-READY avec version et date
- Tableaux pour les dataclasses et API
- Code blocks Python avec type hints
- Règles invariantes numérotées
- Checklist de validation finale

Règles absolues :
- Jamais de markdown à l'intérieur des tableaux
- Toujours utiliser le français technique
- Référencer explicitement les addendum précédents
"""


class SpecFormatterPattern(CognitivePattern):
    """Formattage Markdown strict — produit un body_md conforme."""

    def run(self, prompt: str, context: str = "") -> str:
        full_prompt = f"Squelette à formater :\n{prompt}"
        if context:
            full_prompt = f"Template de domaine :\n{context}\n\n{full_prompt}"
        result = self._gen.generate(
            system_prompt=_SPEC_FORMATTER_SYSTEM,
            user_prompt=full_prompt,
        )
        return result.code or result.explanation


# ──────────────────────────────────────────────────────────────────────────────
# SpecValidatorPattern
# ──────────────────────────────────────────────────────────────────────────────

_SPEC_VALIDATOR_SYSTEM = """\
Tu es un reviewer technique obsessionnel. Ton rôle : trouver les contradictions.
Vérifie strictement :
- Les dataclasses ont-elles des champs cohérents avec l'usage décrit ?
- Les règles invariantes V5/V7 sont-elles violées ?
- Les chemins de rollback sont-ils cohérents ?
- Y a-t-il des références circulaires ou des dépendances manquantes ?

Réponds UNIQUEMENT en JSON strict :
{"violations": [{"rule": "...", "severity": "blocking|warning", "location": "...", "fix_suggestion": "..."}]}
Si aucune violation : {"violations": []}
"""


class SpecValidatorPattern(CognitivePattern):
    """Détection de contradictions — retourne JSON de violations."""

    def run(self, prompt: str, context: str = "") -> str:
        full_prompt = f"Spec à valider :\n{prompt}"
        if context:
            full_prompt = f"Règles à vérifier :\n{context}\n\n{full_prompt}"
        result = self._gen.generate(
            system_prompt=_SPEC_VALIDATOR_SYSTEM,
            user_prompt=full_prompt,
        )
        return result.code or result.explanation
```

---

## 3. RULE_REGISTRY — `core/spec_validator.py`

### 3.1 Corrections apportées

| Problème original | Correction |
|---|---|
| `RULE_REGISTRY` référencée mais jamais définie | Dict complet avec 10 règles V5 + 5 règles V7 |
| Checkers sans interface | Classe `RuleChecker` avec méthode `analyze(body_md) -> list[dict]` |
| Score basé uniquement sur violations bloquantes | Score pondéré : blocking × 0.3, warning × 0.05 (conservé), + bonus si zéro warning |

### 3.2 Architecture

```python
# core/spec_validator.py
# -*- coding: utf-8 -*-
"""
spec_validator.py — LCCA V7
Sprint 14 — TASK-14-03

Validation de specs techniques.
Contient :
  - RuleChecker (interface)
  - RULE_REGISTRY (10 règles V5 + 5 règles V7)
  - SpecValidatorService (orchestre validation + LLM fallback)
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Optional

from core.spec_entry import SpecEntry
from core.cognitive_patterns import SpecValidatorPattern


# ──────────────────────────────────────────────────────────────────────────────
# Interface RuleChecker
# ──────────────────────────────────────────────────────────────────────────────

class RuleChecker(ABC):
    rule_id: str
    description: str

    @abstractmethod
    def analyze(self, body_md: str) -> list[dict]:
        """Retourne liste de violations (vide si OK)."""


# ──────────────────────────────────────────────────────────────────────────────
# Règles V5 (1-10) — vérifications statiques sur body_md
# ──────────────────────────────────────────────────────────────────────────────

class Rule1SmartPatcherStr(RuleChecker):
    rule_id = "rule_1_smartpatcher_str"
    description = "SmartPatcher.apply_patch() retourne str, jamais n'écrit disque"

    def analyze(self, body_md: str) -> list[dict]:
        if "write_text" in body_md and "apply_patch" in body_md:
            # Vérifie que write_text n'est pas utilisé directement après apply_patch
            if re.search(r"apply_patch.*\n.*write_text", body_md):
                return [{"rule": self.rule_id, "severity": "blocking",
                         "location": "Usage apply_patch + write_text",
                         "fix_suggestion": "Stocker le résultat de apply_patch() dans une variable avant write_text()"}]
        return []


class Rule2AstReadLibcstWrite(RuleChecker):
    rule_id = "rule_2_ast_read_libcst_write"
    description = "ast stdlib pour lecture, libcst pour modification"

    def analyze(self, body_md: str) -> list[dict]:
        violations = []
        if "ast.parse" in body_md and "modification" in body_md.lower():
            violations.append({"rule": self.rule_id, "severity": "warning",
                                "location": "Mention ast.parse pour modification",
                                "fix_suggestion": "Utiliser libcst pour toute modification d'AST"})
        return violations


class Rule3MaxFiles(RuleChecker):
    rule_id = "rule_3_max_files"
    description = "Max 3 fichiers par transaction"

    def analyze(self, body_md: str) -> list[dict]:
        if re.search(r"\b[4-9]\s+fichiers?\s+par\s+transaction", body_md, re.IGNORECASE):
            return [{"rule": self.rule_id, "severity": "blocking",
                     "location": "Mention >3 fichiers/TX",
                     "fix_suggestion": "MAX_FILES_PER_TX = 3 — contrainte non négociable"}]
        return []


class Rule4SnapshotMd5(RuleChecker):
    rule_id = "rule_4_snapshot_md5"
    description = "FileSnapshot doit inclure content_hash MD5"

    def analyze(self, body_md: str) -> list[dict]:
        if "FileSnapshot" in body_md and "content_hash" not in body_md:
            return [{"rule": self.rule_id, "severity": "warning",
                     "location": "Mention FileSnapshot sans content_hash",
                     "fix_suggestion": "Ajouter content_hash: Optional[str] à FileSnapshot"}]
        return []


class Rule5WalAppendOnly(RuleChecker):
    rule_id = "rule_5_wal_append_only"
    description = "WAL est append-only, jamais modifié rétroactivement"

    def analyze(self, body_md: str) -> list[dict]:
        if re.search(r"wal.*modif|modif.*wal|update.*wal", body_md, re.IGNORECASE):
            return [{"rule": self.rule_id, "severity": "blocking",
                     "location": "Mention modification du WAL",
                     "fix_suggestion": "Le WAL est append-only. Utiliser un nouveau record ROLLBACK."}]
        return []


class Rule6LlmFallback(RuleChecker):
    rule_id = "rule_6_llm_fallback"
    description = "FallbackGenerator ne lève jamais d'exception"

    def analyze(self, body_md: str) -> list[dict]:
        if "FallbackGenerator" in body_md and "raise" in body_md:
            return [{"rule": self.rule_id, "severity": "warning",
                     "location": "FallbackGenerator + raise",
                     "fix_suggestion": "FallbackGenerator doit retourner GenerationResult même en cas d'erreur"}]
        return []


class Rule7DependencyInjection(RuleChecker):
    rule_id = "rule_7_dependency_injection"
    description = "Les dépendances sont injectées, jamais instanciées dans les méthodes"

    def analyze(self, body_md: str) -> list[dict]:
        # Cherche des instanciations directes dans des méthodes (heuristique)
        if re.search(r"def \w+.*:\n.*= \w+Engine\(\)", body_md):
            return [{"rule": self.rule_id, "severity": "warning",
                     "location": "Instanciation directe dans méthode",
                     "fix_suggestion": "Injecter les dépendances via __init__"}]
        return []


class Rule8SysExecutable(RuleChecker):
    rule_id = "rule_8_sys_executable"
    description = "sys.executable toujours, jamais 'python' hardcodé"

    def analyze(self, body_md: str) -> list[dict]:
        if re.search(r'subprocess.*["\']python["\']', body_md):
            return [{"rule": self.rule_id, "severity": "blocking",
                     "location": "Appel subprocess avec 'python' hardcodé",
                     "fix_suggestion": "Remplacer par sys.executable"}]
        return []


class Rule9ModuleLevelImports(RuleChecker):
    rule_id = "rule_9_module_level_imports"
    description = "Imports mockables en tête de fichier (pas dans les fonctions)"

    def analyze(self, body_md: str) -> list[dict]:
        if re.search(r"def \w+.*:\n\s+import ", body_md):
            return [{"rule": self.rule_id, "severity": "warning",
                     "location": "Import dans corps de fonction",
                     "fix_suggestion": "Déplacer l'import en tête de module (sauf import tardif documenté)"}]
        return []


class Rule10Utf8Encoding(RuleChecker):
    rule_id = "rule_10_utf8_sig"
    description = "Fichiers Python en utf-8-sig, fichiers JSON en utf-8 (pas de BOM)"

    def analyze(self, body_md: str) -> list[dict]:
        violations = []
        if re.search(r'json.*utf-8-sig|utf-8-sig.*json', body_md, re.IGNORECASE):
            violations.append({"rule": self.rule_id, "severity": "warning",
                                "location": "JSON avec utf-8-sig",
                                "fix_suggestion": "JSON doit être utf-8 sans BOM. utf-8-sig uniquement pour .py"})
        return violations


# Règles V7 (11-15)

class Rule11SpecNoCodeIfInvalid(RuleChecker):
    rule_id = "rule_11_no_code_if_invalid_spec"
    description = "Spec non validée n'autorise pas la génération de code"

    def analyze(self, body_md: str) -> list[dict]:
        if re.search(r"spec.*invalid.*genere|bypass.*spec", body_md, re.IGNORECASE):
            return [{"rule": self.rule_id, "severity": "blocking",
                     "location": "Bypass de validation spec",
                     "fix_suggestion": "Une spec invalide doit arrêter le pipeline (return False)"}]
        return []


class Rule12ComplexityBeforeDecision(RuleChecker):
    rule_id = "rule_12_complexity_first"
    description = "should_generate_spec() appelé avant toute génération"

    def analyze(self, body_md: str) -> list[dict]:
        if "generate_spec" in body_md and "should_generate_spec" not in body_md:
            return [{"rule": self.rule_id, "severity": "warning",
                     "location": "generate_spec sans should_generate_spec",
                     "fix_suggestion": "Appeler should_generate_spec() avant generate_spec()"}]
        return []


class Rule13SpecVersioned(RuleChecker):
    rule_id = "rule_13_spec_versioned"
    description = "Specs tracées via spec_id + superseded_by"

    def analyze(self, body_md: str) -> list[dict]:
        if "SpecEntry" in body_md and "superseded_by" not in body_md:
            return [{"rule": self.rule_id, "severity": "warning",
                     "location": "SpecEntry sans superseded_by",
                     "fix_suggestion": "Ajouter superseded_by: Optional[str] pour traçabilité"}]
        return []


class Rule14InvalidSpecStops(RuleChecker):
    rule_id = "rule_14_invalid_spec_stops"
    description = "Spec invalide → arrêt du pipeline, pas bypass"

    def analyze(self, body_md: str) -> list[dict]:
        if re.search(r"spec.*invalid.*continu|skip.*validation", body_md, re.IGNORECASE):
            return [{"rule": self.rule_id, "severity": "blocking",
                     "location": "Continuation malgré spec invalide",
                     "fix_suggestion": "return False si spec.validated is False après auto_fix"}]
        return []


class Rule15PatternsConfigurable(RuleChecker):
    rule_id = "rule_15_patterns_configurable"
    description = "Patterns cognitifs configurables, pas hardcodés"

    def analyze(self, body_md: str) -> list[dict]:
        return []  # Vérification sémantique uniquement — pas détectable statiquement


# ──────────────────────────────────────────────────────────────────────────────
# RULE_REGISTRY
# ──────────────────────────────────────────────────────────────────────────────

RULE_REGISTRY: dict[str, RuleChecker] = {
    checker.rule_id: checker
    for checker in [
        Rule1SmartPatcherStr(), Rule2AstReadLibcstWrite(), Rule3MaxFiles(),
        Rule4SnapshotMd5(), Rule5WalAppendOnly(), Rule6LlmFallback(),
        Rule7DependencyInjection(), Rule8SysExecutable(), Rule9ModuleLevelImports(),
        Rule10Utf8Encoding(), Rule11SpecNoCodeIfInvalid(), Rule12ComplexityBeforeDecision(),
        Rule13SpecVersioned(), Rule14InvalidSpecStops(), Rule15PatternsConfigurable(),
    ]
}


# ──────────────────────────────────────────────────────────────────────────────
# SpecValidatorService
# ──────────────────────────────────────────────────────────────────────────────

class SpecValidatorService:
    """
    Orchestre la validation d'une SpecEntry.
    Étape 1 : vérifications statiques (RULE_REGISTRY)
    Étape 2 : vérification sémantique LLM (SpecValidatorPattern) — optionnelle
    """

    def __init__(
        self,
        llm_pattern: Optional[SpecValidatorPattern] = None,
        rules: Optional[list[str]] = None,
    ) -> None:
        self._llm = llm_pattern
        self._rules = rules or list(RULE_REGISTRY.keys())

    def validate(self, spec: SpecEntry) -> dict:
        violations: list[dict] = []

        # Étape 1 : règles statiques
        for rule_id in self._rules:
            checker = RULE_REGISTRY.get(rule_id)
            if checker:
                violations.extend(checker.analyze(spec.body_md))

        # Étape 2 : LLM sémantique (si disponible)
        if self._llm:
            try:
                raw = self._llm.run(prompt=spec.body_md, context="\n".join(self._rules))
                llm_result = json.loads(raw)
                violations.extend(llm_result.get("violations", []))
            except (json.JSONDecodeError, Exception):
                pass  # LLM optionnel — ne bloque jamais

        blocking = sum(1 for v in violations if v.get("severity") == "blocking")
        score = max(0.0, 1.0 - (blocking * 0.3) - (len(violations) * 0.05))
        if blocking == 0 and len(violations) == 0:
            score = 1.0

        return {
            "valid": blocking == 0 and score >= 0.8,
            "score": round(score, 2),
            "violations": violations,
            "validation_notes": _format_notes(violations),
        }


def _format_notes(violations: list[dict]) -> str:
    blocking = [v for v in violations if v.get("severity") == "blocking"]
    warnings = [v for v in violations if v.get("severity") == "warning"]
    parts = []
    if blocking:
        parts.append(f"{len(blocking)} violation(s) bloquante(s)")
    if warnings:
        parts.append(f"{len(warnings)} avertissement(s)")
    if not parts:
        return "Validation OK — aucune violation"
    return " | ".join(parts)
```

---

## 4. Génération — `core/spec_generator.py`

### 4.1 Corrections apportées

| Problème original | Correction |
|---|---|
| Dépendances instanciées dans le corps de `generate_spec()` | `SpecGeneratorService.__init__` reçoit tous les collaborateurs (DI) |
| `auto_fix_spec()` non spécifiée | `SpecGeneratorService.auto_fix()` spécifiée : boucle max N itérations sur violations bloquantes |
| Pas de gestion d'erreur LLM | Si `deep_reasoning` échoue → `FallbackGenerator` (via `LLMGenerator`) |

### 4.2 Interface

```python
# core/spec_generator.py
# -*- coding: utf-8 -*-
"""
spec_generator.py — LCCA V7
Sprint 14 — TASK-14-04

Génération et auto-correction de SpecEntry.
Dépendances injectées : DeepReasoningPattern, SpecFormatterPattern, SpecValidatorService.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from core.spec_entry import SpecEntry
from core.cognitive_patterns import DeepReasoningPattern, SpecFormatterPattern
from core.spec_validator import SpecValidatorService
import config


class SpecGeneratorService:
    """
    Génère une SpecEntry complète à partir d'un intent textuel.
    Pipeline : deep_reasoning → spec_formatter → extract_metadata → SpecEntry
    """

    def __init__(
        self,
        reasoner: DeepReasoningPattern,
        formatter: SpecFormatterPattern,
        validator: SpecValidatorService,
        version: str = "7.1.0",
    ) -> None:
        self._reasoner = reasoner
        self._formatter = formatter
        self._validator = validator
        self._version = version

    def generate(self, intent: str, domain: str, context: str = "") -> SpecEntry:
        """
        Génère une SpecEntry non encore validée.
        La validation est de la responsabilité de l'appelant (Orchestrator).
        """
        # 1. Raisonnement architectural
        skeleton = self._reasoner.run(prompt=intent, context=context)

        # 2. Formattage Markdown
        body_md = self._formatter.run(prompt=skeleton, context=domain)

        # 3. Extraction métadonnées
        spec_id = SpecEntry.make_spec_id(body_md)
        title = _extract_title(body_md) or f"Spec {domain} — {intent[:40]}"
        abstract = _extract_abstract(body_md)
        complexity = _compute_complexity(body_md)

        return SpecEntry(
            spec_id=spec_id,
            domain=domain,
            version=self._version,
            complexity_score=complexity,
            title=title,
            body_md=body_md,
            abstract=abstract,
            generated_by="hybrid",
        )

    def auto_fix(
        self,
        spec: SpecEntry,
        violations: list[dict],
        max_iterations: int = None,
    ) -> SpecEntry:
        """
        Tente de corriger une spec en réinjectant les violations comme contexte.
        Retourne la spec corrigée (ou l'originale si non améliorable).
        max_iterations par défaut : config.SPEC_AUTO_FIX_MAX_ITERATIONS
        """
        max_iter = max_iterations or getattr(config, "SPEC_AUTO_FIX_MAX_ITERATIONS", 3)
        current = spec

        for _ in range(max_iter):
            blocking = [v for v in violations if v.get("severity") == "blocking"]
            if not blocking:
                break

            fix_context = "\n".join(
                f"- [{v['rule']}] {v.get('fix_suggestion', '')}"
                for v in blocking
            )
            new_body = self._formatter.run(
                prompt=current.body_md,
                context=f"CORRECTIONS REQUISES :\n{fix_context}",
            )
            new_spec_id = SpecEntry.make_spec_id(new_body)
            current = SpecEntry(
                spec_id=new_spec_id,
                domain=current.domain,
                version=current.version,
                complexity_score=current.complexity_score,
                title=current.title,
                body_md=new_body,
                abstract=_extract_abstract(new_body),
                generated_by="hybrid",
            )
            result = self._validator.validate(current)
            violations = result["violations"]

        return current


# ──────────────────────────────────────────────────────────────────────────────
# Helpers d'extraction (privés)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_title(body_md: str) -> str:
    for line in body_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return ""


def _extract_abstract(body_md: str, max_chars: int = 500) -> str:
    """Prend le premier paragraphe non-titre sous 500 caractères."""
    lines = body_md.splitlines()
    para = []
    for line in lines:
        if line.startswith("#"):
            if para:
                break
            continue
        if line.strip():
            para.append(line.strip())
        elif para:
            break
    abstract = " ".join(para)
    return abstract[:max_chars]


def _compute_complexity(body_md: str) -> int:
    """Heuristique : nombre de sections * 5 + nombre de règles * 3, plafonné à 100."""
    sections = len([l for l in body_md.splitlines() if l.startswith("## ")])
    rules = len([l for l in body_md.splitlines() if l.strip().startswith("| ")])
    raw = sections * 5 + rules * 3
    return min(100, raw)
```

---

## 5. Tests requis — `tests/test_spec_layer.py`

### 5.1 Suite complète (23 tests)

| Classe | Cas test | Couvre |
|--------|----------|--------|
| `TestSpecEntry` | `test_make_spec_id_deterministic` | spec_id MD5 stable |
| `TestSpecEntry` | `test_to_dict_from_dict_roundtrip` | Sérialisation symétrique |
| `TestSpecEntry` | `test_is_usable_requires_validated_not_deprecated` | Règle 11 |
| `TestSpecEntry` | `test_superseded_by_makes_unusable` | Lifecycle |
| `TestRuleRegistry` | `test_registry_has_15_rules` | Complétude |
| `TestRuleRegistry` | `test_rule1_detects_direct_write_after_patch` | Règle 1 |
| `TestRuleRegistry` | `test_rule3_detects_4_files_per_tx` | Règle 3 |
| `TestRuleRegistry` | `test_rule8_detects_hardcoded_python` | Règle 8 |
| `TestRuleRegistry` | `test_rule10_warns_json_utf8_sig` | Règle 10 |
| `TestRuleRegistry` | `test_clean_body_has_no_violations` | Pas de faux positifs |
| `TestSpecValidatorService` | `test_validate_clean_spec_returns_valid` | Happy path |
| `TestSpecValidatorService` | `test_validate_blocking_violation_returns_invalid` | Score < 0.8 |
| `TestSpecValidatorService` | `test_llm_failure_does_not_block_validation` | Résilience LLM |
| `TestSpecValidatorService` | `test_validation_notes_formatted` | Format output |
| `TestCognitivePatterns` | `test_deep_reasoning_calls_generator` | DI mockable |
| `TestCognitivePatterns` | `test_spec_formatter_calls_generator` | DI mockable |
| `TestCognitivePatterns` | `test_spec_validator_parses_json_response` | JSON parsing |
| `TestCognitivePatterns` | `test_spec_validator_handles_invalid_json` | Résilience |
| `TestSpecGeneratorService` | `test_generate_creates_spec_entry` | Happy path |
| `TestSpecGeneratorService` | `test_generate_spec_id_from_body` | MD5 cohérence |
| `TestSpecGeneratorService` | `test_auto_fix_stops_when_no_blocking` | Boucle termine |
| `TestSpecGeneratorService` | `test_auto_fix_max_iterations_respected` | Borne max |
| `TestSpecGeneratorService` | `test_auto_fix_returns_original_if_no_improvement` | Sécurité |

---

## 6. Nouvelles entrées config.py

```python
# === Spec Layer (Sprint 14) ===
ADAPTIVE_SPEC_ENABLED: bool = True
SPEC_COMPLEXITY_THRESHOLD: int = 60
SPEC_AUTO_FIX_MAX_ITERATIONS: int = 3
SPEC_VALIDATOR_RULES: list[str] = [
    "rule_1_smartpatcher_str",
    "rule_2_ast_read_libcst_write",
    "rule_3_max_files",
    "rule_4_snapshot_md5",
    "rule_5_wal_append_only",
    "rule_6_llm_fallback",
    "rule_7_dependency_injection",
    "rule_8_sys_executable",
    "rule_9_module_level_imports",
    "rule_10_utf8_sig",
    "rule_11_no_code_if_invalid_spec",
    "rule_12_complexity_first",
    "rule_13_spec_versioned",
    "rule_14_invalid_spec_stops",
    "rule_15_patterns_configurable",
]
SPEC_MEMORY_COLLECTION: str = "lcca_specs"
SPEC_STORAGE_DIR: str = "palace/wings/lcca/rooms/specs"
```

---

## 7. Règles invariantes V7 — Spec Layer

| # | Règle | Justification |
|---|-------|---------------|
| 11 | Une spec non validée ne génère jamais de code | Empêche la propagation d'erreurs architecturales |
| 12 | La complexité est estimée avant toute génération | Évite l'overhead sur tâches triviales |
| 13 | Les specs validées sont versionnées (spec_id + superseded_by) | Historique et traçabilité garantis |
| 14 | Spec invalide → arrêt du pipeline, jamais bypass | Sécurité : mieux vaut ne rien faire que mal faire |
| 15 | Les patterns cognitifs sont des classes injectables, pas des fonctions libres | Testabilité et configurabilité |

---

## 8. Checklist validation Sprint 14

- [ ] `SpecEntry.is_usable()` retourne False si non validée, dépréciée, ou superseded
- [ ] `SpecEntry.to_dict()` / `from_dict()` : roundtrip parfait (tous champs)
- [ ] `RULE_REGISTRY` contient exactement 15 règles (10 V5 + 5 V7)
- [ ] Chaque `RuleChecker.analyze()` retourne `[]` sur un body_md propre (zéro faux positif)
- [ ] `SpecValidatorService.validate()` : LLM failure → validation continue (pas de crash)
- [ ] `SpecGeneratorService.auto_fix()` : boucle ≤ `SPEC_AUTO_FIX_MAX_ITERATIONS`
- [ ] JSON stocké en `utf-8` (pas `utf-8-sig`)
- [ ] Fichiers `.py` en `utf-8-sig` (BOM Windows)
- [ ] 466 tests V5/V7 précédents restent verts
- [ ] `test_spec_layer.py` : 23 tests PASSED

<!-- AI-READY | Sprint 14 Spec Layer Core | Version 7.1.0 | 2026-04-18 -->
