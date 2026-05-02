# Rapport Benchmark Ollama - V9.1-Dev
**Mode :** GPU  
**Profil :** Dev  
**Date :** 2026-04-29 23:09  
**Duree :** 1h 26m 40s  

## Configuration profil
| Parametre | Valeur |
|-----------|--------|
| RAM_FREE_MIN | 2440 MB |
| OLLAMA_RAM_MAX | 18299 MB |
| Timeout multiplier | x1.5 |
| Kill apps | Non |
| Usage | Test real-world, agent de code actif |

## Classement par vitesse (tok/s moyen)

| Modele | Tier | Tok/s | VRAM (MB) | GPU% | RAM (MB) | Runs | Vides | Tronquees |
|--------|------|-------|-----------|------|----------|------|-------|-----------|
| qwen2.5-coder:3b | GPU | 10.9 | 2259 | 94 | 5218 | 3 | 0 | 0 |
| gemma4:e2b | GPU | 9.3 | 2157 | 68 | 11565 | 3 | 0 | 0 |
| qwen3:4b | GPU | 8.3 | 2865 | 74 | 6130 | 3 |  |  |
| gemma3:4b | GPU | 8 | 2381 | 58 | 7344 | 3 | 0 | 0 |
| phi4-mini-reasoning:latest | GPU | 6 | 3997 | 38 | 9281 | 3 | 0 | 0 |
| gemma4:e4b | GPU | 5.8 | 2994 | 61 | 14352 | 3 | 0 | 0 |

## Erreurs LLM (1)
- **empty_response** : 1x
  - Suggestion : Model has thinking block: multiply num_predict x4.

## Fichiers generes
- CSV : `D:\LLMCodeAgent\CPUVsGPU\results\bench_gpu_incremental_Dev_GPU.csv`
- Log : `D:\LLMCodeAgent\CPUVsGPU\results\bench_gpu_20260429_2143_Dev.log`
- Erreurs : `D:\LLMCodeAgent\CPUVsGPU\results\llm_errors_20260429_2143_Dev.json`
- Reponses : `D:\LLMCodeAgent\CPUVsGPU\results\responses`

