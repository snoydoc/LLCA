# -*- coding: utf-8-sig -*-
"""
project_contributor.py - LCCA V10 / Mode Projets
Sprint PROJ-11 - Pipeline de contribution globale des skills projets

Scanne les skills locales d'un projet, detecte les patterns generalisables,
et les promeut dans la base globale MemPalace (project_global_skills).

Pipeline :
  1. Scan     : lit projects/{slug}/skills/*.md (EducatorAgent local)
  2. Dedup    : Jaccard lexical via ObserverAgent._is_duplicate() (seuil 0.85)
  3. Guard    : bloque si {PROJECT_ROOT} present dans le corps (skill confidentiel)
  4. Quality  : quality_score >= seuil requis (defaut : config.AGENT_MIN_QUALITY_SCORE)
  5. Index    : mine_content() vers collection project_global_skills (MemPalace)
  6. Stats    : stats.skills_generated++ dans project.json

Invariants :
  - contribute() ne leve jamais (mode degrade silencieux)
  - Lecture seule sur le filesystem projet (sauf project.json stats)
  - Palace absent -> mode degrade silencieux (contributed_count = 0)
  - Ecriture project.json : atomique via fichier .tmp (T-14)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Seuil Jaccard pour deduplication (spec PROJ-11 §6.2)
JACCARD_THRESHOLD = 0.85

# Marqueur de confidentialite - bloque la promotion
_CONFIDENTIAL_MARKER = "{PROJECT_ROOT}"

try:
    from config import AGENT_MIN_QUALITY_SCORE as _DEFAULT_MIN_SCORE
except Exception:
    _DEFAULT_MIN_SCORE = 60

# Import tardif _is_duplicate pour eviter crash si agents absent
def _jaccard_is_duplicate(body_a: str, body_b: str, threshold: float) -> bool:
    """Jaccard lexical entre deux corps de skill."""
    def _tokens(text: str) -> set:
        return set(text.lower().split())

    tokens_a = _tokens(body_a)
    tokens_b = _tokens(body_b)
    if not tokens_a or not tokens_b:
        return False
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return (len(intersection) / len(union)) >= threshold


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ContributionResult:
    """Resultat du pipeline ProjectContributor.contribute()."""

    # Compteurs
    scanned:          int = 0    # skills locales lues
    skipped_dedup:    int = 0    # rejetees par deduplication locale
    skipped_global:   int = 0    # rejetees car deja dans la base globale
    skipped_quality:  int = 0    # rejetees par quality_score insuffisant
    skipped_confidential: int = 0  # rejetees car contiennent {PROJECT_ROOT}
    contributed_count: int = 0   # effectivement indexees dans MemPalace

    # Details
    contributed_ids:  list[str] = field(default_factory=list)
    errors:           list[str] = field(default_factory=list)

    # Etat palace
    palace_available: bool = True

    def to_dict(self) -> dict:
        return {
            "scanned":             self.scanned,
            "skipped_dedup":       self.skipped_dedup,
            "skipped_global":      self.skipped_global,
            "skipped_quality":     self.skipped_quality,
            "skipped_confidential": self.skipped_confidential,
            "contributed_count":   self.contributed_count,
            "contributed_ids":     self.contributed_ids,
            "errors":              self.errors,
            "palace_available":    self.palace_available,
        }


# ---------------------------------------------------------------------------
# Helpers module-level
# ---------------------------------------------------------------------------

def _load_local_skills(skills_dir: Path) -> list[dict]:
    """
    Lit tous les *.md dans projects/{slug}/skills/.

    Retourne une liste de dicts {name, body, path}.
    Lignes invalides ignorees silencieusement.
    """
    if not skills_dir.exists():
        return []
    skills = []
    for md_file in sorted(skills_dir.glob("*.md")):
        try:
            body = md_file.read_text(encoding="utf-8").strip()
            if body:
                skills.append({
                    "name": md_file.stem,
                    "body": body,
                    "path": str(md_file),
                })
        except OSError as exc:
            log.warning("_load_local_skills : impossible de lire %s : %s", md_file, exc)
    return skills


def _is_confidential(body: str) -> bool:
    """Retourne True si le corps contient le marqueur {PROJECT_ROOT}."""
    return _CONFIDENTIAL_MARKER in body


def _dedup_local(skills: list[dict], threshold: float) -> tuple[list[dict], int]:
    """
    Deduplique la liste locale par Jaccard.

    Retourne (skills_uniques, nb_rejetes).
    O(n^2) — acceptable (< 500 skills en pratique).
    """
    kept: list[dict] = []
    skipped = 0
    for skill in skills:
        duplicate = False
        for existing in kept:
            if _jaccard_is_duplicate(skill["body"], existing["body"], threshold):
                duplicate = True
                break
        if duplicate:
            skipped += 1
        else:
            kept.append(skill)
    return kept, skipped


def _strip_frontmatter(body: str) -> str:
    """
    Retire les lignes de frontmatter LCCA du corps d'un skill.

    Les lignes de frontmatter sont de la forme "quality_score: N" ou "score: N"
    (les 10 premieres lignes uniquement, prefixe "#" inclus).
    Retourne le corps sans ces lignes, strip() applique.
    """
    lines = body.splitlines()
    result_lines = []
    for i, line in enumerate(lines):
        stripped = line.strip().lstrip("#").strip()
        if i < 10 and any(
            stripped.lower().startswith(p)
            for p in ("quality_score:", "score:")
        ):
            continue  # ligne de frontmatter, ignoree
        result_lines.append(line)
    return "\n".join(result_lines).strip()


def _build_global_entry_id(slug: str, skill_name: str) -> str:
    """Identifiant stable pour la base globale : slug:skill_name."""
    import hashlib
    raw = f"{slug}:{skill_name}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def _increment_skills_generated(project_json_path: Path) -> None:
    """
    Incremente stats.skills_generated dans project.json (ecriture atomique T-14).
    Silencieux si echec.
    """
    try:
        data = json.loads(project_json_path.read_text(encoding="utf-8"))
        stats = data.get("stats", {})
        stats["skills_generated"] = int(stats.get("skills_generated", 0)) + 1
        data["stats"] = stats
        tmp = project_json_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(project_json_path)
    except Exception as exc:
        log.warning("_increment_skills_generated : echec sur %s : %s", project_json_path, exc)


# ---------------------------------------------------------------------------
# ProjectContributor
# ---------------------------------------------------------------------------

class ProjectContributor:
    """
    Pipeline de contribution des skills locales vers la base globale LCCA.

    Usage :
        contributor = ProjectContributor()
        result = contributor.contribute(meta, projects_dir)

    Ne leve jamais d'exception (mode degrade silencieux).
    """

    def __init__(
        self,
        palace_client=None,
        min_quality_score: int = _DEFAULT_MIN_SCORE,
        jaccard_threshold: float = JACCARD_THRESHOLD,
        projects_dir: Optional[Path] = None,
    ) -> None:
        """
        Args:
            palace_client      : MemPalaceClient injecte. Si None, tente d'instancier.
            min_quality_score  : Seuil qualite pour la promotion (defaut config).
            jaccard_threshold  : Seuil Jaccard deduplication (defaut 0.85).
            projects_dir       : Racine projects/. Detecte automatiquement si None.
        """
        self._palace = palace_client  # None = tentative paresseuse dans contribute()
        self._min_quality = min_quality_score
        self._threshold = jaccard_threshold
        self._projects_dir = projects_dir

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def contribute(self, meta, projects_dir: Optional[Path] = None) -> ContributionResult:
        """
        Execute le pipeline complet pour le projet donne.

        Args:
            meta         : ProjectMeta (slug, id, stats, etc.)
            projects_dir : Racine projects/. Prioritaire sur self._projects_dir.

        Returns:
            ContributionResult (jamais None, jamais d'exception)
        """
        result = ContributionResult()

        try:
            pdir = projects_dir or self._projects_dir
            if pdir is None:
                _core = Path(__file__).parent
                pdir = _core.parent / "projects"

            project_dir = pdir / meta.slug
            skills_dir  = project_dir / "skills"
            project_json = project_dir / ".llca" / "project.json"

            # 1. Scan
            local_skills = _load_local_skills(skills_dir)
            result.scanned = len(local_skills)
            if not local_skills:
                return result

            # 2. Dedup locale
            unique_skills, skipped_dedup = _dedup_local(local_skills, self._threshold)
            result.skipped_dedup = skipped_dedup

            # 3. Guard qualite + confidentialite
            candidates: list[dict] = []
            for skill in unique_skills:
                body = skill["body"]

                # Guard confidentiel
                if _is_confidential(body):
                    result.skipped_confidential += 1
                    continue

                # Guard qualite : on lit le score depuis le frontmatter si disponible
                # (format LCCA : premiere ligne "quality_score: N")
                quality = self._extract_quality(body)
                if quality < self._min_quality:
                    result.skipped_quality += 1
                    continue

                skill["quality_score"] = quality
                candidates.append(skill)

            # 4. Dedup globale + indexation MemPalace
            palace = self._get_palace()
            if palace is None:
                result.palace_available = False
                # On retourne sans indexer mais sans lever
                return result

            for skill in candidates:
                entry_id = _build_global_entry_id(meta.slug, skill["name"])

                # Dedup globale : compare le corps sans frontmatter
                # (la base globale stocke le contenu sans la ligne quality_score)
                body_for_dedup = _strip_frontmatter(skill["body"])
                already = self._is_in_global(palace, body_for_dedup)
                if already:
                    result.skipped_global += 1
                    continue

                # 5. Indexation
                try:
                    palace.mine_content(
                        content=skill["body"],
                        wing="project_global_skills",
                        room=meta.slug,
                        metadata={
                            "skill_name":    skill["name"],
                            "project_id":    meta.id,
                            "project_slug":  meta.slug,
                            "quality_score": skill.get("quality_score", 0),
                            "entry_id":      entry_id,
                        },
                    )
                    result.contributed_ids.append(entry_id)
                    result.contributed_count += 1

                    # 6. stats.skills_generated++
                    if project_json.exists():
                        _increment_skills_generated(project_json)

                except Exception as exc:
                    log.warning(
                        "ProjectContributor : echec indexation skill %s : %s",
                        skill["name"], exc,
                    )
                    result.errors.append(f"Echec indexation {skill['name']} : {exc}")

        except Exception as exc:
            log.warning("ProjectContributor.contribute : erreur inattendue : %s", exc)
            result.errors.append(f"Erreur interne : {exc}")

        return result

    # ------------------------------------------------------------------
    # Helpers prives
    # ------------------------------------------------------------------

    def _get_palace(self):
        """Instancie MemPalaceClient paresseusement. Retourne None si indisponible."""
        if self._palace is not None:
            return self._palace
        try:
            from core.mempalace_client import MemPalaceClient
            self._palace = MemPalaceClient()
            return self._palace
        except Exception as exc:
            log.warning("ProjectContributor._get_palace : %s", exc)
            return None

    def _is_in_global(self, palace, body: str) -> bool:
        """
        Verifie si un skill similaire existe deja dans project_global_skills.

        Cherche les N plus proches voisins et compare par Jaccard.
        Retourne False en cas d'erreur (mode degrade).
        """
        try:
            results = palace.search_memories(
                query=body[:200],
                wing="project_global_skills",
                n_results=5,
            )
            for entry in results:
                existing_body = entry.content or ""
                if _jaccard_is_duplicate(body, existing_body, self._threshold):
                    return True
            return False
        except Exception as exc:
            log.debug("ProjectContributor._is_in_global : %s", exc)
            return False

    @staticmethod
    def _extract_quality(body: str) -> int:
        """
        Extrait quality_score depuis le frontmatter Markdown.

        Cherche la premiere ligne "quality_score: N" ou "score: N".
        Retourne 0 si absent (conservateur).
        """
        for line in body.splitlines()[:10]:
            line = line.strip().lstrip("#").strip()
            for prefix in ("quality_score:", "score:"):
                if line.lower().startswith(prefix):
                    val = line[len(prefix):].strip()
                    try:
                        return int(val)
                    except ValueError:
                        pass
        return 0
