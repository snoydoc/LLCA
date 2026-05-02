# M2000M_LLM_HACK — Utiliser la Quadro M2000M pour l'inférence LLM locale
**Machine cible :** Lenovo ThinkPad P50  
**Auteur :** Claude (session 2026-04-21)  
**Statut :** RECHERCHE — brouillon validé, implémentation à venir  

---

## 1. Contexte & Problème

### Configuration matérielle réelle

| Composant | Détail |
|-----------|--------|
| Ordinateur | Lenovo ThinkPad P50 (20ER) |
| CPU | Intel Core i7-6820HQ (4c/8t, Skylake, 2.7 GHz / 3.6 GHz Turbo) |
| RAM | 24 Go DDR4-2133 MHz |
| SSD | 500 Go |
| GPU dGPU | NVIDIA Quadro M2000M — 4 Go GDDR5 (128-bit, 80 GB/s) |
| GPU iGPU | Intel HD Graphics 530 |
| OS | Windows 11 (supposé) |

### Fiche technique GPU (Quadro M2000M)

| Paramètre | Valeur |
|-----------|--------|
| Architecture | Maxwell (GM107, 28 nm) |
| CUDA Cores | 640 |
| VRAM | 4 Go GDDR5 |
| Bande passante mémoire | 80 GB/s (128-bit) |
| TGP (TDP) | ~55 W |
| Compute Capability CUDA | **5.0** |
| Vulkan | Supporté (via drivers NVIDIA récents) |
| OpenCL | 1.2 |
| Équivalent consumer | GeForce GTX 960M |

### Le problème central

LCCA V9 tourne actuellement en **mode CPU-only** via Ollama.  
La raison : le pipeline Ollama/llama.cpp standard exige **CUDA Compute Capability ≥ 5.2** dans ses builds binaires distribués.  
La M2000M est en **CC 5.0** (Maxwell gen 1) — elle est à 0.2 en dessous du seuil officiel.

**Résultat actuel :** Ollama ignore la GPU, pousse tout sur le CPU i7-6820HQ.  
**Objectif :** Activer l'accélération GPU pour réduire le temps par token de ~3×–5×.

---

## 2. Pourquoi la M2000M est bloquée — Analyse technique

### 2.1 Le seuil CUDA 5.2 dans llama.cpp / Ollama

Les binaires distribués de llama.cpp (et donc Ollama) sont compilés avec :

```cmake
# CMakeLists.txt llama.cpp officiel (extrait)
if (NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
    # 52 == lowest CUDA 12 standard
    # 60 == f16 CUDA intrinsics
    # 61 == integer CUDA intrinsics
    set(CMAKE_CUDA_ARCHITECTURES "52;60;61;70;75;80;86;89;90")
endif()
```

La CC 5.0 (notre M2000M) **n'est pas dans cette liste**. Le binaire précompilé ne peut donc pas exécuter les kernels CUDA sur notre GPU.

### 2.2 Ce que CUDA 12 a changé

CUDA 12 a supprimé le support des GPUs CC ≤ 3.7 (Kepler).  
Les GPUs Maxwell CC 5.0/5.2 **restent supportés par CUDA 12** — c'est uniquement le `CMAKE_CUDA_ARCHITECTURES` par défaut qui omet le `50`.

