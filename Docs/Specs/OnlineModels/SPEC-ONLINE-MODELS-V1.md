# SPEC — Online Models & Model Router — V1.0
# Date : 2026-04-24
# Statut : VALIDÉE — prête à implémenter

---

## 1. Problème

LCCA utilise un modèle Ollama unique configuré dans `config.py`.
Deux besoins non couverts :

1. **Routing automatique** : certaines tâches (debug complexe, patch critique)
   méritent un modèle plus puissant que le modèle par défaut.
2. **Providers cloud optionnels** : Kimi (Moonshot AI) et d'autres LLM en ligne
   peuvent servir de fallback ou de booster ponctuel pour les tâches critiques,
   sans compromettre le fonctionnement offline-first de LCCA.

---

## 2. Périmètre

Ce sprint couvre :

- `core/model_router.py` — routeur de modèles (logique de sélection)
- `online_models.json` — configuration des providers online (source de vérité)
- `core/providers/` — clients HTTP providers (un fichier par provider)
- UI : panneau "Modèles en ligne" dans `SettingsModal.tsx`
- 5 handlers IPC nouveaux dans `main.ts` + `preload.ts`

Ce sprint ne couvre **pas** :
- Modification du pipeline KarpathyLoop (intégration future ROUTER-03)
- Fine-tuning ou distillation depuis les réponses cloud
- Authentification OAuth (clés API bearer uniquement)

---

## 3. Invariants absolus

```
INV-01  online = False dans online_models.json → provider jamais appelé
INV-02  pas de clé API → fallback local silencieux, 0 erreur levée vers l'utilisateur
INV-03  réseau indisponible → fallback local silencieux, 0 crash
INV-04  auto_push = false conservé (aucun lien avec ce sprint)
INV-05  OLLAMA_TIMEOUT = None et SPEC_TIMEOUT = None : inchangés
INV-06  model_router.py ne modifie jamais config.py ni online_models.json
INV-07  les clés API sont stockées dans electron-store (main process) — jamais dans un fichier disque
```

---

## 4. Fichier de configuration — `online_models.json`

**Chemin** : `D:\LLMCodeAgent\online_models.json`
**Propriétaire** : lu par `model_router.py` (Python) ET par `main.ts` (Electron via IPC)
**Format** :

```json
{
  "version": "1.0",
  "providers": [
    {
      "id": "kimi",
      "name": "Kimi (Moonshot AI)",
      "api_url": "https://api.moonshot.ai/v1/chat/completions",
      "model_name": "moonshot-v1-8k",
      "online": false,
      "timeout_sec": 30,
      "max_tokens": 2000,
      "description": "Modele cloud Moonshot AI — 8k contexte",
      "roles": ["coding", "debug", "spec"],
      "min_complexity": 6
    },
    {
      "id": "openrouter_qwen3_72b",
      "name": "Qwen3-72B via OpenRouter",
      "api_url": "https://openrouter.ai/api/v1/chat/completions",
      "model_name": "qwen/qwen3-72b",
      "online": false,
      "timeout_sec": 60,
      "max_tokens": 2000,
      "description": "Qwen3 72B via OpenRouter — necessite cle API",
      "roles": ["coding", "spec"],
      "min_complexity": 7
    }
  ],
  "routing": {
    "enabled": false,
    "complexity_source": "spec_estimator",
    "fallback_to_local": true,
    "thresholds": {
      "use_heavy_local": 5,
      "use_online": 6,
      "force_online": 8
    }
  }
}
```

### Champs obligatoires par provider

| Champ | Type | Description |
|-------|------|-------------|
| `id` | str | Identifiant unique snake_case |
| `name` | str | Label affiché dans l'UI |
| `api_url` | str | Endpoint REST (OpenAI-compatible ou custom) |
| `model_name` | str | Nom du modèle à passer dans la requête |
| `online` | bool | **Master switch** — false = jamais appelé |
| `timeout_sec` | int | Timeout réseau (secondes) |
| `max_tokens` | int | Limite de génération |
| `description` | str | Texte affiché dans l'UI |
| `roles` | list[str] | Tâches autorisées : "coding" \| "debug" \| "spec" \| "nl" |
| `min_complexity` | int | Score minimum (0-10) pour activer ce provider |

### Champ clé API

La clé API n'est **pas** dans `online_models.json`.
Elle est stockée dans `electron-store` sous la clé `online_model_keys.<provider_id>`.
`model_router.py` la reçoit via l'IPC `onlineModels:getKey` — jamais via fichier disque.

---

## 5. `core/model_router.py` — spécification

### Interface publique

```python
class ModelRouter:
    def __init__(self, config_path: Path | None = None) -> None: ...

    def get_model(
        self,
        task_type:        str,          # "coding" | "debug" | "spec" | "nl"
        complexity_score: int,          # 0-100 (SpecComplexityEstimator) ou 0-10 (heuristique)
        api_key:          str | None,   # clé API du provider choisi, ou None
    ) -> ModelDecision: ...

    def list_available_online(self) -> list[dict]: ...

    def reload_config(self) -> None: ...
```

### Dataclass de retour

