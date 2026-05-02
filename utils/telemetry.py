"""
Télémétrie LCCA V7 — Métriques légères en JSON Lines.

Règles :
  - Jamais bloquer le flux appelant (try/except silencieux partout)
  - Rotation automatique : 10 MB max, 5 backups
  - Format : JSON Lines (JSONL) — un objet par ligne
  - Thread-safe : flush() après chaque ligne

Utilisation::

    from utils.telemetry import log_metric, MetricTimer

    log_metric("ollama_tokens", 512, {"model": "qwen2.5-coder:14b"})

    with MetricTimer("edit_batch_duration", {"n_files": 3}):
        ...  # code mesuré
"""
from __future__ import annotations

import json
import time
import logging
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from config import LOGS_DIR

# ── Chemin du fichier de télémétrie ──────────────────────────────────────────
TELEMETRY_PATH: Path = LOGS_DIR / "telemetry.jsonl"

# ── Logger rotatif interne (pour les erreurs de la télémétrie elle-même) ─────
_internal_log = logging.getLogger("lcca.telemetry")

# ── Lock pour écriture concurrente ───────────────────────────────────────────
_write_lock = threading.Lock()

# ── Handler rotatif sur le fichier JSONL ─────────────────────────────────────
# 10 MB max, 5 fichiers de backup  →  50 MB total max
_MAX_BYTES  = 10 * 1024 * 1024   # 10 MB
_BACKUP_COUNT = 5

# Initialisation différée du handler (évite crash à l'import si LOGS_DIR absent)
_rotating_handler: Optional[RotatingFileHandler] = None


def _get_handler() -> Optional[RotatingFileHandler]:
    """Retourne (en créant si besoin) le handler rotatif."""
    global _rotating_handler
    if _rotating_handler is not None:
        return _rotating_handler
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _rotating_handler = RotatingFileHandler(
            filename=str(TELEMETRY_PATH),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        return _rotating_handler
    except Exception as exc:  # noqa: BLE001
        _internal_log.debug("Impossible de créer le handler télémétrie : %s", exc)
        return None


# ── API publique ──────────────────────────────────────────────────────────────

def log_metric(
    name: str,
    value: float,
    labels: Optional[dict] = None,
) -> None:
    """
    Écrit une métrique en JSON Lines dans ``telemetry.jsonl``.

    Args:
        name:   Nom de la métrique (ex: ``"edit_batch_duration"``).
        value:  Valeur numérique.
        labels: Dict de labels/tags optionnels (ex: ``{"tool": "edit_batch"}``).

    Note:
        Ne lève jamais d'exception — erreurs loguées à DEBUG uniquement.
    """
    entry = {
        "_ts":    datetime.now(timezone.utc).isoformat(),
        "metric": name,
        "value":  value,
        "labels": labels or {},
    }
    _write_entry(entry)


def _write_entry(entry: dict) -> None:
    """Écrit une entrée JSONL de façon thread-safe et silencieuse."""
    try:
        line = json.dumps(entry, ensure_ascii=False)
        handler = _get_handler()

        with _write_lock:
            if handler is not None:
                # Utiliser le handler rotatif (gère la rotation automatiquement)
                handler.stream  # Vérifie que le stream est ouvert
                handler.emit(
                    logging.makeLogRecord({"msg": line, "levelno": logging.INFO})
                )
                # Flush explicite pour durabilité
                if hasattr(handler, "stream") and handler.stream:
                    handler.stream.flush()
            else:
                # Fallback : écriture directe sans rotation
                with open(TELEMETRY_PATH, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                    fh.flush()
    except Exception as exc:  # noqa: BLE001
        _internal_log.debug("Échec écriture télémétrie : %s", exc)


class MetricTimer:
    """
    Context manager pour mesurer et enregistrer la durée d'un bloc.

    Utilisation::

        with MetricTimer("mcp_request_duration", {"method": "tools/call"}):
            result = handle_request(req)

    La métrique est émise à la sortie du bloc (même en cas d'exception).
    La valeur enregistrée est en **millisecondes**.
    """

    def __init__(self, name: str, labels: Optional[dict] = None) -> None:
        self.name   = name
        self.labels = labels or {}
        self._start: Optional[float] = None
        self.elapsed_ms: int = 0

    def __enter__(self) -> "MetricTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ANN001
        if self._start is not None:
            self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)
            status = "error" if exc_type is not None else "ok"
            log_metric(
                self.name,
                self.elapsed_ms,
                {**self.labels, "unit": "ms", "status": status},
            )
        # Ne pas supprimer l'exception (retourne None = False)
