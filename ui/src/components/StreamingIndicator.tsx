// StreamingIndicator.tsx — Sprint UI-THINK-01 : indicateur style "Claude Desktop"
// Deux modes :
//   mode="full"    → bulle complète (pré-streaming, aucun contenu encore)
//   mode="inline"  → pastille compacte (pendant streaming de texte)
import { useEffect, useState } from 'react';

const TOOL_PHASES: Record<string, { label: string; steps: string[] }> = {
  llm_chat: {
    label: 'Réflexion',
    steps: [
      'Lecture du contexte…',
      'Analyse de la question…',
      'Construction de la réponse…',
      'Rédaction en cours…',
    ],
  },
  web_search: {
    label: 'Recherche web',
    steps: [
      'Interrogation DuckDuckGo…',
      'Récupération des pages…',
      'Extraction du contenu…',
      'Synthèse avec Ollama…',
    ],
  },
  generate_spec: {
    label: 'Génération de spec',
    steps: [
      "Analyse de l'intention…",
      'Raisonnement approfondi…',
      'Formatage Markdown…',
      'Validation des règles R01-R15…',
    ],
  },
  validate_spec: {
    label: 'Validation',
    steps: [
      'Chargement de la spec…',
      'Vérification R01-R15…',
      'Calcul du score…',
    ],
  },
  memory_search: {
    label: 'Recherche mémoire',
    steps: ['Encodage vectoriel…', 'Recherche ChromaDB…', 'Classement…'],
  },
  project_search: {
    label: 'Recherche projet',
    steps: ['Indexation AST…', 'Recherche de symboles…', 'Filtrage fichiers…'],
  },
  sandbox_run: {
    label: 'Exécution sandbox',
    steps: [
      "Préparation de l'environnement…",
      'Exécution du code…',
      'Collecte des sorties…',
    ],
  },
  evaluate_quality: {
    label: 'Évaluation qualité',
    steps: ['Parse AST…', 'Analyse des critères…', 'Calcul du score…'],
  },
  analyze_error: {
    label: "Analyse d'erreur",
    steps: [
      'Identification du type…',
      'Recherche de la cause…',
      'Génération du correctif…',
    ],
  },
  edit_batch: {
    label: 'Écriture ACID',
    steps: [
      'Snapshot WAL…',
      'Application des patches…',
      'Vérification syntaxique…',
      'Commit de la transaction…',
    ],
  },
};

const DEFAULT_PHASE = { label: 'Traitement', steps: ['En cours…'] };

interface Props {
  tool?:  string;
  mode?:  'full' | 'inline';   // défaut : 'full'
}

export function StreamingIndicator({ tool, mode = 'full' }: Props) {
  const phase = (tool && TOOL_PHASES[tool]) ?? DEFAULT_PHASE;

  const [elapsed,  setElapsed]  = useState(0);
  const [stepIdx,  setStepIdx]  = useState(0);
  const [stepKey,  setStepKey]  = useState(0);   // force re-animation

  useEffect(() => {
    const t = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const t = setInterval(() => {
      setStepIdx(i => (i + 1) % phase.steps.length);
      setStepKey(k => k + 1);
    }, 3000);
    return () => clearInterval(t);
  }, [phase.steps.length]);

  const currentStep = phase.steps[stepIdx];

  // ── Mode inline : pastille compacte sous le texte en cours ───────────────
  if (mode === 'inline') {
    return (
      <div className="si-inline" aria-label={`${phase.label} en cours — ${elapsed}s`}>
        <span className="si-orb si-orb-1" />
        <span className="si-orb si-orb-2" />
        <span className="si-orb si-orb-3" />
        <span className="si-inline-label">
          {phase.label}
          <span className="si-inline-sep">·</span>
          <span className="si-inline-timer">{elapsed}s</span>
        </span>
      </div>
    );
  }

  // ── Mode full : bulle complète (pré-streaming) ────────────────────────────
  return (
    <div
      className="si-full"
      aria-label={`${phase.label} — ${elapsed}s — ${currentStep}`}
      aria-live="polite"
    >
      {/* Orbes qui pulsent en cascade */}
      <div className="si-orbs" aria-hidden="true">
        <span className="si-orb si-orb-1" />
        <span className="si-orb si-orb-2" />
        <span className="si-orb si-orb-3" />
      </div>

      {/* Corps */}
      <div className="si-body">
        <span className="si-label">{phase.label}</span>
        <span className="si-step" key={stepKey}>{currentStep}</span>
      </div>

      {/* Timer */}
      <span className="si-timer" aria-hidden="true">{elapsed}s</span>
    </div>
  );
}
