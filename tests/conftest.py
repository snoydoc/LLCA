# -*- coding: utf-8-sig -*-
"""
conftest.py -- Garde-fous réseau pour la suite de tests LCCA.

Problème : certains tests appellent accidentellement urllib.request.urlopen
vers GitHub (educator_github.py) sans mock. Sur Windows avec pare-feu,
la connexion TCP peut bloquer 5-10 minutes au lieu de lever OSError rapidement.

Solution : autouse fixture qui remplace urlopen par une version qui lève
immédiatement OSError("Network calls blocked in tests").

Exceptions explicites :
- Les tests qui patchent eux-mêmes urllib.request.urlopen (patch prend
  précédence sur cette fixture car il s'applique plus tard dans la stack).
- Les tests d'intégration réseau volontaires peuvent opt-out avec le marker
  @pytest.mark.network.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch


def _blocked_urlopen(req, timeout=None):
    """Remplacant urlopen qui leve immediatement OSError."""
    url = getattr(req, "full_url", str(req))
    raise OSError(
        f"[conftest] Network call blocked in tests: {url}\n"
        "Patch urllib.request.urlopen dans le test pour simuler la reponse."
    )


@pytest.fixture(autouse=True)
def block_network_calls(request):
    """
    Bloque tous les appels urllib.request.urlopen sauf si :
    1. Le test est marque @pytest.mark.network
    2. Le test patche lui-meme urlopen (le patch local prend precedence)

    Patche aussi core.agents.educator_github._sleep (binding local isole)
    pour eviter les sleeps reels du retry loop apres OSError (T-10 bis).
    Ce patch ne touche pas time.sleep global ni time.perf_counter.
    """
    if request.node.get_closest_marker("network"):
        yield  # Test reseau volontaire -- pas de blocage
        return

    with patch("urllib.request.urlopen", side_effect=_blocked_urlopen), \
         patch("core.agents.educator_github._sleep"):
        yield
