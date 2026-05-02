# -*- coding: utf-8-sig -*-
"""
evalloop_types.py — Dataclasses EvalLoop V3
Fondations du système : 5 types + to_dict/from_dict.
Pas de logique métier ici — uniquement les structures de données.

INVARIANTS ENCODÉS DANS LES VALEURS PAR DÉFAUT :
  JudgeScore.inject_recommended = False  (JudgeLocal ne décide jamais d'injecter)
  JudgeScore.improved_answer    = ""     (JudgeLocal ne produit jamais de contenu)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── BenchQuestion ─────────────────────────────────────────────────────────────

@dataclass
class BenchQuestion:
    """Une question du curriculum EvalLoop."""
    id:                str
    domain:            str
    palier:            int
    question:          str
    expected_concepts: List[str]
    rubric:            str  = ""
    status:            str  = "active"   # "active" | "draft"
    tags:              List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":                self.id,
            "domain":            self.domain,
            "palier":            self.palier,
            "question":          self.question,
            "expected_concepts": list(self.expected_concepts),
            "rubric":            self.rubric,
            "status":            self.status,
            "tags":              list(self.tags),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BenchQuestion":
        return cls(
            id                = d["id"],
            domain            = d["domain"],
            palier            = int(d["palier"]),
            question          = d["question"],
            expected_concepts = list(d.get("expected_concepts", [])),
            rubric            = d.get("rubric", ""),
            status            = d.get("status", "active"),
            tags              = list(d.get("tags", [])),
        )


# ── ProbeResponse ─────────────────────────────────────────────────────────────

@dataclass
class ProbeResponse:
    """Réponse brute de LCCA à une question (sortie ProbeEngine)."""
    question_id:  str
    question:     BenchQuestion
    response:     str
    model:        str
    duration_sec: float
    timestamp:    str            # ISO 8601 UTC

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id":  self.question_id,
            "question":     self.question.to_dict(),
            "response":     self.response,
            "model":        self.model,
            "duration_sec": self.duration_sec,
            "timestamp":    self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProbeResponse":
        return cls(
            question_id  = d["question_id"],
            question     = BenchQuestion.from_dict(d["question"]),
            response     = d["response"],
            model        = d["model"],
            duration_sec = float(d["duration_sec"]),
            timestamp    = d["timestamp"],
        )


# ── JudgeScore ────────────────────────────────────────────────────────────────

@dataclass
class JudgeScore:
    """Score produit par un juge pour une réponse donnée."""
    question_id:        str
    judge:              str          # "local" | "claude"
    # Scores composants (0.0–1.0)
    concept_score:      float = 0.0
    coherence_score:    float = 0.0
    structure_score:    float = 0.0
    # Score final
    final_score:        float = 0.0
    # Décision injection
    inject_recommended: bool  = False  # INVARIANT JudgeLocal : toujours False
    improved_answer:    str   = ""     # INVARIANT JudgeLocal : toujours ""
    # Contexte
    domain:             str   = ""
    palier:             int   = 0
    # Diagnostics
    strengths:  List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id":        self.question_id,
            "judge":              self.judge,
            "concept_score":      self.concept_score,
            "coherence_score":    self.coherence_score,
            "structure_score":    self.structure_score,
            "final_score":        self.final_score,
            "inject_recommended": self.inject_recommended,
            "improved_answer":    self.improved_answer,
            "domain":             self.domain,
            "palier":             self.palier,
            "strengths":          list(self.strengths),
            "weaknesses":         list(self.weaknesses),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "JudgeScore":
        return cls(
            question_id        = d["question_id"],
            judge              = d["judge"],
            concept_score      = float(d.get("concept_score", 0.0)),
            coherence_score    = float(d.get("coherence_score", 0.0)),
            structure_score    = float(d.get("structure_score", 0.0)),
            final_score        = float(d.get("final_score", 0.0)),
            inject_recommended = bool(d.get("inject_recommended", False)),
            improved_answer    = d.get("improved_answer", ""),
            domain             = d.get("domain", ""),
            palier             = int(d.get("palier", 0)),
            strengths          = list(d.get("strengths", [])),
            weaknesses         = list(d.get("weaknesses", [])),
        )


# ── DistilledSkill ────────────────────────────────────────────────────────────

@dataclass
class DistilledSkill:
    """Entrée prête à être injectée dans MemoryEngine (lcca_context)."""
    question_id:     str
    domain:          str
    palier:          int
    improved_answer: str
    score:           float          # >= 0.70 pour passer _THRESHOLD_CONTEXT=0.6
    dedup_hash:      str            # SHA256[:16] de improved_answer
    judge:           str            # Toujours "claude" en V3
    injected_at:     str = ""       # ISO 8601, rempli après store()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id":     self.question_id,
            "domain":          self.domain,
            "palier":          self.palier,
            "improved_answer": self.improved_answer,
            "score":           self.score,
            "dedup_hash":      self.dedup_hash,
            "judge":           self.judge,
            "injected_at":     self.injected_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DistilledSkill":
        return cls(
            question_id     = d["question_id"],
            domain          = d["domain"],
            palier          = int(d["palier"]),
            improved_answer = d["improved_answer"],
            score           = float(d["score"]),
            dedup_hash      = d["dedup_hash"],
            judge           = d["judge"],
            injected_at     = d.get("injected_at", ""),
        )


# ── PalierState ───────────────────────────────────────────────────────────────

@dataclass
class PalierState:
    """État courant d'un domaine dans eval_state.json."""
    domain:             str
    current_palier:     int   = 0
    questions_done:     int   = 0
    avg_score:          float = 0.0
    unlock_threshold:   float = 0.70
    sessions_completed: int   = 0
    recent_scores:      List[float] = field(default_factory=list)  # Pour SYS-02 (V4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain":             self.domain,
            "current_palier":     self.current_palier,
            "questions_done":     self.questions_done,
            "avg_score":          self.avg_score,
            "unlock_threshold":   self.unlock_threshold,
            "sessions_completed": self.sessions_completed,
            "recent_scores":      list(self.recent_scores),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PalierState":
        return cls(
            domain             = d["domain"],
            current_palier     = int(d.get("current_palier", 0)),
            questions_done     = int(d.get("questions_done", 0)),
            avg_score          = float(d.get("avg_score", 0.0)),
            unlock_threshold   = float(d.get("unlock_threshold", 0.70)),
            sessions_completed = int(d.get("sessions_completed", 0)),
            recent_scores      = list(d.get("recent_scores", [])),
        )
