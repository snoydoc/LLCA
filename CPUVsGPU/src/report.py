"""
report.py — Génère le rapport HTML final avec graphiques
Produit un fichier HTML autonome (pas de dépendances externes)
"""
import json
import os
import time
from typing import List, Optional

def _couleur_mode(mode: str) -> str:
    return {"cpu": "#3B82F6", "gpu": "#10B981", "hybrid": "#F59E0B"}.get(mode, "#6B7280")

def _emoji_mode(mode: str) -> str:
    return {"cpu": "🔵", "gpu": "🟢", "hybrid": "🟡"}.get(mode, "⚪")

def generate_report(benchmark_results: List[dict], output_path: str) -> str:
    """
    Génère un rapport HTML complet.
    
    benchmark_results : liste de dicts retournés par run_benchmark()
    output_path       : chemin du fichier HTML à créer
    
    Retourne le chemin du fichier créé.
    """
    
    # ── Trouver le meilleur mode ───────────────────────────────────────────────
    best_mode = None
    best_score = -1
    for r in benchmark_results:
        if r.get("overall_avg_tok_s", 0) > best_score:
            best_score = r["overall_avg_tok_s"]
            best_mode = r["mode"]
    
    # ── Préparer les données pour les graphiques ───────────────────────────────
    modes      = [r["mode"] for r in benchmark_results]
    avg_tok_s  = [r.get("overall_avg_tok_s", 0) for r in benchmark_results]
    colors     = [_couleur_mode(m) for m in modes]
    
    # Données par prompt (pour le graphique groupé)
    prompt_labels = []
    prompt_datasets = []
    
    if benchmark_results and benchmark_results[0].get("results"):
        prompt_labels = [r["prompt_label"] for r in benchmark_results[0]["results"]]
        for bench in benchmark_results:
            dataset = {
                "label": bench["mode"].upper(),
                "data": [r["avg_tok_s"] for r in bench.get("results", [])],
                "backgroundColor": _couleur_mode(bench["mode"])
            }
            prompt_datasets.append(dataset)
    
    # Données CPU/GPU/VRAM par mode (premier run du premier prompt)
    system_data = {}
    for bench in benchmark_results:
        results = bench.get("results", [])
        if results and results[0].get("runs"):
            sys_metrics = results[0]["runs"][0].get("system", {})
            system_data[bench["mode"]] = sys_metrics
    
    # ── Tableau comparatif ─────────────────────────────────────────────────────
    tableau_rows = ""
    for bench in benchmark_results:
        mode = bench["mode"]
        score = bench.get("overall_avg_tok_s", 0)
        is_best = (mode == best_mode)
        badge = " 🏆" if is_best else ""
        style = 'style="background:#f0fdf4;font-weight:bold"' if is_best else ""
        
        # Métriques système moyennes (premier prompt)
        sys = system_data.get(mode, {})
        cpu_s = f"{sys.get('cpu_avg', '-'):.0f}%" if sys.get('cpu_avg') else "—"
        gpu_s = f"{sys.get('gpu_avg', '-'):.0f}%" if sys.get('gpu_avg') else "—"
        vram_s = f"{sys.get('vram_avg_mb', '-'):.0f} MB" if sys.get('vram_avg_mb') else "—"
        temp_s = f"{sys.get('gpu_temp_avg', '-'):.0f}°C" if sys.get('gpu_temp_avg') else "—"
        
        tableau_rows += f"""
        <tr {style}>
            <td>{_emoji_mode(mode)} {mode.upper()}{badge}</td>
            <td><strong>{score}</strong> tok/s</td>
            <td>{cpu_s}</td>
            <td>{gpu_s}</td>
            <td>{vram_s}</td>
            <td>{temp_s}</td>
        </tr>"""
    
    # ── Recommandation ─────────────────────────────────────────────────────────
    reco_text = f"""
    <div class="reco">
        <h2>🏆 Recommandation</h2>
        <p>Basé sur les benchmarks, le mode <strong>{(best_mode or 'inconnu').upper()}</strong> 
        est le plus performant avec <strong>{best_score:.1f} tokens/seconde</strong> en moyenne.</p>
        {"<p>➡️ Configure Ollama en mode GPU pour tes projets LLM.</p>" if best_mode == "gpu" else ""}
        {"<p>➡️ Le CPU seul suffit — ton GPU n'apporte pas de gain significatif.</p>" if best_mode == "cpu" else ""}
        {"<p>➡️ Le mode hybride CPU+GPU est optimal pour ta configuration.</p>" if best_mode == "hybrid" else ""}
    </div>"""
    
    # ── HTML complet ───────────────────────────────────────────────────────────
    chart_data_json = json.dumps({
        "modes": modes,
        "avg_tok_s": avg_tok_s,
        "colors": colors,
        "prompt_labels": prompt_labels,
        "prompt_datasets": prompt_datasets
    })
    
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rapport Benchmark CPU vs GPU — Ollama</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f8fafc; color: #1e293b; line-height: 1.6; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 2rem; }}
  h1 {{ font-size: 1.8rem; color: #0f172a; margin-bottom: 0.5rem; }}
  .subtitle {{ color: #64748b; margin-bottom: 2rem; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
  .card {{ background: white; border-radius: 12px; padding: 1.5rem;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .card h2 {{ font-size: 1rem; color: #475569; margin-bottom: 1rem; }}
  .chart-full {{ grid-column: 1 / -1; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
  th {{ background: #f1f5f9; padding: 0.75rem 1rem; text-align: left;
        font-weight: 600; color: #475569; }}
  td {{ padding: 0.75rem 1rem; border-bottom: 1px solid #e2e8f0; }}
  .reco {{ background: #fffbeb; border: 2px solid #f59e0b; border-radius: 12px;
           padding: 1.5rem; margin: 2rem 0; }}
  .reco h2 {{ color: #92400e; margin-bottom: 0.75rem; }}
  .meta {{ color: #94a3b8; font-size: 0.8rem; margin-top: 2rem; text-align: center; }}
  canvas {{ max-height: 350px; }}
</style>
</head>
<body>
<div class="container">
  <h1>📊 Rapport Benchmark : CPU vs GPU vs Hybride</h1>
  <p class="subtitle">Ollama — Lenovo P50 NVIDIA | Généré le {time.strftime("%d/%m/%Y à %H:%M")}</p>

  {reco_text}

  <div class="grid">
    <div class="card">
      <h2>⚡ Performance globale (tok/s)</h2>
      <canvas id="chartGlobal"></canvas>
    </div>
    <div class="card">
      <h2>🖥️ Utilisation CPU moyenne (%)</h2>
      <canvas id="chartCPU"></canvas>
    </div>
    <div class="card chart-full">
      <h2>📝 Performance par type de prompt (tok/s)</h2>
      <canvas id="chartPrompts"></canvas>
    </div>
    <div class="card chart-full">
      <h2>📋 Tableau comparatif complet</h2>
      <table>
        <thead>
          <tr>
            <th>Mode</th>
            <th>Vitesse moy.</th>
            <th>CPU moy.</th>
            <th>GPU moy.</th>
            <th>VRAM moy.</th>
            <th>Temp. GPU</th>
          </tr>
        </thead>
        <tbody>{tableau_rows}</tbody>
      </table>
    </div>
  </div>

  <p class="meta">
    Modèle testé : {benchmark_results[0].get('model', 'N/A') if benchmark_results else 'N/A'} |
    Prompts : {benchmark_results[0].get('prompt_count', 0) if benchmark_results else 0} |
    Runs/prompt : {benchmark_results[0].get('runs_per_prompt', 0) if benchmark_results else 0}
  </p>
</div>

<script>
const D = {chart_data_json};

// Graphique 1 : Performance globale
new Chart(document.getElementById('chartGlobal'), {{
  type: 'bar',
  data: {{
    labels: D.modes.map(m => m.toUpperCase()),
    datasets: [{{
      label: 'tok/s',
      data: D.avg_tok_s,
      backgroundColor: D.colors,
      borderRadius: 8
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'tokens/seconde' }} }} }}
  }}
}});

// Graphique 2 : CPU usage
const cpuData = D.modes.map((m, i) => {{
  const benchData = {json.dumps([{"mode": r["mode"], "results": r.get("results", [])} for r in benchmark_results])};
  const bench = benchData.find(b => b.mode === m);
  if (bench && bench.results && bench.results[0] && bench.results[0].runs) {{
    return bench.results[0].runs[0].system.cpu_avg || 0;
  }}
  return 0;
}});

new Chart(document.getElementById('chartCPU'), {{
  type: 'bar',
  data: {{
    labels: D.modes.map(m => m.toUpperCase()),
    datasets: [{{
      label: 'CPU %',
      data: cpuData,
      backgroundColor: D.colors,
      borderRadius: 8
    }}]
  }},
  options: {{
    plugins: {{ legend: {{ display: false }} }},
    scales: {{ y: {{ beginAtZero: true, max: 100, title: {{ display: true, text: '% utilisation' }} }} }}
  }}
}});

// Graphique 3 : Par prompt
new Chart(document.getElementById('chartPrompts'), {{
  type: 'bar',
  data: {{
    labels: D.prompt_labels,
    datasets: D.prompt_datasets.map(ds => ({{
      ...ds,
      borderRadius: 4
    }}))
  }},
  options: {{
    scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: 'tokens/seconde' }} }} }}
  }}
}});
</script>
</body>
</html>"""
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    return output_path
