# Sprint FL-02 — ModelRouter branché dans le pipeline
<!-- AI-READY | LCCA V11 | Sprint FL-02 | Priorité P1 | Effort 0.5j | Statut : 🔲 À FAIRE -->

## Objectif

Brancher `ModelRouter` (existant, ROUTER-01, jamais utilisé en prod) dans le pipeline
`AgentOrchestrator → CoderAgent` pour que le choix du modèle LLM soit piloté par la
complexité de la tâche et le type d'opération, au lieu d'utiliser toujours le modèle
par défaut hardcodé dans `config.py`.

**ModelRouter existe et est testé — il n'est jamais appelé dans le pipeline.**
Ce sprint branche ce qui existe sur ce qui manque.

## Contraintes invariantes

- `routing.enabled = false` dans `online_models.json` par défaut → **zéro régression**,
  le comportement actuel est préservé à l'identique si le fichier est absent ou désactivé
- `ModelRouter` ne lève jamais d'exception → le pipeline ne peut pas crasher à cause du routing
- Aucun secret (clé API) lu depuis le disque par ModelRouter — les clés arrivent en paramètre
- `CoderAgent` reste injectant-compatible (tests existants : `llm_generator=None` → stub)
- `AgentOrchestrator.create()` : signature étendue, tous nouveaux args optionnels

## Fichiers cibles

| # | Fichier | Opération | Lignes estimées |
|---|---------|-----------|-----------------|
| 1 | `core/agents/agent_orchestrator.py` | PATCH — injection `ModelRouter` dans `__init__` + `create()` | +20 lignes |
| 2 | `core/agents/coder_agent.py` | PATCH — `_generate_code()` consulte `ModelRouter` si injecté | +25 lignes |
| 3 | `tests/test_fl_02.py` | CREATE | ~80 lignes |

## Prérequis

- `core/model_router.py` — `ModelRouter`, `ModelDecision` (ROUTER-01) ✅
- `core/agents/agent_orchestrator.py` — `AgentOrchestrator.__init__()` + `create()` ✅
- `core/agents/coder_agent.py` — `CoderAgent.__init__()` + `_generate_code()` ✅
- `tests/test_model_router.py` — 55 tests existants, ne pas casser ✅

## Spécification

### 1. PATCH `agent_orchestrator.py`

Dans `AgentOrchestrator.__init__()`, ajouter l'attribut :

```python
# FL-02 : ModelRouter injecté (None = routing désactivé)
self._model_router = model_router   # nouveau param optionnel
```

Signature `__init__` étendue (nouvel arg à la fin, valeur par défaut `None`) :

```python
def __init__(
    self,
    bus: A2ALocalBus,
    architect: ArchitectAgent,
    coder: CoderAgent,
    reviewer: ReviewerAgent,
    tester: TesterAgent,
    skill_library=None,
    educator: Optional[EducatorAgent] = None,
    model_router=None,                          # FL-02
    max_iterations: int = KARPATHY_MAX_ITERATIONS,
    max_stagnation: int = KARPATHY_MAX_STAGNATION,
    timeout_sec: int = AGENT_PIPELINE_TIMEOUT,
) -> None:
    ...
    self._model_router = model_router           # FL-02
```

Dans `create()`, instancier `ModelRouter` et l'injecter dans `CoderAgent` :

```python
@classmethod
def create(
    cls,
    bus: A2ALocalBus,
    mcp_caller=None,
    skill_library=None,
    educator: Optional[EducatorAgent] = None,
    model_router=None,                          # FL-02 : injectable pour les tests
    max_iterations: int = KARPATHY_MAX_ITERATIONS,
    max_stagnation: int = KARPATHY_MAX_STAGNATION,
    timeout_sec: int = AGENT_PIPELINE_TIMEOUT,
) -> "AgentOrchestrator":
    # FL-02 : instancier ModelRouter par défaut si non injecté
    if model_router is None:
        try:
            from core.model_router import ModelRouter
            model_router = ModelRouter()
        except Exception as exc:
            logger.debug("[orchestrator] ModelRouter non disponible : %s", exc)
            model_router = None

    coder = CoderAgent.create(
        bus=bus,
        mcp_caller=mcp_caller,
        model_router=model_router,              # FL-02
    )
    return cls(
        bus=bus,
        architect=ArchitectAgent.create(bus=bus, mcp_caller=mcp_caller),
        coder=coder,
        reviewer=ReviewerAgent.create(bus=bus, mcp_caller=mcp_caller),
        tester=TesterAgent.create(bus=bus, mcp_caller=mcp_caller, skill_library=skill_library),
        skill_library=skill_library,
        educator=educator,
        model_router=model_router,              # FL-02
        max_iterations=max_iterations,
        max_stagnation=max_stagnation,
        timeout_sec=timeout_sec,
    )
```

### 2. PATCH `coder_agent.py`

Dans `CoderAgent.__init__()`, ajouter le param :

