# LCCA - ANTI-INTERRUPTION (S-01 / S-02 / S-03)
# Lire EN PREMIER, avant les autres skills.

## S-02 - Lecture DEBUT DE SESSION (OBLIGATOIRE)
Lire `D:\LLMCodeAgent\.claude-skills\session_state.json`.
Si `status = in_progress` -> STOP. Alerter l'utilisateur + proposer reprise avant toute action.

## S-01 - Checkpoint AVANT chaque action
Avant tout pull/rm/benchmark/sprint/ecriture de fichier :
Ecrire dans `session_state.json` :
```json
{
  "session_date": "YYYY-MM-DD HH:MM",
  "checkpoint": "description courte de l'action qui va demarrer",
  "status": "in_progress",
  "next_action": "commande exacte ou sprint a relancer si interruption"
}
```

## S-03 - Cloture de session
Apres toute action terminee avec succes :
Mettre `status: done` + `next_action` = prochain sprint ou commande.
