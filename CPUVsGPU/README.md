# 📊 CPUVsGPU — Benchmark Ollama

Teste les performances d'Ollama en mode **CPU**, **GPU** et **Hybride** sur ton Lenovo P50.

## 🚀 Démarrage rapide

### 1. Installation (une seule fois)
```powershell
cd D:\LLMCodeAgent\CPUVsGPU
.\setup.ps1
```

### 2. Diagnostic (vérifie que tout est OK)
```powershell
.\.venv\Scripts\python src\diag.py
```

### 3. Benchmark rapide (test de 2 min)
```powershell
.\run_benchmark.ps1 -Quick
```

### 4. Benchmark complet (15-30 min)
```powershell
.\run_benchmark.ps1
```

---

## 📖 Comment configurer chaque mode

Le script `run_benchmark.ps1` t'explique tout, mais voici le résumé :

### Mode CPU (désactive le GPU)
```powershell
# Dans une nouvelle fenêtre PowerShell :
$env:CUDA_VISIBLE_DEVICES="-1"
ollama serve
```

### Mode GPU (GPU uniquement)
```powershell
# Ferme l'ancienne instance, puis :
$env:CUDA_VISIBLE_DEVICES="0"
ollama serve
```

### Mode Hybride (CPU + GPU)
```powershell
# Ferme l'ancienne instance, puis :
Remove-Item Env:CUDA_VISIBLE_DEVICES -ErrorAction SilentlyContinue
$env:OLLAMA_NUM_GPU="999"
ollama serve
```

---

## 📁 Structure des fichiers

```
CPUVsGPU/
├── setup.ps1           → Installation (lancer une fois)
├── run_benchmark.ps1   → Lanceur principal
├── src/
│   ├── diag.py         → Diagnostic avant benchmark
│   ├── benchmark.py    → Moteur de test
│   ├── metrics.py      → Collecte CPU/GPU/RAM
│   ├── prompts.py      → 6 prompts de test
│   ├── report.py       → Génération rapport HTML
│   └── main.py         → Point d'entrée Python
└── results/            → Rapports HTML + JSON (créé automatiquement)
```

---

## 🎯 Ce que mesure le benchmark

| Métrique | Description |
|----------|-------------|
| **tok/s** | Tokens générés par seconde (+ = mieux) |
| **TTFT** | Time To First Token — latence perçue |
| **CPU %** | Utilisation processeur pendant l'inférence |
| **GPU %** | Utilisation GPU NVIDIA |
| **VRAM** | Mémoire GPU consommée |
| **Temp.** | Température GPU |
