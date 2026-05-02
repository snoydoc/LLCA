"""
metrics.py — Collecte des métriques système en temps réel
Mesure : CPU%, RAM, GPU%, VRAM, température toutes les 500ms
"""
import threading
import time
import subprocess
import json
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class Sample:
    """Un relevé de métriques à un instant T"""
    timestamp: float
    cpu_percent: float
    ram_used_mb: float
    gpu_percent: Optional[float] = None
    vram_used_mb: Optional[float] = None
    gpu_temp_c: Optional[float] = None

@dataclass  
class MetricsSummary:
    """Résumé statistique d'une série de mesures"""
    cpu_avg: float = 0.0
    cpu_max: float = 0.0
    ram_avg_mb: float = 0.0
    ram_max_mb: float = 0.0
    gpu_avg: Optional[float] = None
    gpu_max: Optional[float] = None
    vram_avg_mb: Optional[float] = None
    vram_max_mb: Optional[float] = None
    gpu_temp_avg: Optional[float] = None
    sample_count: int = 0

def get_nvidia_stats() -> dict:
    """Interroge nvidia-smi pour GPU%, VRAM, température"""
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(',')
            if len(parts) >= 3:
                return {
                    "gpu_percent": float(parts[0].strip()),
                    "vram_used_mb": float(parts[1].strip()),
                    "gpu_temp_c": float(parts[2].strip())
                }
    except Exception:
        pass
    return {}

def get_cpu_ram() -> dict:
    """Mesure CPU% et RAM via psutil"""
    try:
        import psutil
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_used_mb": psutil.virtual_memory().used / (1024 * 1024)
        }
    except ImportError:
        # Fallback sans psutil
        return {"cpu_percent": 0.0, "ram_used_mb": 0.0}

class MetricsCollector:
    """
    Collecteur de métriques en arrière-plan.
    
    Usage :
        collector = MetricsCollector()
        collector.start()
        # ... faire l'inférence ...
        summary = collector.stop()
    """
    
    def __init__(self, interval_ms: int = 500):
        self.interval = interval_ms / 1000.0
        self._samples: List[Sample] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
    
    def start(self):
        """Démarre la collecte en arrière-plan"""
        self._samples = []
        self._running = True
        # Initialiser psutil pour le premier appel (sinon CPU% = 0)
        try:
            import psutil
            psutil.cpu_percent(interval=None)
        except ImportError:
            pass
        time.sleep(0.1)  # Laisser psutil se calibrer
        
        self._thread = threading.Thread(target=self._collect_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> MetricsSummary:
        """Arrête la collecte et retourne le résumé"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        
        with self._lock:
            return self._compute_summary()
    
    def _collect_loop(self):
        """Boucle de collecte (thread arrière-plan)"""
        while self._running:
            sample = self._take_sample()
            with self._lock:
                self._samples.append(sample)
            time.sleep(self.interval)
    
    def _take_sample(self) -> Sample:
        """Prend un relevé instantané"""
        cpu_ram = get_cpu_ram()
        gpu_stats = get_nvidia_stats()
        
        return Sample(
            timestamp=time.time(),
            cpu_percent=cpu_ram.get("cpu_percent", 0.0),
            ram_used_mb=cpu_ram.get("ram_used_mb", 0.0),
            gpu_percent=gpu_stats.get("gpu_percent"),
            vram_used_mb=gpu_stats.get("vram_used_mb"),
            gpu_temp_c=gpu_stats.get("gpu_temp_c")
        )
    
    def _compute_summary(self) -> MetricsSummary:
        """Calcule les statistiques sur tous les relevés"""
        if not self._samples:
            return MetricsSummary()
        
        s = self._samples
        summary = MetricsSummary(sample_count=len(s))
        
        # CPU & RAM
        cpu_vals = [x.cpu_percent for x in s]
        ram_vals = [x.ram_used_mb for x in s]
        summary.cpu_avg = sum(cpu_vals) / len(cpu_vals)
        summary.cpu_max = max(cpu_vals)
        summary.ram_avg_mb = sum(ram_vals) / len(ram_vals)
        summary.ram_max_mb = max(ram_vals)
        
        # GPU (optionnel — seulement si nvidia-smi fonctionne)
        gpu_vals = [x.gpu_percent for x in s if x.gpu_percent is not None]
        vram_vals = [x.vram_used_mb for x in s if x.vram_used_mb is not None]
        temp_vals = [x.gpu_temp_c for x in s if x.gpu_temp_c is not None]
        
        if gpu_vals:
            summary.gpu_avg = sum(gpu_vals) / len(gpu_vals)
            summary.gpu_max = max(gpu_vals)
        if vram_vals:
            summary.vram_avg_mb = sum(vram_vals) / len(vram_vals)
            summary.vram_max_mb = max(vram_vals)
        if temp_vals:
            summary.gpu_temp_avg = sum(temp_vals) / len(temp_vals)
        
        return summary
    
    def to_dict(self, summary: MetricsSummary) -> dict:
        """Convertit le résumé en dictionnaire pour le rapport"""
        d = {
            "cpu_avg": round(summary.cpu_avg, 1),
            "cpu_max": round(summary.cpu_max, 1),
            "ram_avg_mb": round(summary.ram_avg_mb, 1),
            "ram_max_mb": round(summary.ram_max_mb, 1),
            "sample_count": summary.sample_count
        }
        if summary.gpu_avg is not None:
            d["gpu_avg"] = round(summary.gpu_avg, 1)
            d["gpu_max"] = round(summary.gpu_max, 1)
        if summary.vram_avg_mb is not None:
            d["vram_avg_mb"] = round(summary.vram_avg_mb, 1)
            d["vram_max_mb"] = round(summary.vram_max_mb, 1)
        if summary.gpu_temp_avg is not None:
            d["gpu_temp_avg"] = round(summary.gpu_temp_avg, 1)
        return d
