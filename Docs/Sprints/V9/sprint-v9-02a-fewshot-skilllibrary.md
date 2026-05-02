# Sprint V9-02-A — Few-shot SkillLibrary dans PromptBuilder
<!-- AI-READY | LCCA V9 | Sprint V9-02-A | Priorité P0 | Effort 1j -->

## Objectif

Connecter `SkillLibrary.retrieve()` à `PromptBuilder.build()` pour injecter des exemples
de code LCCA réels dans les prompts de génération. Gain estimé : +30% conformité LCCA.

## Prérequis

- V9-01-B terminé
- `core/skill_library.py` opérationnel (V8-05 ✅)

## Fichiers cibles

| # | Fichier | Opération |
|---|---------|-----------|
| 1 | `core/llm_generator.py` | PATCH — `PromptBuilder.build()` + `LLMGenerator.generate()` |
| 2 | `core/agents/coder_agent.py` | PATCH — extraction `skill_context` |
| 3 | `tests/test_llm_generator.py` | PATCH — 3 tests |

## Spécification

### Patch `PromptBuilder.build`

Ajouter `skill_context: str = ""` en paramètre :

```python
def build(
    self,
    op,
    intent,
    context: str = "",
    skill_context: str = "",   # V9-02-A
) -> tuple[str, str]:
    """
    Construit (system_prompt, user_prompt).

    Args:
        op            : PatchOperation
        intent        : NLIntent
        context       : Code source du fichier cible (60 premières lignes)
        skill_context : Snippets few-shot formatés par SkillLibrary.format_for_prompt()
    """
    # ... logique existante inchangée ...

    # V9-02-A : injection few-shot en tête du user prompt
    if skill_context:
        user = (
            "## Exemples de code LCCA existants (style à imiter)\n\n"
            + skill_context
            + "\n\n## Votre tâche\n\n"
            + user
        )

    return self._SYSTEM, user
```

### Patch `LLMGenerator.generate`

```python
def generate(
    self,
    op,
    intent,
    context      : str = "",
    skill_context: str = "",   # V9-02-A
) -> GenerationResult:
    ...
    system, user = self.builder.build(
        op, intent, context, skill_context=skill_context   # V9-02-A
    )
    ...
```

### Patch `CoderAgent.run_task`

```python
# Dans run_task(), avant l'appel generate() :
skill_context = contract.context.get("available_skills", "")

result = self._generator.generate(
    op=patch,
    intent=intent,
    context=file_context,
    skill_context=skill_context,   # V9-02-A
)
```

### Tests à ajouter : `class TestFewShotPrompt`

```python
class TestFewShotPrompt:
    def test_skill_context_injected_in_user_prompt(self):
        from core.llm_generator import PromptBuilder
        builder = PromptBuilder()
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="my_func", file="test.py")
        intent = MagicMock(details="parse JSON", project="LCCA", target="")
        _, user = builder.build(op, intent, skill_context="def example(): pass")
        assert "example" in user
        assert "Exemples de code LCCA" in user

    def test_empty_skill_context_no_injection(self):
        from core.llm_generator import PromptBuilder
        builder = PromptBuilder()
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="f", file="x.py")
        intent = MagicMock(details="do x", project="LCCA", target="")
        _, u1 = builder.build(op, intent)
        _, u2 = builder.build(op, intent, skill_context="")
        assert u1 == u2

    def test_generate_passes_skill_context_to_builder(self, mocker):
        from core.llm_generator import LLMGenerator
        gen = LLMGenerator()
        spy = mocker.spy(gen.builder, "build")
        mocker.patch.object(gen.ollama, "is_available", return_value=False)
        op = MagicMock(action="add", patch_type="add_function",
                       target_symbol="f", file="x.py")
        intent = MagicMock(details="x", project="P", target="")
        gen.generate(op, intent, skill_context="# skill snippet")
        kwargs = spy.call_args.kwargs
        assert kwargs.get("skill_context") == "# skill snippet"
```

## Critères d'acceptation

- [ ] `builder.build(op, intent, skill_context="def f(): pass")` → user contient "Exemples"
- [ ] `builder.build(op, intent)` → user identique à `build(op, intent, skill_context="")`
- [ ] `gen.generate(op, intent, skill_context=s)` propage `s` à `builder.build`
- [ ] `CoderAgent.run_task` lit `contract.context.get("available_skills", "")`
- [ ] 0 régression tests V8

## Protocole d'exécution

```
1. filesystem:read_text_file core/llm_generator.py   → repérer PromptBuilder.build
2. filesystem:edit_file core/llm_generator.py        → ajouter skill_context param à build()
3. filesystem:edit_file core/llm_generator.py        → propagation dans generate()
4. filesystem:read_text_file core/agents/coder_agent.py → repérer run_task()
5. filesystem:edit_file core/agents/coder_agent.py   → extraction skill_context
6. filesystem:edit_file tests/test_llm_generator.py  → ajouter TestFewShotPrompt
7. bash: python -m pytest tests/test_llm_generator.py -v -k "TestFewShot"
8. bash: python -m pytest tests/ -x -q
```

## Mise à jour skills

- **001** : pattern "V9-02-A — skill_context dans PromptBuilder.build() + CoderAgent"
- **004** : V9-02-A TERMINÉ
