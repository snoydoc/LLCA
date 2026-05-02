# -*- coding: utf-8-sig -*-
"""
make_ico.py — Convertit assets/AdhamDesktop.png en assets/AdhamDesktop.ico.

Usage (depuis D:\\LLMCodeAgent\\ui\\) :
    python make_ico.py

Nécessite : pip install Pillow

Note : electron-builder.yml pointe vers assets/AdhamDesktop.ico.
Ce script est un fallback si le .ico est absent ou corrompu.
"""
from pathlib import Path
from PIL import Image

ROOT   = Path(__file__).resolve().parent   # D:\LLMCodeAgent\ui
SRC    = ROOT / "assets" / "AdhamDesktop.png"
DST    = ROOT / "assets" / "AdhamDesktop.ico"

SIZES = [16, 24, 32, 48, 64, 128, 256]

def main():
    if not SRC.exists():
        raise FileNotFoundError(f"Source introuvable : {SRC}")

    img = Image.open(SRC).convert("RGBA")
    resized = [img.resize((s, s), Image.LANCZOS) for s in SIZES]
    resized[0].save(DST, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=resized[1:])

    print(f"✅ ICO généré : {DST}")
    print(f"   Tailles incluses : {SIZES}")

if __name__ == "__main__":
    main()