```python
@dataclass
class ModelDecision:
    model_name:    str           # Ex: "qwen3:8b" ou "moonshot-v1-8k"
    provider:      str           # "ollama" | "kimi" | "openrouter_qwen3_72b" | ...
    is_online:     bool          # True si provider cloud
    fallback_used: bool          # True si fallback local déclenché
    reason:        str           # Log human-readable
```

### Logique de routing (pseudo-code)

```
score_norm = complexity_score // 10  # normalise 0-100 → 0-10

si routing.enabled == False:
    → local principal (OLLAMA_MODEL depuis config.py)

si task_type == "debug":
    → OLLAMA_MODEL_DEBUG si défini, sinon OLLAMA_MODEL_HEAVY

si score_norm >= routing.thresholds.use_online:
    chercher provider online avec:
      - online == True
      - task_type dans provider.roles
      - min_complexity <= score_norm
      - api_key fournie et non vide
    si trouvé → retourner ce provider
    sinon → fallback local (fallback_used=True)

si score_norm >= routing.thresholds.use_heavy_local:
    → OLLAMA_MODEL_HEAVY

→ OLLAMA_MODEL (défaut)
```

### Règles d'implémentation

- `model_router.py` < 6 KB (responsabilité unique : décision)
- `ModelRouter.__init__` charge `online_models.json` via `Path.read_text()`
- `reload_config()` relit le fichier (hotreload sans redémarrer le serveur)
- Toute erreur de lecture JSON → log warning + routing désactivé (mode dégradé)
- `model_router.py` n'instancie pas `OllamaClient` ni aucun provider
- Les clés API arrivent en paramètre — jamais lues depuis le disque dans ce module

---

## 6. `core/providers/` — clients HTTP

### Structure

```
core/providers/
  __init__.py
  base_provider.py      # ABC + ProviderResult dataclass
  kimi_provider.py      # Client Moonshot AI
  openrouter_provider.py  # Client OpenRouter (générique OpenAI-compat)
```

### `base_provider.py`

```python
@dataclass
class ProviderResult:
    text:          str
    model:         str
    provider_id:   str
    tokens_used:   int
    duration_ms:   int
    from_fallback: bool

class BaseProvider(ABC):
    @abstractmethod
    def generate(self, system: str, user: str, api_key: str) -> ProviderResult: ...

    @abstractmethod
    def is_compatible(self, provider_cfg: dict) -> bool: ...
```

### `kimi_provider.py`

- Endpoint : `POST https://api.moonshot.ai/v1/chat/completions`
- Format request : OpenAI-compatible (`messages`, `model`, `max_tokens`)
- Header : `Authorization: Bearer {api_key}`
- `urllib.request` uniquement (pas de `requests`)
- Timeout : `provider_cfg["timeout_sec"]`
- Erreur réseau → lève `ProviderError(message, recoverable=True)`
- `ProviderError` catchée dans `LLMGenerator` → fallback silencieux

### `openrouter_provider.py`

- Même format OpenAI-compatible que Kimi
- Header additionnel : `HTTP-Referer: https://lcca.local` (requis OpenRouter)
- Réutilise 90% du code de `kimi_provider.py` → factoriser dans `_openai_compat_call()`

---

## 7. Intégration dans `LLMGenerator`

Modification minimale — **aucune rupture d'interface** :

```python
# llm_generator.py — ajout dans generate()
def generate(self, op, intent, context="", skill_context="",
             task_type="coding", complexity_score=0, api_key=None):

    if self._router and self._router_enabled:
        decision = self._router.get_model(task_type, complexity_score, api_key)
        if decision.is_online and not decision.fallback_used:
            return self._generate_via_provider(decision, system, user)
    # ... pipeline existant inchangé
```

`self._router` : `ModelRouter | None` — `None` si `online_models.json` absent (rétrocompat totale)
`self._router_enabled` : `bool` — lu depuis `routing.enabled` dans le JSON

---

## 8. UI — `OnlineModelsPanel.tsx`

Composant intégré dans `SettingsModal.tsx` comme nouvelle `<Section>`.

### Affichage

Pour chaque provider dans `online_models.json` :

```
┌─────────────────────────────────────────────────────┐
│  🌐 Kimi (Moonshot AI)         [●] Activé    [Tester]│
│  Modele cloud Moonshot AI — 8k contexte              │
│  Rôles : coding, debug, spec  |  Complexité min : 6  │
│  Clé API : [••••••••••••]  [Modifier]                │
└─────────────────────────────────────────────────────┘
```

### Interactions

| Action | IPC appelé |
|--------|-----------|
| Toggle ON/OFF provider | `onlineModels:setEnabled` |
| Modifier clé API | `onlineModels:setKey` |
| Tester la connexion | `onlineModels:testProvider` |
| Toggle routing global | `onlineModels:setRoutingEnabled` |

### États

- **Désactivé** (online=false) : badge gris "Désactivé", bouton Tester grisé
- **Activé sans clé** : badge orange "Clé manquante"
- **Activé avec clé** : badge vert "Prêt"
- **Test en cours** : spinner + "Test…"
- **Test réussi** : badge vert temporaire "✓ Connecté"
- **Test échoué** : badge rouge temporaire "✗ Erreur réseau"

