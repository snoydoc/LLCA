============================================================
Fichier : 21-addendum-v7-spec-layer-adaptative.md
============================================================

# Addendum V7 — Spec Layer Adaptative (Cognition vs Orchestration)
&lt;!-- AI-READY | Architecture Spec Layer | Version 7.0.0-rc4 | 2026-04-18 --&gt;

## Vue d'ensemble

Cet addendum substitue la vision "pipeline/orchestration" (fichiers 18-19-20) par une architecture **cognitive adaptative**. La Spec Layer n'est pas une application externe ni un cockpit manuel. C'est une **capacité native de LCCA V7**, exposée via MCP, stockée en mémoire vectorielle, et activée conditionnellement par heuristique de complexité.

&gt; **Principe fondateur** :  
&gt; ❌ Orchestration = séquence rigide imposee par le système  
&gt; ✅ Cognition = le système décide adaptativement s'il a besoin d'une spec, la génère, la valide, l'apprend, puis l'utilise.

---

## 1. Architecture intégrée
GOOSE (cerveau principal, Ollama Qwen)
│
├── Si tâche simple → execute direct (pipeline V5 existant)
│
└── Si tâche complexe → active Spec Layer
│
├── memory_search("lcca_specs", query=intent) → spec existante ?
│       │
│       ├── Hit + valide → utiliser spec_from_memory
│       │
│       └── Miss / obsolète → generate_spec
│               │
│               ├── deep_reasoning (pattern o3-mini) → squelette archi
│               ├── spec_formatter (pattern Kimi) → structure .md
│               └── spec_validator (pattern Claude) → contradiction check
│               │
│               └── memory_store(collection="lcca_specs") → apprentissage
│
└── apply_edit_batch (pipeline V5 ACID) → sandbox_run → memory_store


---

## 2. Nouvelle collection mémoire : `lcca_specs`

### 2.1 Schéma

