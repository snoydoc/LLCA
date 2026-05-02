#!/usr/bin/env python3
# -*- coding: utf-8-sig -*-
"""
scripts/migrate_cache_v6_to_v7.py
Script one-shot : génère les fichiers metadata .json manquants pour le
cache LLM (fichiers .py sans .json correspondant = cache pré-V7).

À exécuter UNE SEULE FOIS après mise à jour vers V7 :
    python scripts/migrate_cache_v6_to_v7.py

Effet :
  - Les entrées sans metadata reçoivent {model: "unknown", ...}.
  - Au prochain accès, LLMGenerator les considèrera comme cache miss
    si le modèle courant est différent de "unknown" (invalidation saine).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

try:
    from config import LLM_CACHE_DIR  # type: ignore
    cache_dir = LLM_CACHE_DIR
except ImportError:
    cache_dir = _ROOT / "transactions" / ".llm_cache"


def migrate() -> None:
    if not cache_dir.exists():
        print(f"Dossier cache introuvable : {cache_dir}")
        return

    migrated = 0
    skipped  = 0

    for py_file in sorted(cache_dir.glob("*.py")):
        meta_file = py_file.with_suffix(".json")
        if meta_file.exists():
            skipped += 1
            continue

        meta = {
            "model":       "unknown",
            "migrated_at": datetime.now(timezone.utc).isoformat(),
            "note":        "Cache généré avant versionnement par modèle (migration V6→V7)",
        }
        try:
            meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            migrated += 1
            print(f"  ✓ {py_file.name} → metadata créée (model=unknown)")
        except Exception as exc:
            print(f"  ✗ {py_file.name} → erreur : {exc}")

    print(
        f"\nMigration terminée : {migrated} metadata créée(s), "
        f"{skipped} déjà présente(s)."
    )
    if migrated:
        print(
            "INFO : Au prochain accès, ces entrées seront invalidées si le modèle\n"
            "       courant est différent de 'unknown' (comportement attendu V7)."
        )


if __name__ == "__main__":
    migrate()