---

## 9. IPC nouveaux — `main.ts` / `preload.ts`

### 5 handlers IPC

```typescript
// Lire la config providers (sans les clés)
ipcMain.handle('onlineModels:getConfig', () => { ... })
// Retourne: { providers: ProviderPublic[], routing: RoutingConfig }

// Activer/désactiver un provider (écrit dans online_models.json)
ipcMain.handle('onlineModels:setEnabled', (_event, providerId: string, enabled: boolean) => { ... })

// Lire/écrire une clé API (electron-store — jamais sur disque)
ipcMain.handle('onlineModels:getKey', (_event, providerId: string) => { ... })
ipcMain.handle('onlineModels:setKey', (_event, providerId: string, key: string) => { ... })

// Test de connexion (appel HTTP léger)
ipcMain.handle('onlineModels:testProvider', (_event, providerId: string) => { ... })
// Retourne: { ok: boolean, latency_ms: number, error?: string }

// Toggle routing global
ipcMain.handle('onlineModels:setRoutingEnabled', (_event, enabled: boolean) => { ... })
```

### Sécurité clés API

- Stockées dans `electron-store` sous `online_model_keys.<provider_id>`
- `getKey` retourne `"has_key"` (booléen masqué) si la clé existe, `""` sinon — jamais la valeur réelle vers le renderer
- La vraie clé n'est lue que dans `main.ts` pour le test de connexion
- `testProvider` dans `main.ts` fait l'appel HTTP directement — la clé ne transite jamais vers le renderer

---

## 10. Sprints

| Sprint | Fichiers | Tests | Dépendances |
|--------|----------|-------|-------------|
| ROUTER-01 | `online_models.json` + `core/model_router.py` + `tests/test_router_01.py` | 15 tests | Aucune |
| ROUTER-02 | `core/providers/__init__.py` + `base_provider.py` + `kimi_provider.py` + `openrouter_provider.py` + `tests/test_router_02.py` | 12 tests | ROUTER-01 |
| ROUTER-03 | Patch `llm_generator.py` (intégration router) + `tests/test_router_03.py` | 10 tests | ROUTER-01/02 |
| ROUTER-04 | UI : `OnlineModelsPanel.tsx` + 5 IPC `main.ts` + patch `preload.ts` + patch `settingsStore.ts` | Tests manuels | ROUTER-01 |

### Ordre recommandé

ROUTER-01 → ROUTER-04 (UI) → ROUTER-02 → ROUTER-03

Justification : ROUTER-04 peut être fait sans les providers réels (affichage de la config JSON).
ROUTER-02/03 peuvent attendre d'avoir une vraie clé API Kimi pour tester end-to-end.

---

## 11. Tests — ROUTER-01 (15 tests)

```
test_decision_local_default          → routing disabled → OLLAMA_MODEL
test_decision_heavy_local            → complexity 55 → OLLAMA_MODEL_HEAVY
test_decision_debug_task             → task_type=debug → OLLAMA_MODEL_DEBUG
test_decision_online_kimi            → complexity 70, kimi online=True, clé fournie → kimi
test_decision_online_fallback_no_key → complexity 70, kimi online=True, clé None → local fallback
test_decision_online_fallback_offline → kimi online=False → local fallback
test_decision_role_mismatch          → task_type hors roles → local fallback
test_decision_min_complexity_not_met → complexity 30, min_complexity=60 → local fallback
test_list_available_online           → retourne providers avec online=True
test_reload_config                   → modifie le JSON sur disque → reload → nouvelle valeur
test_bad_json_falls_back_silently    → JSON invalide → routing disabled, no exception
test_missing_file_falls_back         → fichier absent → routing disabled, no exception
test_model_decision_dataclass        → vérifie champs is_online, fallback_used, reason
test_routing_disabled_flag           → routing.enabled=False → toujours local
test_complexity_normalisation        → score 65 → score_norm 6 (65//10)
```

---

## 12. `config.py` — ajouts

3 constantes à ajouter dans la section "LLM / Ollama" :

```python
OLLAMA_MODEL_DEBUG   = "deepseek-r1:14b"   # ROUTER-01 : modele pour task_type=debug
ONLINE_MODELS_PATH   = BASE_DIR / "online_models.json"  # chemin config providers
```

(OLLAMA_MODEL_LIGHT existe déjà — ne pas dupliquer)

---

## 13. Règles LCCA applicables

- `model_router.py` < 6 KB (1 responsabilité : décision)
- `kimi_provider.py` < 6 KB (1 responsabilité : HTTP Kimi)
- `urllib.request` uniquement — jamais `requests`
- Toute exception réseau → `ProviderError(recoverable=True)` → catchée → fallback silencieux
- Clés API : jamais sur disque, jamais dans les logs, jamais dans le renderer
- `online_models.json` : écriture atomique `.tmp → .replace()` (règle T-14)
- Tests providers : `urllib.request.urlopen` mocké via `conftest.py` (règle T-10)
- `ModelRouter.__init__` : injectable `config_path` pour les tests (règle `tmp_path`)