```python
def __init__(
    self,
    card: AgentCard,
    bus: A2ALocalBus,
    mcp_caller=None,
    llm_generator: "Optional[LLMGenerator]" = None,
    model_router=None,                          # FL-02
) -> None:
    super().__init__(card=card, bus=bus, mcp_caller=mcp_caller)
    self._llm = llm_generator
    self._model_router = model_router           # FL-02
```

Dans `CoderAgent.create()`, accepter et passer le router :

```python
@classmethod
def create(
    cls,
    bus: A2ALocalBus,
    mcp_caller=None,
    llm_generator: "Optional[LLMGenerator]" = None,
    model_router=None,                          # FL-02
) -> "CoderAgent":
    ...
    return cls(
        card=card,
        bus=bus,
        mcp_caller=mcp_caller,
        llm_generator=llm_generator,
        model_router=model_router,              # FL-02
    )
```

Dans `_generate_code()`, consulter le router **avant** l'appel LLM :

```python
def _generate_code(self, contract: TaskContract, skills_ctx: str) -> str:
    if self._llm is None:
        logger.debug("[coder] _generate_code : llm=None -> stub vide")
        return ""

    # FL-02 : demander au ModelRouter quel modèle utiliser
    if self._model_router is not None:
        try:
            complexity = contract.context.get("complexity_score", 5) if isinstance(contract.context, dict) else 5
            decision = self._model_router.get_model(
                task_type="coding",
                complexity_score=complexity,
            )
            if decision.model_name != self._llm.ollama.model:
                logger.info(
                    "[coder] model_router: %s → %s (reason: %s)",
                    self._llm.ollama.model, decision.model_name, decision.reason,
                )
                self._llm.ollama.model = decision.model_name
        except Exception as exc:
            logger.debug("[coder] model_router.get_model error (ignored): %s", exc)

    prompt = _build_coder_prompt(
        contract.intent,
        contract.domain,
        skills_ctx,
        fix_hints          = contract.context.get("fix_hints") if isinstance(contract.context, dict) else None,
        last_quality_score = contract.context.get("last_quality_score") if isinstance(contract.context, dict) else None,
    )
    ...  # reste inchangé
```

> ⚠️ `self._llm.ollama.model` est l'attribut exposé par `OllamaClient` dans
> `llm_generator.py`. Si le router retourne le même modèle, aucune modification
> n'est faite (guard `!= model`). Si `OllamaClient` n'a pas d'attribut `ollama`,
> l'exception est swallowée silencieusement (guard `except Exception`).

## Tests — `tests/test_fl_02.py`