Issue confirmée dans llama.cpp : [#3501](https://github.com/ggml-org/llama.cpp/issues/3501) —  
des utilisateurs avec exactement la même M2000M et une GTX 960M ont activé le GPU en forçant `CMAKE_CUDA_ARCHITECTURES "50;52;61;70"`.

### 2.3 Capacités manquantes à CC 5.0 vs 6.0+

| Feature | CC 5.0 (M2000M) | CC 6.0+ |
|---------|-----------------|---------|
| fp16 CUDA intrinsics | ❌ | ✅ |
| Integer CUDA intrinsics | ❌ | ✅ (CC 6.1+) |
| Flash Attention CUDA kernels | ❌ (dégradé) | ✅ |
| WMMA (tensor-like) | ❌ | ✅ (CC 7.0+) |
| Quantized GEMM (MMQ) | ✅ partiel | ✅ complet |
| Offload de couches | ✅ | ✅ |

La M2000M peut faire du **layer offload quantisé** (la partie la plus utile pour l'inférence LLM) mais pas les optimisations fp16 avancées. En pratique : accélération réelle mais plus lente qu'une GTX 1060 ou RTX 2070.

---

## 3. Solutions disponibles — Classement par effort/bénéfice

### STRATÉGIE A — Vulkan via Ollama (recommandée, effort = faible)

**Principe :** Ollama supporte expérimentalement le backend Vulkan depuis fin 2024.  
La M2000M supporte Vulkan (les drivers NVIDIA Maxwell incluent Vulkan 1.1/1.2).  
Ce backend est indépendant de CUDA et contourne entièrement le problème CC 5.0.

**Statut :** Feature expérimentale, `OLLAMA_VULKAN=1` requis manuellement.

**Procédure Windows :**

```powershell
# 1. Vérifier que Vulkan est dispo sur la M2000M
# Installer VulkanInfo (inclus dans le Vulkan SDK ou GPU-Z)
vulkaninfo --summary
# Chercher : "apiVersion" >= 1.1.xxx

# 2. Démarrer Ollama avec Vulkan activé
$env:OLLAMA_VULKAN = "1"
$env:GGML_VK_VISIBLE_DEVICES = "0"   # forcer GPU 0 (M2000M)
# Tuer l'instance Ollama existante d'abord
Get-Process -Name ollama -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2
ollama serve

# 3. Vérifier que la GPU est détectée
# Dans les logs Ollama (stderr) chercher :
# inference compute" library=Vulkan name=Vulkan0 description="NVIDIA Quadro M2000M"
```

**Mettre à jour start-ollama.ps1 :**

```powershell
# scripts/start-ollama.ps1 — version GPU-aware
$env:OLLAMA_VULKAN = "1"
$env:GGML_VK_VISIBLE_DEVICES = "0"
$env:OLLAMA_DEBUG = "INFO"    # pour voir si GPU est utilisé
Start-Process ollama -ArgumentList "serve" -NoNewWindow
Write-Host "Ollama démarré — Vulkan activé sur Quadro M2000M"
```

**Limitations Vulkan sur M2000M :**
- Pas de Flash Attention via Vulkan (contexte limité, plus de VRAM consommée)
- Bande passante 128-bit (80 GB/s) = goulot d'étranglement vs 256-bit moderne
- Vitesse estimée : 3–6 tok/s sur un modèle 3B Q4_K_M (vs 1–2 tok/s CPU-only)

---

### STRATÉGIE B — Compiler llama.cpp avec CC 5.0 (effort = moyen)

**Principe :** Compiler llama.cpp depuis les sources en forçant `CMAKE_CUDA_ARCHITECTURES=50`.  
Remplcer le binaire llama-server qu'Ollama embarque.

**Prérequis :**
- Visual Studio 2022 Build Tools (C++ Desktop)
- CUDA Toolkit 11.8 ou 12.x (tous deux supportent CC 5.0)
- CMake ≥ 3.25
- Git

**Commandes build (PowerShell) :**

```powershell
# 1. Cloner llama.cpp
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp

# 2. Build CUDA avec CC 5.0 forcé
cmake -B build `
    -DGGML_CUDA=ON `
    -DCMAKE_CUDA_ARCHITECTURES="50;52;61;70;75;80;86" `
    -DCMAKE_BUILD_TYPE=Release `
    -G "Visual Studio 17 2022"

cmake --build build --config Release --parallel 8

# 3. Tester
.\build\bin\Release\llama-cli.exe `
    -m "C:\path\to\model.gguf" `
    --n-gpu-layers 32 `
    -p "Bonjour" -n 50
# Chercher dans la sortie : "ggml_cuda_init: found 1 CUDA devices"
```

**Alternative — llama-cpp-python avec CC 5.0 (pour intégration Python LCCA) :**

```powershell
# Variables d'environnement avant pip install
$env:CMAKE_ARGS = "-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=50"
$env:FORCE_CMAKE = "1"

.\venv\Scripts\Activate.ps1
pip install llama-cpp-python --upgrade --force-reinstall --no-cache-dir
```

**Note importante — CUDA Toolkit à installer :**  
CUDA 12.x est compatible CC 5.0 pour la compilation (contrairement à ce que disent certaines docs).  
Si problème, rétrograder à CUDA 11.8 qui supporte CC 5.0 nativement.

---

### STRATÉGIE C — Hybrid offload (GPU partiel + RAM) via llama.cpp

**Principe :** Avec 4 Go VRAM et 24 Go RAM, on peut placer les premières N couches sur GPU et le reste sur CPU.  
La VRAM accélère le goulot des premières couches (embedding + premières attentions).

```powershell
# Avec llama-cli compilé (Stratégie B) ou via Ollama custom
# Régler --n-gpu-layers = nombre de couches qui tiennent en 4 Go VRAM

# Pour un modèle 7B Q4_K_M (~4.1 Go total) :
# Essayer 20–28 couches sur GPU (selon overhead)
llama-cli.exe `
    -m model-7b-q4_k_m.gguf `
    --n-gpu-layers 20 `
    -c 2048 `
    -p "Test" -n 100

# Pour un modèle 3B Q4_K_M (~1.9 Go total) :
# Toutes les couches sur GPU
llama-cli.exe `
    -m model-3b-q4_k_m.gguf `
    --n-gpu-layers 99 `
    -c 4096 `
    -p "Test" -n 100
```

**Modèle Ollama pour layers custom (si Vulkan non-dispo) :**

```
# Dans le Modelfile Ollama
FROM codellama:7b-instruct-q4_K_M
PARAMETER num_gpu 20
PARAMETER num_ctx 2048
```

---

### STRATÉGIE D — Utiliser la iGPU Intel HD 530 en complément

**Principe :** L'Intel HD 530 est une iGPU Skylake qui partage la RAM système.  
Via le BIOS P50 (Config → Display → Discrete Only), on désactive l'Optimus et on force la M2000M.  
Alternativement, en mode Hybrid, l'iGPU peut être utilisé pour certains kernels légers.

**Limitation :** L'HD 530 n'a pas d'accélération LLM notable. Utile seulement pour libérer la M2000M de l'affichage dans les configurations dual-GPU.

**Action BIOS recommandée :**

```
ThinkPad P50 BIOS → Config → Display
  Graphics Mode : Hybrid (défaut) → Discrete Only
  
Avantage : La M2000M n'est plus partagée avec l'affichage
           → ~200–300 Mo de VRAM libérés pour l'inférence
```

---

## 4. Modèles recommandés pour 4 Go VRAM

### Cas A — GPU full offload (toutes les couches en VRAM)

| Modèle | Taille GGUF | Contexte max | Tok/s estimé M2000M |
|--------|-------------|--------------|---------------------|
| `qwen2.5:3b` Q4_K_M | ~1.9 Go | 8k | 5–8 tok/s |
| `codellama:7b` Q4_K_M | ~4.1 Go | 4k | 3–5 tok/s (limite VRAM) |
| `phi3:mini` Q4_K_M | ~2.2 Go | 4k | 5–7 tok/s |
| `deepseek-coder:1.3b` Q4_K_M | ~0.8 Go | 4k | 8–12 tok/s |

### Cas B — Hybrid GPU+CPU (pour modèles > 4 Go)

| Modèle | Taille GGUF | GPU layers | Tok/s estimé |
|--------|-------------|-----------|--------------|
| `codellama:7b` Q4_K_M | 4.1 Go | 20/32 | 2–4 tok/s |
| `qwen2.5:7b` Q4_K_M | 4.4 Go | 18/28 | 2–4 tok/s |
| `deepseek-coder:6.7b` Q4_K_M | 3.8 Go | 28/32 | 4–6 tok/s |

### Modèle recommandé pour LCCA (coding agent)

**`qwen2.5-coder:3b-instruct` Q4_K_M** — tient entièrement en VRAM, excellent sur les tâches de code, ~5–8 tok/s attendus vs ~1–2 tok/s actuellement en CPU-only.

---

## 5. Impact sur config.py (LCCA V9)

```python
# config.py — ajouts pour profil GPU M2000M
# À activer après validation de la Stratégie A ou B

# GPU
GPU_ENABLED = True          # False par défaut → passer à True après hack
GPU_BACKEND = "vulkan"      # "cuda_50" | "vulkan" | "cpu"
GPU_LAYERS = -1             # -1 = auto (toutes les couches si VRAM suffisante)
                            # 20 = hybrid pour modèles 7B
VRAM_GB = 4                 # détecté par hardware_profile.py

# Modèles recommandés selon GPU
GPU_MODEL_DEFAULT = "qwen2.5-coder:3b-instruct"
GPU_MODEL_FALLBACK = "codellama:7b-instruct-q4_K_M"   # hybrid

# hardware_profile.py — tiers à adapter
# Actuellement : low = RAM < 24 Go → pool=2, pyttsx3, ttl=300
# Avec GPU : mid tier même si RAM = 24 Go (GPU compense)
```

---

## 6. Intégration dans hardware_profile.py (V9)

Le module `core/hardware_profile.py` (V9-00) détecte la RAM mais pas le GPU.  
À étendre pour détecter la VRAM et choisir le bon tier :

```python
# core/hardware_profile.py — extension GPU (SPRINT FUTUR V9-GPU-01)

def detect_vram_gb() -> int:
    """Détecte la VRAM disponible via nvidia-smi ou pynvml."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            return int(result.stdout.strip()) // 1024  # MiB → GiB
    except Exception:
        pass
    return 0  # fallback : pas de GPU détecté

def get_gpu_backend() -> str:
    """Retourne le backend GPU optimal selon la config."""
    import os
    if os.environ.get("OLLAMA_VULKAN") == "1":
        return "vulkan"
    vram = detect_vram_gb()
    if vram >= 4:
        return "cuda_50"   # si compilé avec CC 5.0
    return "cpu"
```

---

## 7. Plan d'action recommandé (ordre de priorité)

### Phase 1 — Test Vulkan immédiat (30 min)

```
[ ] 1. Vérifier Vulkan disponible : vulkaninfo --summary | grep apiVersion
[ ] 2. Ajouter OLLAMA_VULKAN=1 dans start-ollama.ps1
[ ] 3. Redémarrer Ollama
[ ] 4. Vérifier logs : grep "Vulkan" dans stderr Ollama
[ ] 5. Tester : ollama run qwen2.5-coder:3b → mesurer tok/s
[ ] 6. Comparer avec baseline CPU-only (noter les tok/s avant/après)
```

**Commande de mesure :**
```powershell
# Benchmark rapide avant/après
$start = Get-Date
ollama run qwen2.5-coder:3b "écris une fonction Python qui trie une liste"
$elapsed = (Get-Date) - $start
Write-Host "Temps : $($elapsed.TotalSeconds)s"
# → calculer manuellement le nb tokens / secondes
```

### Phase 2 — Si Vulkan ne fonctionne pas : Build llama.cpp CC 5.0 (2–4h)

```
[ ] 1. Installer CUDA Toolkit 12.x (ou 11.8)
[ ] 2. Installer Visual Studio 2022 Build Tools (C++ Desktop)
[ ] 3. Installer CMake 3.25+
[ ] 4. Cloner llama.cpp
[ ] 5. Build avec CMAKE_CUDA_ARCHITECTURES="50;52;61;70"
[ ] 6. Tester llama-cli.exe avec --n-gpu-layers 99
[ ] 7. Si OK : remplacer le runner Ollama ou utiliser llama-server directement
```

### Phase 3 — Sprint V9-GPU-01 (LCCA intégration)

```
[ ] 1. Étendre hardware_profile.py : detect_vram_gb() + get_gpu_backend()
[ ] 2. Mettre à jour config.py : GPU_ENABLED, GPU_BACKEND, GPU_LAYERS
[ ] 3. Mettre à jour start-ollama.ps1 avec variables d'environnement GPU
[ ] 4. Mettre à jour 004-sprint-context.md : marquer V9-GPU-01 planifié
[ ] 5. Écrire tests/test_hardware_profile_gpu.py (5 nouveaux tests)
```

---

## 8. Risques & limitations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Vulkan instable sur Maxwell Windows | Moyenne | Rollback CPU | Variable d'env désactivable |
| 4 Go VRAM insuffisants pour 7B full offload | Haute | Hybrid mode | Réduire ctx ou couches GPU |
| Overhead Optimus (Hybrid Graphics) | Moyenne | -10% perf | Mode Discrete BIOS |
| Chaleur CPU+GPU prolongée (laptop) | Moyenne | Throttling | Limiter tok/s max, refroidissement |
| llama.cpp CC 5.0 build cassé par update | Faible | Rebuild requis | Épingler version git tag |

---

## 9. Références

- Issue llama.cpp #3501 — Maxwell CC 5.0 support : https://github.com/ggml-org/llama.cpp/issues/3501
- Ollama GPU support officiel (Vulkan) : https://docs.ollama.com/gpu
- eGPU P50 + Vulkan AMD RX 5700 XT : https://egpu.io/forums/builds/...
- NotebookCheck M2000M : https://www.notebookcheck.net/NVIDIA-Quadro-M2000M.151581.0.html
- VRAM requirements local LLMs : https://localllm.in/blog/ollama-vram-requirements-for-local-llms
- Ollama Vulkan Windows (AMD APU) : https://www.binwh.com/en/2026/04/12/vulkan-ollama-amd-gpu/

---

## 10. Notes de session

- Recherche effectuée le 2026-04-21
- La CC 5.0 est **techniquement supportée** par CUDA 12 — c'est uniquement le CMakeLists.txt par défaut qui l'omet
- La Vulkan route est plus rapide à tester et ne nécessite pas de compilation
- La M2000M a 640 CUDA cores et 80 GB/s de bande passante — pas négligeable pour un 3B Q4_K_M
- Le hardware_profile V9-00 devra être étendu en V9-GPU-01 pour intégrer ces informations
- SPRINT À PLANIFIER : `V9-GPU-01` dans `004-sprint-context.md`

---

*Fichier généré par Claude — session LCCA V9 — 2026-04-21*  
*Mettre à jour après validation de la Phase 1 (Vulkan)*
