# -*- coding: utf-8-sig -*-
"""
ollama_client.py — REFACTO-11
Extrait de llm_generator.py : client HTTP vers Ollama.

Responsabilité unique : communication HTTP avec l'API Ollama via urllib.request.
  - is_available() : ping /api/tags
  - warmup()       : pré-charge le modèle en VRAM (V9-06)
  - generate()     : /api/generate streaming
  - generate_stream() : /api/generate streaming avec callback on_token (UI-07)
  - chat()         : /api/chat avec historique (NO-TIMEOUT)
  - chat_stream()  : /api/chat streaming avec callback on_token

NO-TIMEOUT : self.timeout = None -> urllib.urlopen(timeout=None) = attente infinie.
Le socket reste ouvert grâce au streaming token par token.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Callable, Optional

from core.llm_config import _log_metric, cfg_read

log = logging.getLogger("lcca.ollama_client")


# ── Helpers internes (mutualisés) ────────────────────────────────────────────

def _build_request(url: str, payload: dict) -> urllib.request.Request:
    """Construit un Request POST JSON encodé UTF-8."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )


def _stream_lines(resp) -> "Generator[dict, None, None]":
    """Itère sur les lignes d'une réponse streaming Ollama et retourne des chunks JSON parsés."""
    for raw_line in resp:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _capture_tps(chunk: dict, model: str, extra: dict | None = None) -> None:
    """Lit eval_count/eval_duration dans un chunk done:True et logue le tok/s via _log_metric."""
    eval_count  = chunk.get("eval_count", 0)
    eval_dur_ns = chunk.get("eval_duration", 0)
    if eval_count and eval_dur_ns:
        tps = eval_count / (eval_dur_ns / 1_000_000_000)
        labels = {"model": model, "eval_count": eval_count}
        if extra:
            labels.update(extra)
        _log_metric("llm_tokens_per_sec", round(tps, 2), labels)
        log.info(
            "Ollama done — model=%s eval_count=%d tps=%.2f",
            model, eval_count, tps,
        )


