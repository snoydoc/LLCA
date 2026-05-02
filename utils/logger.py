"""
Logger structuré LCCA V5 Fusion.
Centralisé, coloré console, rotatif fichier.
Usage:
    from utils.logger import get_logger
    log = get_logger("transaction_manager")
    log.info("Transaction BEGIN tx_abc123")
    log.error("Rollback déclenché", extra={"tx_id": "abc123"})
"""
import logging
import logging.handlers
from pathlib import Path

# Dossier logs — créé automatiquement si absent
LOG_DIR = Path("D:/LLMCodeAgent/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Codes ANSI pour couleurs console
COLORS = {
    "DEBUG":    "\033[36m",   # Cyan
    "INFO":     "\033[32m",   # Vert
    "WARNING":  "\033[33m",   # Jaune
    "ERROR":    "\033[31m",   # Rouge
    "CRITICAL": "\033[35m",   # Magenta
    "RESET":    "\033[0m",
}


class ColoredFormatter(logging.Formatter):
    """Formatter console avec couleurs ANSI par niveau."""

    def format(self, record: logging.LogRecord) -> str:
        color = COLORS.get(record.levelname, COLORS["RESET"])
        reset = COLORS["RESET"]
        return f"{color}{super().format(record)}{reset}"


def get_logger(name: str) -> logging.Logger:
    """
    Retourne un logger nommé lcca.<name>, configuré une seule fois.

    Args:
        name: Nom du module source (ex: "transaction_manager").

    Returns:
        Logger Python standard avec handlers console + fichier.
    """
    logger = logging.getLogger(f"lcca.{name}")

    # Idempotent — ne réajoute pas les handlers si déjà configuré
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ── Handler console (INFO+, coloré) ──────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(ColoredFormatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    ))

    # ── Handler fichier rotatif (DEBUG+, utf-8) ───────────────────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "lcca.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))

    logger.addHandler(console)
    logger.addHandler(file_handler)
    return logger
