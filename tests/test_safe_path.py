# -*- coding: utf-8-sig -*-
"""
test_safe_path.py — LCCA V7
Sprint 12 — TASK-12-T3

Tests unitaires pour utils/safe_path.py :
  - safe_path()          — résolution et validation de chemins
  - safe_path_or_none()  — variante None-safe pour champs optionnels MCP

Tous les tests sont isolés (workspace temporaire via tmp_path).
Exécution : pytest tests/test_safe_path.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.safe_path import PathSecurityError, safe_path, safe_path_or_none


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────

@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """Workspace temporaire isolé par test."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


# ──────────────────────────────────────────────────────────────
# Cas nominaux — chemins valides
# ──────────────────────────────────────────────────────────────

class TestSafePathValid:
    def test_simple_file(self, ws):
        """Un chemin relatif simple est résolu dans le workspace."""
        result = safe_path("module.py", workspace=ws)
        assert result == (ws / "module.py").resolve()

    def test_subdirectory_file(self, ws):
        """Un chemin relatif avec sous-dossier est résolu correctement."""
        result = safe_path("core/utils.py", workspace=ws)
        assert result == (ws / "core" / "utils.py").resolve()

    def test_returns_path_object(self, ws):
        """safe_path() retourne toujours un objet pathlib.Path."""
        result = safe_path("file.py", workspace=ws)
        assert isinstance(result, Path)

    def test_path_input_accepted(self, ws):
        """safe_path() accepte un Path en entrée (pas seulement str)."""
        result = safe_path(Path("sub/module.py"), workspace=ws)
        assert result == (ws / "sub" / "module.py").resolve()

    def test_deep_nested_path(self, ws):
        """Chemin profondément imbriqué — reste dans le workspace."""
        result = safe_path("a/b/c/d/e.py", workspace=ws)
        assert result == (ws / "a" / "b" / "c" / "d" / "e.py").resolve()

    def test_result_starts_with_workspace(self, ws):
        """Le résultat est toujours un descendant du workspace."""
        result = safe_path("nested/file.txt", workspace=ws)
        assert str(result).startswith(str(ws.resolve()))


# ──────────────────────────────────────────────────────────────
# Rejet — chemins absolus
# ──────────────────────────────────────────────────────────────

class TestSafePathAbsolute:
    def test_absolute_windows_path_raises(self, ws):
        """Un chemin absolu Windows lève PathSecurityError."""
        with pytest.raises(PathSecurityError):
            safe_path("C:/Windows/System32/cmd.exe", workspace=ws)

    def test_absolute_unix_path_raises(self, ws):
        """Un chemin absolu Unix lève PathSecurityError."""
        with pytest.raises(PathSecurityError):
            safe_path("/etc/passwd", workspace=ws)

    def test_absolute_unc_path_raises(self, ws):
        """Un chemin UNC absolu lève PathSecurityError."""
        with pytest.raises(PathSecurityError):
            safe_path("//server/share/file.txt", workspace=ws)

    def test_error_message_mentions_absolute(self, ws):
        """Le message d'erreur mentionne l'interdiction des chemins absolus."""
        with pytest.raises(PathSecurityError, match="absolu"):
            safe_path("D:/LLMCodeAgent/core/secret.py", workspace=ws)


# ──────────────────────────────────────────────────────────────
# Rejet — traversal via ".."
# ──────────────────────────────────────────────────────────────

class TestSafePathTraversal:
    def test_parent_traversal_raises(self, ws):
        """'../secret.py' — remonte au-dessus du workspace → erreur."""
        with pytest.raises(PathSecurityError):
            safe_path("../secret.py", workspace=ws)

    def test_deep_traversal_raises(self, ws):
        """'../../etc/passwd' — traversal multiple → erreur."""
        with pytest.raises(PathSecurityError):
            safe_path("../../etc/passwd", workspace=ws)

    def test_embedded_traversal_raises(self, ws):
        """'subdir/../../outside.py' — '..' intégré → erreur."""
        with pytest.raises(PathSecurityError):
            safe_path("subdir/../../outside.py", workspace=ws)

    def test_windows_backslash_traversal_raises(self, ws):
        r"""'..\outside.py' (antislash Windows) → erreur."""
        with pytest.raises(PathSecurityError):
            safe_path(r"..\outside.py", workspace=ws)

    def test_error_message_mentions_traversal(self, ws):
        """Le message d'erreur mentionne le path traversal."""
        with pytest.raises(PathSecurityError, match=r"\.\.|traversal|interdit"):
            safe_path("../escape.py", workspace=ws)