```python
# tests/test_fl_02.py
"""FL-02 — Tests branchement ModelRouter dans le pipeline."""
import pytest
from unittest.mock import MagicMock, patch


class TestCoderAgentRouterInjection:
    """Vérifie que CoderAgent accepte model_router et l'utilise dans _generate_code."""

    def _make_coder(self, router=None):
        from core.agents.coder_agent import CoderAgent
        bus  = MagicMock()
        card = MagicMock()
        llm  = MagicMock()
        llm.ollama = MagicMock()
        llm.ollama.model = "qwen2.5-coder:3b"
        llm.generate_text.return_value = "def f(): pass"
        return CoderAgent(card=card, bus=bus, llm_generator=llm, model_router=router)

    def _make_contract(self, complexity=3):
        from core.agents.a2a_bus import TaskContract
        c = TaskContract(
            task_id="t1", intent="create f", domain="global",
            source_agent="architect", target_agent="coder",
        )
        c.context["complexity_score"] = complexity
        return c

    def test_router_none_no_crash(self):
        """Sans router, _generate_code fonctionne normalement."""
        coder = self._make_coder(router=None)
        result = coder._generate_code(self._make_contract(), "")
        assert isinstance(result, str)

    def test_router_called_with_coding_task(self):
        """Le router est appelé avec task_type='coding'."""
        from core.model_router import ModelDecision
        router = MagicMock()
        router.get_model.return_value = ModelDecision(
            model_name="qwen2.5-coder:3b", provider="ollama",
            is_online=False, fallback_used=False, reason="test",
        )
        coder = self._make_coder(router=router)
        coder._generate_code(self._make_contract(complexity=4), "")
        router.get_model.assert_called_once()
        call_kwargs = router.get_model.call_args
        assert call_kwargs[1].get("task_type") == "coding" or call_kwargs[0][0] == "coding"

    def test_router_changes_model_when_different(self):
        """Si le router retourne un modèle différent, ollama.model est mis à jour."""
        from core.model_router import ModelDecision
        router = MagicMock()
        router.get_model.return_value = ModelDecision(
            model_name="qwen3:8b", provider="ollama",
            is_online=False, fallback_used=False, reason="heavy",
        )
        coder = self._make_coder(router=router)
        coder._generate_code(self._make_contract(complexity=8), "")
        assert coder._llm.ollama.model == "qwen3:8b"

    def test_router_no_change_when_same_model(self):
        """Si le router retourne le même modèle, ollama.model n'est pas réassigné."""
        from core.model_router import ModelDecision
        router = MagicMock()
        router.get_model.return_value = ModelDecision(
            model_name="qwen2.5-coder:3b", provider="ollama",
            is_online=False, fallback_used=False, reason="default",
        )
        coder = self._make_coder(router=router)
        original = coder._llm.ollama.model
        coder._generate_code(self._make_contract(complexity=2), "")
        assert coder._llm.ollama.model == original

    def test_router_exception_swallowed(self):
        """Si le router lève une exception, _generate_code continue normalement."""
        router = MagicMock()
        router.get_model.side_effect = RuntimeError("router crash")
        coder = self._make_coder(router=router)
        result = coder._generate_code(self._make_contract(), "")
        assert isinstance(result, str)


class TestOrchestratorRouterInjection:
    """Vérifie que AgentOrchestrator.__init__ et create() acceptent model_router."""

    def test_init_stores_router(self):
        from core.agents.agent_orchestrator import AgentOrchestrator
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        router = MagicMock()
        orch = AgentOrchestrator(
            bus=bus,
            architect=MagicMock(), coder=MagicMock(),
            reviewer=MagicMock(), tester=MagicMock(),
            model_router=router,
        )
        assert orch._model_router is router

    def test_init_no_router_is_none(self):
        from core.agents.agent_orchestrator import AgentOrchestrator
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        orch = AgentOrchestrator(
            bus=bus,
            architect=MagicMock(), coder=MagicMock(),
            reviewer=MagicMock(), tester=MagicMock(),
        )
        assert orch._model_router is None

    def test_create_injects_router_into_coder(self):
        """create() passe le model_router au CoderAgent."""
        from core.agents.agent_orchestrator import AgentOrchestrator
        from core.agents.a2a_bus import A2ALocalBus
        bus = MagicMock(spec=A2ALocalBus)
        router = MagicMock()
        with patch("core.agents.agent_orchestrator.CoderAgent") as MockCoder, \
             patch("core.agents.agent_orchestrator.ArchitectAgent"), \
             patch("core.agents.agent_orchestrator.ReviewerAgent"), \
             patch("core.agents.agent_orchestrator.TesterAgent"):
            MockCoder.create.return_value = MagicMock()
            AgentOrchestrator.create(bus=bus, model_router=router)
            call_kwargs = MockCoder.create.call_args[1]
            assert call_kwargs.get("model_router") is router
```

## Critères d'acceptation

- [ ] `pytest tests/test_fl_02.py` : 8 passed
- [ ] `pytest tests/test_model_router.py` : toujours verts (55 tests)
- [ ] `pytest tests/test_orchestrator.py tests/test_refacto_07.py` : toujours verts
- [ ] `AgentOrchestrator.create()` sans `model_router` → comportement identique à avant FL-02
- [ ] `CoderAgent(model_router=None)` → comportement identique à avant FL-02

## Protocole d'exécution

```
1. filesystem:read_text_file core/agents/agent_orchestrator.py
2. filesystem:edit_file core/agents/agent_orchestrator.py
   → __init__ : ajouter param model_router=None + self._model_router
   → create() : instancier ModelRouter + passer à CoderAgent.create()
3. filesystem:read_text_file core/agents/coder_agent.py
4. filesystem:edit_file core/agents/coder_agent.py
   → __init__ : ajouter param model_router=None + self._model_router
   → create() : accepter + passer model_router
   → _generate_code() : bloc FL-02 avant _build_coder_prompt()
5. filesystem:write_file tests/test_fl_02.py
6. pytest tests/test_fl_02.py -v
7. pytest tests/test_model_router.py tests/test_orchestrator.py tests/test_refacto_07.py -v
```

## ⚠️ Points d'attention

- `self._llm.ollama.model` : attribut de `OllamaClient` (via `LLMGenerator.ollama`).
  Si `LLMGenerator` n'expose pas `ollama`, l'exception est swallowée — pas de crash.
- Le router est consulté **une fois par appel** `_generate_code()`, pas par itération de boucle.
  Si la même instance `CoderAgent` est réutilisée sur plusieurs itérations,
  le modèle peut changer entre deux itérations (comportement voulu).
- `model_router=None` dans les tests existants (`test_refacto_07.py`) → aucun changement
  de comportement puisque le bloc FL-02 est sous `if self._model_router is not None`.
- `AgentOrchestrator.create()` : `model_router=None` → `ModelRouter()` instancié automatiquement.
  Si `online_models.json` absent → `routing.enabled=False` → fallback local silencieux. ✅

## Mise à jour skills post-sprint

- **001** : FL-02 — `ModelRouter` branché dans `CoderAgent._generate_code()` via `self._model_router`
- **002** : +8 tests test_fl_02.py, état tests ~1566
- **004** : FL-02 TERMINÉ
