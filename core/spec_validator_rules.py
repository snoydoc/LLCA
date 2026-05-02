# -*- coding: utf-8-sig -*-
"""
spec_validator_rules.py — RuleChecker ABC + 15 règles V7.2 + RULE_REGISTRY (Sprint REFACTO-01).

Extrait de spec_validator.py pour réduire sa taille de 19.7 KB à < 6 KB.

Rétrocompatibilité : RuleChecker et RULE_REGISTRY sont ré-exportés depuis spec_validator.py,
donc `from core.spec_validator import RULE_REGISTRY` continue de fonctionner.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


# ════════════════════════════════════════════════════════════════════════════
# RuleChecker ABC (V7.2)
# ════════════════════════════════════════════════════════════════════════════

class RuleChecker(ABC):
    """Interface commune des règles V7.2.

    Chaque règle analyse le corps Markdown brut (body_md) de la spec,
    pas ses champs Python.
    """

    rule_id: str
    description: str
    blocking: bool

    @abstractmethod
    def analyze(self, body_md: str) -> list[dict]:
        """Retourne une liste de violations (dicts) ou [] si RAS."""


# ── Règle 1 : SmartPatcher ne doit pas write_text directement ───────────────

class Rule1SmartPatcherStr(RuleChecker):
    rule_id = "rule_1_smartpatcher_str"
    description = "apply_patch() + write_text() directs → SmartPatcher retourne str uniquement"
    blocking = True

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "apply_patch" in lower and "write_text" in lower:
            return [{
                "rule": self.rule_id, "severity": "blocking",
                "location": "body_md",
                "fix_suggestion": "SmartPatcher.apply_patch() retourne str — ne jamais appeler write_text() en aval direct",
            }]
        return []


# ── Règle 2 : ast pour lecture, libcst pour modification ────────────────────

class Rule2AstReadLibcstWrite(RuleChecker):
    rule_id = "rule_2_ast_read_libcst_write"
    description = "ast.parse() utilisé pour modification → doit utiliser libcst"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "ast.parse" in lower and ("modifier" in lower or "patch" in lower or "edit" in lower):
            return [{
                "rule": self.rule_id, "severity": "warning",
                "location": "body_md",
                "fix_suggestion": "Utiliser libcst pour les modifications AST ; ast uniquement pour la lecture",
            }]
        return []


# ── Règle 3 : max 3 fichiers par TX ─────────────────────────────────────────

class Rule3MaxFiles(RuleChecker):
    rule_id = "rule_3_max_files"
    description = "Plus de 3 fichiers mentionnés dans une TX → viole MAX_FILES_PER_TX"
    blocking = True

    _PATTERNS = ("4 fichiers", "5 fichiers", "6 fichiers", "7 fichiers", "8 fichiers",
                 "9 fichiers", "4 files", "5 files",
                 "four files", "five files",)

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        for pat in self._PATTERNS:
            if pat in lower:
                return [{
                    "rule": self.rule_id, "severity": "blocking",
                    "location": "body_md",
                    "fix_suggestion": "Limiter chaque transaction à 3 fichiers maximum (config.MAX_FILES_PER_TX)",
                }]
        return []


# ── Règle 4 : FileSnapshot avec content_hash ────────────────────────────────

class Rule4SnapshotMd5(RuleChecker):
    rule_id = "rule_4_snapshot_md5"
    description = "FileSnapshot sans content_hash → intégrité non garantie"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "filesnapshot" in lower and "content_hash" not in lower:
            return [{
                "rule": self.rule_id, "severity": "warning",
                "location": "body_md",
                "fix_suggestion": "Ajouter content_hash (MD5) dans FileSnapshot pour vérifier l'intégrité avant rollback",
            }]
        return []


# ── Règle 5 : WAL append-only ────────────────────────────────────────────────

class Rule5WalAppendOnly(RuleChecker):
    rule_id = "rule_5_wal_append_only"
    description = "Modification du WAL en dehors du flux append → violation ACID"
    blocking = True

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "wal" in lower and ("modifier" in lower or "ecraser" in lower or "truncat" in lower or "delete" in lower):
            return [{
                "rule": self.rule_id, "severity": "blocking",
                "location": "body_md",
                "fix_suggestion": "Le WAL est append-only — ne jamais modifier ou tronquer les entrées existantes",
            }]
        return []


# ── Règle 6 : FallbackGenerator ne doit pas lever ────────────────────────────

class Rule6LlmFallback(RuleChecker):
    rule_id = "rule_6_llm_fallback"
    description = "FallbackGenerator + raise → le fallback doit toujours retourner"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "fallbackgenerator" in lower and "raise" in lower:
            return [{
                "rule": self.rule_id, "severity": "warning",
                "location": "body_md",
                "fix_suggestion": "FallbackGenerator doit retourner GenerationResult même en erreur — jamais lever",
            }]
        return []


# ── Règle 7 : Injection de dépendances ──────────────────────────────────────

class Rule7DependencyInjection(RuleChecker):
    rule_id = "rule_7_dependency_injection"
    description = "Instanciation dans des méthodes → préférer l'injection au __init__"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        keywords = ("= transactionmanager(", "= astindexer(", "= sandboxengine(",
                    "= llmgenerator(", "= memoryengine(")
        for kw in keywords:
            if kw in lower:
                return [{
                    "rule": self.rule_id, "severity": "warning",
                    "location": "body_md",
                    "fix_suggestion": "Instancier les dépendances dans __init__ ou via injection, pas dans les méthodes",
                }]
        return []


# ── Règle 8 : sys.executable obligatoire ────────────────────────────────────

class Rule8SysExecutable(RuleChecker):
    rule_id = "rule_8_sys_executable"
    description = "subprocess + 'python' hardcodé → utiliser sys.executable"
    blocking = True

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "subprocess" in lower and (
            '"python"' in body_md or "'python'" in body_md
            or "\"python\"" in body_md
        ):
            return [{
                "rule": self.rule_id, "severity": "blocking",
                "location": "body_md",
                "fix_suggestion": "Remplacer 'python' par sys.executable dans tout appel subprocess",
            }]
        return []


# ── Règle 9 : imports au niveau module ──────────────────────────────────────

class Rule9ModuleLevelImports(RuleChecker):
    rule_id = "rule_9_module_level_imports"
    description = "import dans corps de fonction → doit être au niveau module"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "import " in lower and ("def " in lower or "methode" in lower) and "corps" in lower:
            return [{
                "rule": self.rule_id, "severity": "warning",
                "location": "body_md",
                "fix_suggestion": "Placer les imports au niveau module sauf pour éviter les imports circulaires documentés",
            }]
        return []


# ── Règle 10 : JSON en utf-8 (sans BOM) ─────────────────────────────────────

class Rule10Utf8Sig(RuleChecker):
    rule_id = "rule_10_utf8_sig"
    description = "JSON avec utf-8-sig → les fichiers JSON doivent être utf-8 sans BOM"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "json" in lower and "utf-8-sig" in lower:
            return [{
                "rule": self.rule_id, "severity": "warning",
                "location": "body_md",
                "fix_suggestion": "Écrire les JSON en utf-8 (sans BOM) — utf-8-sig réservé aux fichiers .py Windows",
            }]
        return []


# ── Règle 11 : pas de code sans spec valide ──────────────────────────────────

class Rule11NoCodeIfInvalidSpec(RuleChecker):
    rule_id = "rule_11_no_code_if_invalid_spec"
    description = "Bypass spec invalide → Règle 11 fondamentale violée"
    blocking = True

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if ("spec" in lower and "invalide" in lower and "ignor" in lower) or \
           ("skip" in lower and "validation" in lower and "spec" in lower):
            return [{
                "rule": self.rule_id, "severity": "blocking",
                "location": "body_md",
                "fix_suggestion": "Jamais générer du code si la spec est invalide — Règle 11 est non négociable",
            }]
        return []


# ── Règle 12 : complexity_first ─────────────────────────────────────────────

class Rule12ComplexityFirst(RuleChecker):
    rule_id = "rule_12_complexity_first"
    description = "generate_spec() sans should_generate_spec() → vérifier la complexité d'abord"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "generate_spec" in lower and "should_generate_spec" not in lower and "complexit" not in lower:
            return [{
                "rule": self.rule_id, "severity": "warning",
                "location": "body_md",
                "fix_suggestion": "Appeler should_generate_spec() / SpecComplexityEstimator avant generate_spec()",
            }]
        return []


# ── Règle 13 : spec versionnée ───────────────────────────────────────────────

class Rule13SpecVersioned(RuleChecker):
    rule_id = "rule_13_spec_versioned"
    description = "SpecEntry sans superseded_by → traçabilité de version manquante"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "specentry" in lower and "superseded_by" not in lower and "version" not in lower:
            return [{
                "rule": self.rule_id, "severity": "warning",
                "location": "body_md",
                "fix_suggestion": "Inclure superseded_by pour tracer la chaîne de versions des specs",
            }]
        return []


# ── Règle 14 : spec invalide stoppe l'exécution ─────────────────────────────

class Rule14InvalidSpecStops(RuleChecker):
    rule_id = "rule_14_invalid_spec_stops"
    description = "Continuation malgré spec invalide → violation Règle 11"
    blocking = True

    def analyze(self, body_md: str) -> list[dict]:
        lower = body_md.lower()
        if "continuer" in lower and "spec" in lower and "invalide" in lower:
            return [{
                "rule": self.rule_id, "severity": "blocking",
                "location": "body_md",
                "fix_suggestion": "Interrompre le pipeline dès qu'une spec invalide est détectée",
            }]
        return []


# ── Règle 15 : patterns configurables ────────────────────────────────────────

class Rule15PatternsConfigurable(RuleChecker):
    rule_id = "rule_15_patterns_configurable"
    description = "CognitivePatterns configurables — contrôle sémantique uniquement"
    blocking = False

    def analyze(self, body_md: str) -> list[dict]:
        # Règle sémantique — pas de détection automatique sur body_md
        return []


# ── Registre V7.2 ─────────────────────────────────────────────────────────────

def _build_registry_v72() -> dict[str, RuleChecker]:
    rules: list[RuleChecker] = [
        Rule1SmartPatcherStr(),
        Rule2AstReadLibcstWrite(),
        Rule3MaxFiles(),
        Rule4SnapshotMd5(),
        Rule5WalAppendOnly(),
        Rule6LlmFallback(),
        Rule7DependencyInjection(),
        Rule8SysExecutable(),
        Rule9ModuleLevelImports(),
        Rule10Utf8Sig(),
        Rule11NoCodeIfInvalidSpec(),
        Rule12ComplexityFirst(),
        Rule13SpecVersioned(),
        Rule14InvalidSpecStops(),
        Rule15PatternsConfigurable(),
    ]
    return {r.rule_id: r for r in rules}


RULE_REGISTRY: dict[str, RuleChecker] = _build_registry_v72()