# ──────────────────────────────────────────────────────────────
# Rejet — chemin vide
# ──────────────────────────────────────────────────────────────

class TestSafePathEmpty:
    def test_empty_string_raises(self, ws):
        """Un chemin vide lève ValueError."""
        with pytest.raises(ValueError):
            safe_path("", workspace=ws)

    def test_whitespace_only_raises(self, ws):
        """Un chemin composé uniquement d'espaces lève ValueError."""
        with pytest.raises(ValueError):
            safe_path("   ", workspace=ws)


# ──────────────────────────────────────────────────────────────
# Workspace personnalisé
# ──────────────────────────────────────────────────────────────

class TestSafePathCustomWorkspace:
    def test_custom_workspace_used(self, tmp_path):
        """Le workspace personnalisé est utilisé comme racine."""
        ws_a = tmp_path / "workspace_a"
        ws_b = tmp_path / "workspace_b"
        ws_a.mkdir()
        ws_b.mkdir()

        result_a = safe_path("module.py", workspace=ws_a)
        result_b = safe_path("module.py", workspace=ws_b)

        assert result_a != result_b
        assert str(result_a).startswith(str(ws_a.resolve()))
        assert str(result_b).startswith(str(ws_b.resolve()))

    def test_file_outside_custom_workspace_raises(self, tmp_path):
        """Un chemin qui résoudrait hors du workspace personnalisé → erreur."""
        ws = tmp_path / "workspace"
        ws.mkdir()

        # On tente d'atteindre tmp_path directement
        with pytest.raises(PathSecurityError):
            safe_path("../outside.py", workspace=ws)


# ──────────────────────────────────────────────────────────────
# safe_path_or_none()
# ──────────────────────────────────────────────────────────────

class TestSafePathOrNone:
    def test_none_input_returns_none(self, ws):
        """None en entrée → None en sortie (pas d'erreur)."""
        result = safe_path_or_none(None, workspace=ws)
        assert result is None

    def test_empty_string_returns_none(self, ws):
        """Chaîne vide → None (cas optionnel MCP)."""
        result = safe_path_or_none("", workspace=ws)
        assert result is None

    def test_valid_path_resolved(self, ws):
        """Chemin valide → Path résolu normalement."""
        result = safe_path_or_none("module.py", workspace=ws)
        assert result == (ws / "module.py").resolve()

    def test_traversal_still_raises(self, ws):
        """Un traversal passé à safe_path_or_none() lève quand même PathSecurityError."""
        with pytest.raises(PathSecurityError):
            safe_path_or_none("../../etc/shadow", workspace=ws)

    def test_absolute_still_raises(self, ws):
        """Un chemin absolu passé à safe_path_or_none() lève PathSecurityError."""
        with pytest.raises(PathSecurityError):
            safe_path_or_none("/etc/passwd", workspace=ws)


# ──────────────────────────────────────────────────────────────
# Cas limites & robustesse
# ──────────────────────────────────────────────────────────────

class TestSafePathEdgeCases:
    def test_dot_prefix_file(self, ws):
        """Fichier débutant par '.' (fichier caché Unix) — valide."""
        result = safe_path(".env", workspace=ws)
        assert result == (ws / ".env").resolve()

    def test_extension_with_multiple_dots(self, ws):
        """Fichier avec plusieurs points dans le nom — valide."""
        result = safe_path("archive.tar.gz", workspace=ws)
        assert result == (ws / "archive.tar.gz").resolve()

    def test_path_with_spaces(self, ws):
        """Chemin avec espaces (entre guillemets) — valide si dans le workspace."""
        result = safe_path("my module/utils.py", workspace=ws)
        assert result == (ws / "my module" / "utils.py").resolve()

    def test_single_dot_is_workspace_itself(self, ws):
        """'.' seul résoud en workspace — reste dans le workspace."""
        result = safe_path(".", workspace=ws)
        assert result == ws.resolve()

    def test_path_security_error_is_exception(self, ws):
        """PathSecurityError est une Exception (pas juste BaseException)."""
        assert issubclass(PathSecurityError, Exception)

    def test_valid_path_does_not_need_to_exist(self, ws):
        """safe_path() valide le chemin logique, pas l'existence physique."""
        result = safe_path("nonexistent/future_file.py", workspace=ws)
        # Le fichier n'existe pas — mais safe_path() ne doit pas lever
        assert result is not None
        assert isinstance(result, Path)
