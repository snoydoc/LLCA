"""
diag.py — Diagnostic complet avant benchmark
Vérifie : Python, Ollama, NVIDIA, modèles disponibles
"""
import subprocess
import sys
import json
import urllib.request
import urllib.error
import platform

def titre(texte):
    print(f"\n{'='*50}")
    print(f"  {texte}")
    print('='*50)

def ok(msg):    print(f"  ✅ {msg}")
def err(msg):   print(f"  ❌ {msg}")
def info(msg):  print(f"  ℹ️  {msg}")
def warn(msg):  print(f"  ⚠️  {msg}")

def check_python():
    titre("Python")
    v = sys.version_info
    ok(f"Python {v.major}.{v.minor}.{v.micro}")
    if v.major < 3 or (v.major == 3 and v.minor < 9):
        err("Python 3.9+ recommandé")
    
    modules = ["requests", "psutil", "rich"]
    for m in modules:
        try:
            __import__(m)
            ok(f"Module '{m}' disponible")
        except ImportError:
            warn(f"Module '{m}' manquant — sera installé par setup.ps1")

def check_nvidia():
    titre("NVIDIA GPU")
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 3:
                    ok(f"GPU : {parts[0]}")
                    ok(f"VRAM : {parts[1]}")
                    ok(f"Driver : {parts[2]}")
                    if len(parts) >= 4:
                        ok(f"Compute Capability : {parts[3]}")
        else:
            err("nvidia-smi a échoué")
            info(result.stderr)
    except FileNotFoundError:
        err("nvidia-smi introuvable — NVIDIA drivers non installés ?")
    except subprocess.TimeoutExpired:
        err("nvidia-smi timeout")

def check_ollama():
    titre("Ollama")
    # Vérifier si le processus tourne
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ollama.exe"],
            capture_output=True, text=True
        )
        if "ollama.exe" in result.stdout:
            ok("Processus ollama.exe en cours d'exécution")
        else:
            warn("ollama.exe non détecté dans les processus")
            info("Lance Ollama avant le benchmark")
    except Exception:
        pass

    # Vérifier l'API
    try:
        req = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
        data = json.loads(req.read().decode())
        ok("API Ollama répond sur port 11434")
        
        models = data.get("models", [])
        if models:
            ok(f"{len(models)} modèle(s) disponible(s) :")
            for m in models:
                name = m.get("name", "?")
                size = m.get("size", 0)
                size_gb = size / (1024**3)
                info(f"  → {name} ({size_gb:.1f} GB)")
        else:
            warn("Aucun modèle trouvé — il faut en télécharger un")
            info("Exemple : ollama pull mistral:7b")
            
        return models
    except urllib.error.URLError:
        err("API Ollama inaccessible (port 11434)")
        info("Démarre Ollama : ollama serve")
        return []

def check_models(models):
    titre("Modèles recommandés pour le benchmark")
    
    recommended = ["mistral", "llama", "qwen", "phi", "gemma"]
    found = []
    
    for m in models:
        name = m.get("name", "").lower()
        for r in recommended:
            if r in name:
                found.append(m.get("name"))
                break
    
    if found:
        ok(f"Modèles compatibles trouvés : {', '.join(found)}")
        info(f"Le benchmark utilisera : {found[0]}")
    else:
        warn("Aucun modèle recommandé trouvé")
        info("Télécharge un modèle : ollama pull mistral:7b-instruct")
        info("Ou un modèle léger  : ollama pull phi3:mini")

def test_inference(models):
    titre("Test d'inférence rapide")
    
    if not models:
        warn("Pas de modèle — test ignoré")
        return
    
    model_name = models[0].get("name", "mistral")
    info(f"Test avec : {model_name}")
    info("Envoi d'un prompt court...")
    
    try:
        payload = json.dumps({
            "model": model_name,
            "prompt": "Réponds en 5 mots : Quelle est la capitale de France ?",
            "stream": False
        }).encode()
        
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        
        response = urllib.request.urlopen(req, timeout=60)
        data = json.loads(response.read().decode())
        
        response_text = data.get("response", "").strip()
        tok_s = data.get("eval_count", 0) / max(data.get("eval_duration", 1) / 1e9, 0.001)
        
        ok(f"Réponse : {response_text[:80]}")
        ok(f"Vitesse  : {tok_s:.1f} tokens/seconde")
        
        # Détails techniques
        load_duration = data.get("load_duration", 0) / 1e9
        total_duration = data.get("total_duration", 0) / 1e9
        info(f"Chargement modèle : {load_duration:.2f}s")
        info(f"Durée totale      : {total_duration:.2f}s")
        
    except urllib.error.URLError as e:
        err(f"Erreur réseau : {e}")
    except Exception as e:
        err(f"Erreur : {e}")

def resume():
    titre("RÉSUMÉ & PROCHAINE ÉTAPE")
    print("""
  Si tout est ✅ ci-dessus, tu peux lancer le benchmark :
  
    .\\run_benchmark.ps1 -Mode all
  
  Pour un test rapide (30 secondes) :
  
    .\\run_benchmark.ps1 -Mode cpu -Quick
  
  Si des ❌ apparaissent :
  - Ollama non démarré  → ouvre Ollama depuis le menu démarrer
  - Modèle manquant     → ollama pull mistral:7b-instruct
  - nvidia-smi absent   → réinstalle les drivers NVIDIA
    """)

if __name__ == "__main__":
    print("\n" + "🔍 DIAGNOSTIC CPUVsGPU ".center(52, "="))
    print(f"  OS : {platform.system()} {platform.release()}")
    print(f"  Machine : {platform.node()}")
    
    check_python()
    check_nvidia()
    models = check_ollama()
    check_models(models)
    test_inference(models)
    resume()