```python
@dataclass
class SpecEntry(MemoryEntry):
    # Hérite de MemoryEntry (wing, room, hall, layer)
    
    spec_id: str           # MD5 12-chars du contenu
    domain: str            # "transaction", "ast", "mcp", "sandbox", "global"
    version: str           # "7.0.0"
    complexity_score: int  # 0-100 (heuristique interne)
    
    # Contenu
    title: str
    body_md: str           # Texte complet de la spec
    abstract: str          # Résumé 500 caractères max (pour recherche sémantique)
    
    # Provenance
    generated_by: str      # "deep_reasoning" | "spec_formatter" | "hybrid"
    validated: bool        # True si spec_validator a approuvé
    validation_notes: str  # Liste des corrections apportées
    
    # Lifecycle
    superseded_by: Optional[str]  # spec_id de la version plus récente
    deprecated: bool       # True si obsolète

2.2 Stockage
| Collection ChromaDB | Fichiers JSON                                  | Indexation                                |
| ------------------- | ---------------------------------------------- | ----------------------------------------- |
| `lcca_specs`        | `palace/wings/lcca/rooms/specs/{spec_id}.json` | Embedding sur `abstract + domain + title` |

2.3 Règle de rétention
Une spec validée est conservée indéfiniment (Layer 3 deep)
Une spec non validée après 3 tentatives est stockée dans lcca_failures (apprentissage par échec)
Une spec deprecated=True est exclue de la recherche par défaut
3. Nouveaux outils MCP
3.1 generate_spec
Rôle : Générer une specification technique complète à partir d'un besoin flou.
Input JSON :
{
  "intent": "Ajouter un sandbox Docker avec fallback soft",
  "domain": "sandbox",
  "context": "Voir addendum 19 section 4",
  "format": "addendum_markdown",
  "max_length": "medium"
}

Output JSON :
{
  "spec_id": "a1b2c3d4e5f6",
  "title": "Specification Sandbox Engine V7",
  "abstract": "Sandbox hybride subprocess/Docker avec detection automatique...",
  "body_md": "# Spec ...",
  "complexity_score": 72,
  "generated_by": "hybrid",
  "confidence": 0.91
}

Implémentation interne :
def generate_spec(intent: str, domain: str, context: str) -> SpecEntry:
    # 1. Assembler le contexte (ContextAssembler V5)
    ctx = context_assembler.assemble(
        intent=intent,
        wing="lcca",
        room="spec_generation"
    )
    
    # 2. Deep reasoning (pattern o3-mini) : structure logique
    skeleton = deep_reasoning(prompt=f"Architecturer : {intent}", context=ctx)
    
    # 3. Spec formatter (pattern Kimi) : formattage MD strict
    body_md = spec_formatter(
        skeleton=skeleton,
        template="addendum_v7",
        constraints=load_template_constraints(domain)
    )
    
    # 4. Extraction métadonnées
    abstract = extract_abstract(body_md)
    complexity = compute_complexity(body_md)  # Nombre de sections, critères, contraintes
    
    spec = SpecEntry(
        spec_id=hashlib.md5(body_md.encode()).hexdigest()[:12],
        domain=domain,
        title=extract_title(body_md),
        abstract=abstract,
        body_md=body_md,
        complexity_score=complexity,
        generated_by="hybrid"
    )
    
    return spec

3.2 validate_spec
Rôle : Détecter les contradictions, incohérences et régressions par rapport aux règles invariantes V5.
Input JSON :
{
  "spec_id": "a1b2c3d4e5f6",
  "check_rules": ["all_v5_invariants", "acid_integrity", "mcp_compliance"],
  "compare_with": ["18-addendum-v7-reconcilie", "19-addendum-v7-complementaire"]
}

Output JSON :
{
  "valid": false,
  "score": 0.85,
  "violations": [
    {
      "rule": "SmartPatcher retourne str",
      "severity": "blocking",
      "location": "Section 6, paragraphe 3",
      "fix_suggestion": "Ajouter 'new_code = patcher.apply_patch(...)' avant write_text"
    }
  ],
  "validation_notes": "2 violations mineures, 0 bloquante après correction"
}

Implémentation interne :
def validate_spec(spec: SpecEntry, rules: List[str]) -> dict:
    violations = []
    
    # Pattern spec_validator (Claude) : vérification cohérence transversale
    for rule_name in rules:
        checker = RULE_REGISTRY.get(rule_name)
        if checker:
            result = checker.analyze(spec.body_md)
            violations.extend(result)
    
    # Vérification référentielle : les specs citées existent-elles ?
    referenced = extract_references(spec.body_md)  # "fichier 18", "addendum 19"
    for ref in referenced:
        if not spec_exists(ref):
            violations.append({
                "rule": "reference_integrity",
                "severity": "warning",
                "message": f"Spec référencée introuvable : {ref}"
            })
    
    # Score global
    blocking = sum(1 for v in violations if v["severity"] == "blocking")
    score = max(0, 1.0 - (blocking * 0.3) - (len(violations) * 0.05))
    
    return {
        "valid": blocking == 0 and score >= 0.8,
        "score": round(score, 2),
        "violations": violations,
        "validation_notes": format_notes(violations)
    }

4. Détection de complexité (heuristique adaptative)
Le système ne génère pas une spec pour chaque tâche. Il décide.
4.1 Algorithme should_generate_spec(intent)
def should_generate_spec(intent: Intent) -> Tuple[bool, int]:
    """
    Retourne (True, complexity_score) si une spec est nécessaire.
    """
    score = 0
    triggers = []
    
    # 1. Nombre de fichiers impliqués
    target_files = file_selector.select(intent)
    if len(target_files) >= 3:
        score += 30
        triggers.append("max_files_per_tx")
    
    # 2. Nouveau domaine architectural
    domain = infer_domain(intent)
    if not memory_engine.has_spec_for_domain(domain):
        score += 25
        triggers.append("new_domain")
    
    # 3. Mots-clés complexes
    complex_keywords = ["rollback", "sandbox", "mcp", "memory-first", 
                       "transaction", "acid", "async", "multi-agent"]
    if any(kw in intent.raw.lower() for kw in complex_keywords):
        score += 20
        triggers.append("complex_keywords")
    
    # 4. Historique d'échec
    past_failures = memory_engine.search(
        collection="lcca_failures",
        query=intent.details,
        n=3
    )
    if len(past_failures) > 0:
        score += 15
        triggers.append("past_failure_similar")
    
    # 5. Durée estimée (proxy : longueur details)
    if len(intent.details) > 100:
        score += 10
    
    threshold = 60
    return (score >= threshold, score)

4.2 Règle de décision
| Score  | Action                                                                             |
| ------ | ---------------------------------------------------------------------------------- |
| 0-40   | Pas de spec. Exécution directe pipeline V5.                                        |
| 41-59  | Optionnel. Demander confirmation (mode interactif) ou générer si `auto_spec=True`. |
| 60-100 | Obligatoire. `generate_spec` activé avant toute modification.                      |

5. Spécification des modèles-outils (patterns cognitifs)
Ces outils ne sont pas des appels API externes obligatoires. Ce sont des patterns de prompting appliqués au modèle local (Qwen via Ollama), avec fallback sur paste humain si configuré.
5.1 deep_reasoning (pattern o3-mini)
But : Raisonnement architectural avant rédaction.
System prompt :
Tu es un architecte logiciel senior. Avant d'écrire du code ou du Markdown :
1. Identifie les 3 options possibles
2. Pour chaque option, liste risques et bénéfices
3. Choisis la meilleure option et justifie
4. Définis les interfaces et contrats avant l'implémentation

Ne génère pas de code. Génère une analyse structurée en sections.

Input : Intent + contexte technique
Output : Squelette d'architecture (JSON ou bullet points)
5.2 spec_formatter (pattern Kimi)
But : Formattage strict respectant les conventions du projet.
System prompt :
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
- Référencer explicitement les addendum précédents (fichier 18, 19, 20...)

Input : Squelette + template de domaine
Output : body_md prêt pour validation
5.3 spec_validator (pattern Claude)
But : Détection de contradictions et cohérence transversale.
System prompt :
Tu es un reviewer technique obsessionnel. Ton rôle : trouver les contradictions.
Vérifie strictement :
- Les dataclasses ont-elles des champs cohérents avec l'usage décrit ?
- Les règles invariantes V5 sont-elles violées ?
- Les chemins de rollback sont-ils cohérents ?
- Y a-t-il des références circulaires ou des dépendances manquantes ?

Format de sortie : JSON strict avec liste de violations.
Input : body_md + liste des règles à vérifier
Output : Rapport de validation structuré
6. Intégration avec le pipeline V5/V7 existant
6.1 Modification de LCCAV5Fusion.execute()
# core/orchestrator.py — Modification du pipeline execute()

def execute(self, command: str, auto_rollback: bool = True, 
            adaptive_spec: bool = True) -> bool:
    
    # Phase 1 : Parsing (inchangé)
    intent = DSLParser().parse(command)
    
    # Phase 2 : Décision adaptative (NOUVEAU)
    if adaptive_spec:
        need_spec, complexity = should_generate_spec(intent)
        
        if need_spec:
            # Recherche spec existante
            existing = memory_engine.search(
                collection="lcca_specs",
                query=intent.raw,
                n=3
            )
            
            if existing and existing[0].validated and not existing[0].deprecated:
                spec = existing[0]
                log.info("Spec réutilisée depuis mémoire : %s", spec.spec_id)
            else:
                # Génération
                spec = generate_spec(
                    intent=intent.raw,
                    domain=infer_domain(intent),
                    context=assemble_context(intent)
                )
                
                # Validation
                val_result = validate_spec(spec, check_rules=["all_v5_invariants"])
                if not val_result["valid"]:
                    log.warning("Spec invalide, tentatives de correction...")
                    spec = auto_fix_spec(spec, val_result["violations"])
                    val_result = validate_spec(spec, check_rules=["all_v5_invariants"])
                
                spec.validated = val_result["valid"]
                spec.validation_notes = val_result["validation_notes"]
                memory_engine.store("lcca_specs", spec.to_dict())
                
                if not spec.validated:
                    log.error("Spec non validable — arrêt")
                    return False
    
    # Phase 3 : Exécution V5 standard (inchangée)
    # FileSelector → MultiFilePlanner → TransactionManager → SmartPatcher...
    return self._execute_core(intent, auto_rollback)

6.2 Nouveau paramètre config.py
# === Spec Layer Adaptive ===
ADAPTIVE_SPEC_ENABLED = True
SPEC_COMPLEXITY_THRESHOLD = 60
SPEC_AUTO_FIX_MAX_ITERATIONS = 3
SPEC_VALIDATOR_RULES = [
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
]

7. Mécanisme d'apprentissage (Spec Layer → Memory)
Cycle de vie d'une spec :

generate_spec()
    │
    ▼
validate_spec() ──[échec]──→ auto_fix() ──[3 échecs]──→ lcca_failures (apprentissage)
    │
    ├──[succès]──→ lcca_specs (layer 2 scoped)
    │
    └──[utilisation réussie dans TX]──→ promotion layer 1 compressed
                                              │
                                              └──[10 utilisations]──→ layer 0 identity

                                
Promotion automatique :
layer_2_scoped → layer_1_compressed : résumé automatique par le LLM (abstract enrichi)
layer_1_compressed → layer_0_identity : intégration dans le prompt système de LCCA ("Tu es un agent qui suit ces patterns...")

8. Tests requis
| Suite       | Fichier                     | Cas test                                                      |
| ----------- | --------------------------- | ------------------------------------------------------------- |
| Heuristique | `test_spec_complexity.py`   | `test_should_generate_spec_max_files` (3 fichiers → True)     |
| Heuristique | `test_spec_complexity.py`   | `test_should_not_generate_simple_rename` (score < 40 → False) |
| Génération  | `test_spec_layer.py`        | `test_generate_spec_creates_valid_markdown`                   |
| Validation  | `test_spec_layer.py`        | `test_validate_spec_detects_missing_snapshot_rule`            |
| Mémoire     | `test_spec_layer.py`        | `test_spec_stored_in_lcca_specs`                              |
| Intégration | `test_spec_orchestrator.py` | `test_adaptive_spec_blocks_invalid_spec`                      |
| Intégration | `test_spec_orchestrator.py` | `test_reuse_existing_validated_spec`                          |

9. Règles invariantes V7 — Spécifiques Spec Layer
| #  | Règle                                                          | Justification                                                                    |
| -- | -------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| 11 | **Une spec non validée ne génère jamais de code**              | Empêche la propagation d'erreurs architecturales                                 |
| 12 | **La complexité est toujours estimée avant décision**          | Évite l'overhead spec sur les tâches triviales                                   |
| 13 | **Les specs validées sont versionnées et tracées**             | `spec_id` + `superseded_by` garantissent l'historique                            |
| 14 | **Le fallback d'une spec invalide est l'arrêt, pas le bypass** | Sécurité : mieux vaut ne rien faire que mal faire                                |
| 15 | **Les patterns cognitifs sont prompts, pas hardcodés**         | `deep_reasoning`, `spec_formatter`, `spec_validator` sont configurables via YAML |

10. Checklist validation (avant merge)
[ ] should_generate_spec() respecte MAX_FILES_PER_TX (règle 3)
[ ] generate_spec() n'écrit jamais directement sur disque (règle 1)
[ ] validate_spec() vérifie les 10 règles V5 + 5 règles V7
[ ] lcca_specs utilise l'encodage utf-8-sig pour les fichiers JSON (règle 10)
[ ] Les modèles-outils utilisent sys.executable si subprocess (règle 8)
[ ] Les imports des classes mockables sont module-level (règle 9)
[ ] memory_store pour specs valide score >= 0.8 ou stocke dans lcca_failures
[ ] Les 237 tests V5 restent verts
[ ] spec_validator détecte les contradictions entre addendum 18-19-20-21
<!-- AI-READY | Addendum Spec Layer V7 | 2026-04-18 -->