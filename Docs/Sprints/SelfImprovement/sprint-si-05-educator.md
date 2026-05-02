# Sprint SI-05 — Educator SI
<!-- AI-READY | LCCA V10.5 | Sprint SI-05 | Priorité P2 | Effort 1j | Statut : 🔲 À FAIRE -->

## Objectif

Implémenter `EducatorSI` : analyse des auto-fix réussis et borgnes (V10) pour générer
des suggestions de patterns. Zéro modification automatique du système.

## Contexte

- Dépendance : SI-01 ✅, SI-04 🔲
- Source principale : `auto_fix_success.log` + `borgnes_map.json`
- Sortie : fichiers `.md` dans `SelfImprove/patterns/`

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `SelfImprove/engines/educator.py` | CREATE | ~180 lignes |
| 2 | `tests/test_si_05_educator.py` | CREATE | ~60 lignes |

## Spécification

### Classe `EducatorSI`

```python
class EducatorSI:
    def __init__(self, cfg: dict | None = None): ...

    def ingest(self, source: str, file_path: str | None = None) -> Path | None:
        """
        source: "auto-fix" | "borgnes" | "manual"
        Retourne chemin fichier suggestion créé, ou None si données insuffisantes.
        """
        if source == "auto-fix":
            return self._ingest_auto_fix()
        if source == "borgnes":
            return self._ingest_borgnes()
        if source == "manual" and file_path:
            return self._ingest_manual(Path(file_path))
        return None

    def _ingest_auto_fix(self) -> Path | None:
        # Lit auto_fix_success.log
        # Groupe par pattern_id → confiance selon count
        # Si count ≥ 1 → génère suggestion
        ...

    def _ingest_borgnes(self) -> Path | None:
        # Lit borgnes_map.json
        # Pour chaque borgne count ≥ 3 et severity=high → suggestion cognitive
        ...

    def _ingest_manual(self, source_file: Path) -> Path | None:
        # Analyse libre du fichier
        ...

    def _write_suggestion(self, pattern_id: str, source: str,
                           suggestion_type: str, content: dict) -> Path:
        # Écrit patterns/suggested_YYYY-MM-DD-NNN.md
        # Déduplication : hashlib.sha256(pattern_id + source)[:16]
        ...

    def _next_seq(self, patterns_dir: Path) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return len(list(patterns_dir.glob(f"suggested_{today}-*.md"))) + 1
```

### Format suggestion (template)

```markdown
# Suggestion — {pattern_id}
> Générée le : {date} | Source : {source} | Type : {type}

## Pattern détecté
- **Nom** : `{pattern_id}`
- **Source** : {source_detail}
- **Type** : opérationnel | cognitif (borgne V10)

## Correction appliquée (si opérationnel)
{diff_block}

## Description du borgne (si cognitif)
{borgne_description}

## Confiance
{confidence} ({count} occurrence(s))

## Validation humaine requise
- [ ] Ajouter dans `orchestrator_rules.json`
- [ ] Ajouter dans `auto_fix_whitelist.json` (si pertinent)
- [ ] Ajouter dans `prompts/rules.md` (si borgne cognitif)
```

## Critères d'acceptation

- [ ] `python lcca_si.py educator ingest --source auto-fix` crée `patterns/suggested_*.md`
- [ ] `python lcca_si.py educator ingest --source borgnes` crée une suggestion cognitive
- [ ] Déduplication : même pattern_id + source → pas de doublon
- [ ] Educator ne modifie jamais `orchestrator_rules.json` ni `auto_fix_whitelist.json`
- [ ] Données insuffisantes → retourne None sans crash

## Protocole d'exécution

```
1. filesystem:read_text_file SelfImprove/borgnes_map.json
2. filesystem:write_file SelfImprove/engines/educator.py
3. filesystem:write_file tests/test_si_05_educator.py
4. [relire les deux fichiers]
5. pytest tests/test_si_05_educator.py -v
6. pytest tests/ -x -q
```

## Mise à jour skills (fin de sprint)

- **001** : règle "EducatorSI — suggestions uniquement, jamais de modification system files"
- **002** : `SelfImprove/engines/educator.py` ajouté à l'arborescence