class OllamaClient:
    """
    Client HTTP minimal vers l'API Ollama (urllib.request uniquement).

    NO-TIMEOUT : self.timeout = None -> urllib.urlopen(timeout=None) = attente infinie.
    """

    def __init__(
        self,
        base_url:   str,
        model:      str,
        timeout:    Optional[int],
        max_tokens: int,
        keep_alive: str = "5m",
    ) -> None:
        self.base_url   = base_url.rstrip("/")
        self.model      = model
        self.timeout    = timeout
        self.max_tokens = max_tokens
        self.keep_alive = keep_alive

    def _ollama_options(self) -> dict:
        """V9-01-A : options GPU/threads/mmap lues depuis config."""
        return {
            "num_predict": self.max_tokens,
            "num_thread":  cfg_read("OLLAMA_THREADS", 4),
            "num_gpu":     cfg_read("OLLAMA_NUM_GPU", 0),
            "use_mmap":    cfg_read("OLLAMA_MMAP", True),
        }

    def warmup(self) -> None:
        """
        V9-06 : Pré-charge le modèle dans la VRAM via un prompt vide.
        Silencieux — ne lève jamais d'exception.
        """
        try:
            url = f"{self.base_url}/api/generate"
            payload = {
                "model":      self.model,
                "prompt":     "",
                "stream":     False,
                "keep_alive": self.keep_alive,
                "options":    {"num_predict": 1},
            }
            data = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
            log.info("Ollama warmup OK -- model=%s keep_alive=%s", self.model, self.keep_alive)
        except Exception as exc:
            log.debug("Ollama warmup silencieux : %s", exc)

    def is_available(self) -> bool:
        try:
            url = f"{self.base_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status != 200:
                    return False
                data   = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(self.model in m for m in models)
        except Exception:
            return False

    def chat(self, system: str, history: list[dict]) -> str:
        """
        /api/chat avec historique conversationnel.
        stream:True maintient le socket actif token par token (NO-TIMEOUT).
        """
        url      = f"{self.base_url}/api/chat"
        messages = [{"role": "system", "content": system}] + history
        payload  = {
            "model":      self.model,
            "messages":   messages,
            "stream":     True,
            "keep_alive": self.keep_alive,
            "options":    self._ollama_options(),
        }
        req = _build_request(url, payload)
        try:
            full_response = []
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for chunk in _stream_lines(resp):
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        full_response.append(token)
                    if chunk.get("done"):
                        _capture_tps(chunk, self.model)
                        break
            return "".join(full_response)
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Ollama inaccessible ({self.base_url}): {exc}") from exc
        except (KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("Reponse Ollama /api/chat malformee") from exc

    def chat_stream(self, system: str, history: list[dict], on_token: Callable) -> str:
        """
        /api/chat streaming — émet les tokens via on_token(str).
        Retourne la réponse complète assemblée.
        """
        url      = f"{self.base_url}/api/chat"
        messages = [{"role": "system", "content": system}] + history
        payload  = {
            "model":      self.model,
            "messages":   messages,
            "stream":     True,
            "keep_alive": self.keep_alive,
            "options":    self._ollama_options(),
        }
        req = _build_request(url, payload)
        try:
            full_response = []
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for chunk in _stream_lines(resp):
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        full_response.append(token)
                        try:
                            on_token(token)
                        except Exception:
                            pass
                    if chunk.get("done"):
                        break
            return "".join(full_response)
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Ollama inaccessible ({self.base_url}): {exc}") from exc

    def generate(self, system: str, user: str, model_override: Optional[str] = None) -> str:
        """
        /api/generate — stream:True maintient le socket actif (NO-TIMEOUT).
        V9-05 : capture eval_count + eval_duration_ns pour telemetrie tok/s.
        FL-02 : model_override optionnel — local a l'appel, ne mute pas self.model.
        """
        url    = f"{self.base_url}/api/generate"
        model  = model_override or self.model          # FL-02 : local, sans effet de bord
        prompt = f"{system}\n\nUtilisateur: {user}\nAssistant:"
        payload = {
            "model":      model,
            "prompt":     prompt,
            "stream":     True,
            "keep_alive": self.keep_alive,
            "options":    self._ollama_options(),
        }
        req = _build_request(url, payload)
        try:
            full_response = []
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for chunk in _stream_lines(resp):
                    token = chunk.get("response", "")
                    if token:
                        full_response.append(token)
                    if chunk.get("done"):
                        _capture_tps(chunk, model)   # FL-02 : utilise model local
                        break
            return "".join(full_response)
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Ollama inaccessible ({self.base_url}): {exc}") from exc
        except (KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError("Reponse Ollama malformee") from exc

    def generate_stream(self, system: str, user: str, on_token: Callable) -> str:
        """
        UI-07 : streaming réel via Ollama stream:true.
        Appelle on_token(token: str) pour chaque fragment reçu.
        V9-06 : telemetrie tok/s depuis le chunk done:true.
        """
        url    = f"{self.base_url}/api/generate"
        prompt = f"{system}\n\nUtilisateur: {user}\nAssistant:"
        payload = {
            "model":      self.model,
            "prompt":     prompt,
            "stream":     True,
            "keep_alive": self.keep_alive,
            "options":    self._ollama_options(),
        }
        req = _build_request(url, payload)
        try:
            full_response = []
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for chunk in _stream_lines(resp):
                    token = chunk.get("response", "")
                    if token:
                        full_response.append(token)
                        try:
                            on_token(token)
                        except Exception:
                            pass
                    if chunk.get("done"):
                        _capture_tps(chunk, self.model, {"source": "stream"})
                        break
            return "".join(full_response)
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Ollama inaccessible ({self.base_url}): {exc}") from exc
