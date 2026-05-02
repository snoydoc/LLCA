"""
main.py — Point d'entrée principal du benchmark
Lance les 3 modes et génère le rapport final
"""
import sys
import os
import json
import time
import argparse

# Ajouter le dossier parent au path Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from src.benchmark import run_benchmark
from src.report import generate_report

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")

def save_json(data: dict, filename: str):
    """Sauvegarde les résultats bruts en JSON"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Resultats sauvegardes : {path}")
    return path

def main():
    parser = argparse.ArgumentParser(description="Benchmark Ollama CPU vs GPU")
    parser.add_argument("--mode", choices=["cpu", "gpu", "hybrid", "all"],
                        default="all", help="Mode a tester")
    parser.add_argument("--quick", action="store_true",
                        help="Test rapide (2 prompts, 1 run)")
    parser.add_argument("--model", default=None,
                        help="Forcer un modele specifique (ex: qwen2.5-coder:3b)")
    args = parser.parse_args()
    
    print("\n" + "=" * 57)
    print("  BENCHMARK OLLAMA CPU vs GPU".center(57))
    print("=" * 57)
    print(f"  Mode     : {args.mode.upper()}")
    print(f"  Rapide   : {'Oui (2 prompts)' if args.quick else 'Non (6 prompts)'}")
    print("=" * 57)
    
    modes_to_run = ["cpu", "gpu", "hybrid"] if args.mode == "all" else [args.mode]
    all_results = []
    
    for mode in modes_to_run:
        if args.model is None:
            # Mode interactif : Ollama doit etre prepare manuellement pour chaque mode
            print(f"\n  ATTENTION : Ce script suppose qu'Ollama est deja")
            print(f"  demarre dans le bon mode ({mode.upper()}).")
            print(f"  Appuie sur ENTREE pour lancer le test {mode.upper()}, ou Ctrl+C pour annuler.")
            try:
                input()
            except KeyboardInterrupt:
                print("\nBenchmark annule.")
                sys.exit(0)
        
        result = run_benchmark(mode=mode, quick=args.quick, model=args.model)
        all_results.append(result)
        
        # Sauvegarder les résultats de ce mode
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        save_json(result, f"benchmark_{mode}_{timestamp}.json")
    
    # ── Rapport final ──────────────────────────────────────────────────────────
    if len(all_results) > 0:
        print("\n\n" + "=" * 57)
        print("  GENERATION DU RAPPORT".center(57))
        print("=" * 57)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        report_path = os.path.join(RESULTS_DIR, f"rapport_{timestamp}.html")
        
        generate_report(all_results, report_path)
        print(f"\n  Rapport genere : {report_path}")
        
        # Sauvegarder aussi le JSON combiné
        save_json({"runs": all_results}, f"combined_{timestamp}.json")
        
        # Afficher le résumé final
        print("\n" + "=" * 57)
        print("  RESUME FINAL".center(57))
        print("=" * 57)
        for r in all_results:
            mode = r["mode"]
            score = r.get("overall_avg_tok_s", 0)
            print(f"  {mode.upper():8s} : {score:6.2f} tok/s")
        
        best = max(all_results, key=lambda x: x.get("overall_avg_tok_s", 0))
        print(f"\n  Meilleur mode : {best['mode'].upper()} ({best['overall_avg_tok_s']} tok/s)")
        
        # Ouvrir le rapport dans le navigateur
        try:
            import webbrowser
            webbrowser.open(f"file:///{os.path.abspath(report_path)}")
            print(f"  Rapport ouvert dans le navigateur")
        except Exception:
            print(f"  Ouvre manuellement : {report_path}")

if __name__ == "__main__":
    main()
