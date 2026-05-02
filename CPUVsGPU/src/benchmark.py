"""
benchmark.py — Moteur principal de benchmark
Lance les tests, mesure les performances, retourne les résultats
"""
import json
import time
import urllib.request
import urllib.error
from typing import Optional
from src.metrics import MetricsCollector
from src.prompts import PROMPTS, get_quick_prompts

# ─── Configuration ────────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434"
RUNS_PER_PROMPT = 3      # Nombre de fois qu'on teste chaque prompt
WARMUP_RUNS = 1          # Run de chauffe (ignore dans les stats)
TIMEOUT_S = 600          # Timeout par inference (10 min -- 14B hybride CPU/GPU ~1-3 tok/s)

# ─── Fonctions utilitaires ─────────────────────────────────────────────────────

def get_available_model() -> Optional[str]:
    """Retourne le premier modèle disponible dans Ollama"""
    try:
        req = urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5)
        data = json.loads(req.read().decode())
        models = data.get("models", [])
        if models:
            return models[0]["name"]
    except Exception:
        pass
    return None

def run_inference(model: str, prompt: str) -> dict:
    """
    Lance une inférence et retourne les métriques Ollama.
    
    Retourne un dict avec :
    - response       : texte généré
    - tokens_out     : nombre de tokens générés
    - tok_per_sec    : tokens par seconde (métrique principale)
    - ttft_s         : Time To First Token (latence perçue)
    - total_s        : durée totale
    - prompt_tok_s   : vitesse d'évaluation du prompt
    - error          : message d'erreur (si échec)
    """
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 512,   # Max tokens à générer
            "temperature": 0.1    # Reproductibilité maximale
        }
    }).encode()
    
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        
        t_start = time.time()
        response = urllib.request.urlopen(req, timeout=TIMEOUT_S)
        t_end = time.time()
        
        data = json.loads(response.read().decode())
        
        # Métriques Ollama (en nanosecondes → converties en secondes)
        eval_count    = data.get("eval_count", 0)
        eval_duration = data.get("eval_duration", 1) / 1e9
        load_duration = data.get("load_duration", 0) / 1e9
        prompt_eval_c = data.get("prompt_eval_count", 0)
        prompt_eval_d = data.get("prompt_eval_duration", 1) / 1e9
        total_dur     = data.get("total_duration", 0) / 1e9
        
        tok_per_sec   = eval_count / max(eval_duration, 0.001)
        prompt_tok_s  = prompt_eval_c / max(prompt_eval_d, 0.001)
        
        return {
            "response"    : data.get("response", "")[:200],  # Tronqué pour le rapport
            "tokens_out"  : eval_count,
            "tok_per_sec" : round(tok_per_sec, 2),
            "ttft_s"      : round(load_duration, 3),
            "total_s"     : round(total_dur, 3),
            "prompt_tok_s": round(prompt_tok_s, 2),
            "error"       : None
        }
        
    except urllib.error.URLError as e:
        return {"error": f"Réseau : {e}", "tok_per_sec": 0}
    except Exception as e:
        return {"error": str(e), "tok_per_sec": 0}

# ─── Benchmark principal ───────────────────────────────────────────────────────

def run_benchmark(mode: str, quick: bool = False, model: Optional[str] = None) -> dict:
    """
    Lance le benchmark complet pour un mode donne.

    mode  : "cpu", "gpu", ou "hybrid"
    quick : True = 2 prompts au lieu de 6, 1 run au lieu de 3
    model : force un modele specifique (ex: "qwen2.5-coder:3b").
            Si None, utilise le premier modele disponible (comportement original).

    Retourne un dict avec tous les resultats.
    """
    print(f"\n{'='*55}")
    print(f"  BENCHMARK MODE : {mode.upper()}")
    print(f"{'='*55}")

    active_model = model or get_available_model()
    if not active_model:
        print("  Aucun modele Ollama disponible !")
        return {"mode": mode, "error": "Aucun modele disponible", "results": []}

    print(f"  Modele : {active_model}")

    prompts_to_test = get_quick_prompts() if quick else PROMPTS
    runs = 1 if quick else RUNS_PER_PROMPT

    print(f"  Prompts : {len(prompts_to_test)} | Runs/prompt : {runs}")
    print(f"  Mode rapide : {'Oui' if quick else 'Non'}\n")

    # Warmup
    print("  Warmup (chargement modele en memoire)...")
    warmup_result = run_inference(active_model, "Dis bonjour en une phrase.")
    if warmup_result.get("error"):
        print(f"  Warmup echoue : {warmup_result['error']}")
    else:
        print(f"  Warmup OK ({warmup_result['tok_per_sec']} tok/s)")
    
    all_results = []
    collector = MetricsCollector(interval_ms=500)

    for prompt_info in prompts_to_test:
        pid    = prompt_info["id"]
        label  = prompt_info["label"]
        prompt = prompt_info["prompt"]

        print(f"\n  [{label}]")
        run_results = []

        for run_num in range(1, runs + 1):
            print(f"     Run {run_num}/{runs}...", end=" ", flush=True)

            collector.start()
            result = run_inference(active_model, prompt)
            summary = collector.stop()
            metrics_dict = collector.to_dict(summary)

            if result.get("error"):
                print(f"ERREUR {result['error']}")
            else:
                print(f"OK {result['tok_per_sec']} tok/s | CPU {metrics_dict.get('cpu_avg', 0):.0f}%", end="")
                if "gpu_avg" in metrics_dict:
                    print(f" | GPU {metrics_dict['gpu_avg']:.0f}%", end="")
                print()
            
            run_results.append({
                "run": run_num,
                "inference": result,
                "system": metrics_dict
            })
        
        # Calculer la moyenne des runs
        valid_runs = [r for r in run_results if not r["inference"].get("error")]
        if valid_runs:
            avg_tok_s = sum(r["inference"]["tok_per_sec"] for r in valid_runs) / len(valid_runs)
            avg_total = sum(r["inference"]["total_s"] for r in valid_runs) / len(valid_runs)
        else:
            avg_tok_s = 0
            avg_total = 0
        
        all_results.append({
            "prompt_id"  : pid,
            "prompt_label": label,
            "avg_tok_s"  : round(avg_tok_s, 2),
            "avg_total_s": round(avg_total, 3),
            "runs"       : run_results
        })
    
    valid_avgs = [r["avg_tok_s"] for r in all_results if r["avg_tok_s"] > 0]
    overall_avg = sum(valid_avgs) / len(valid_avgs) if valid_avgs else 0

    print(f"\n  {'-'*45}")
    print(f"  Moyenne globale : {overall_avg:.2f} tok/s")
    print(f"  {'-'*45}")

    return {
        "mode"             : mode,
        "model"            : active_model,
        "overall_avg_tok_s": round(overall_avg, 2),
        "prompt_count"     : len(prompts_to_test),
        "runs_per_prompt"  : runs,
        "results"          : all_results,
        "timestamp"        : time.strftime("%Y-%m-%d %H:%M:%S")
    }
