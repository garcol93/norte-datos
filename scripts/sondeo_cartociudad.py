#!/usr/bin/env python3
"""Sondeo: ¿sitúa CartoCiudad (IGN) los tramos de radar móvil de la DGT?

Para cada tramo móvil del PDF de la DGT pide al geocodificador de CartoCiudad
el punto kilométrico inicial y el final («CM-220 17») y mide cuántos se
sitúan. Solo informa; no genera datos para la app.

    python3 sondeo_cartociudad.py informe.pdf
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

from sondeo_radar_movil import leer_pdf

BASE = "https://www.cartociudad.es/geocoder/api/geocoder"
UA = {"User-Agent": "norte-datos (sondeo)"}


def pedir(ruta: str, **params) -> object | None:
    url = f"{BASE}/{ruta}?" + urllib.parse.urlencode(params)
    for intento in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                texto = r.read().decode("utf-8", "replace").strip()
            # Algunas respuestas vienen como JSONP «callback(...)»
            if texto and texto[0] not in "[{":
                texto = texto[texto.find("(") + 1: texto.rfind(")")]
            return json.loads(texto) if texto else None
        except Exception as e:  # noqa: BLE001
            if intento == 2:
                print(f"   ! {url}: {e}")
            time.sleep(1 + intento)
    return None


import math
import re
import unicodedata


def normal(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


# Provincias del PDF que CartoCiudad escribe de otra forma (o al revés)
ALIAS = {
    "illesbalears": "baleares", "balears": "baleares", "acoruna": "coruna", "lacoruna": "coruna",
    "araba": "alava", "arabaalava": "alava", "alavaaraba": "alava", "gipuzkoa": "guipuzcoa", "bizkaia": "vizcaya",
    "valenciavalencia": "valencia", "castellocastellon": "castellon", "castello": "castellon",
    "alacantalicante": "alicante", "alacant": "alicante", "ourense": "orense", "lleida": "lerida",
    "girona": "gerona", "santacruzdetenerife": "tenerife", "laspalmas": "laspalmas",
}


def prov(t: str) -> str:
    n = normal(t)
    return ALIAS.get(n, n)


def coincide(c: dict, via: str, km: int, provincia: str) -> bool:
    """La dirección es exactamente «<VÍA> km <km> (…)» y la provincia es la del PDF."""
    m = re.match(r"^\s*([A-Za-z]{1,4}-?\d{1,4}[A-Za-z]?)\s+km\s+(\d+)", str(c.get("address", "")), re.I)
    if not m or normal(m.group(1)) != normal(via) or int(m.group(2)) != km:
        return False
    p = prov(c.get("province", ""))
    q = prov(provincia)
    return not p or not q or p == q or p in q or q in p


def coords(c: dict) -> tuple[float, float] | None:
    try:
        return float(c["lat"]), float(c["lng"])
    except (KeyError, TypeError, ValueError):
        return None


def situar(via: str, km: float, provincia: str, crudo: list) -> tuple[float, float] | None:
    base = int(round(km))
    for k in (base, base + 1, base - 1):
        if k < 0:
            continue
        q = f"{via} {k}"
        cands = pedir("candidates", q=q, limit=20, no_process="municipio,poblacion,toponimo,expendeduria,ngbe")
        if len(crudo) < 3:
            crudo.append((q, cands))
        if not isinstance(cands, list):
            continue
        for c in cands:
            if coincide(c, via, k, provincia) and (p := coords(c)):
                return p
    return None


def dist_m(a, b) -> float:
    x = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    return 6371000 * math.hypot(x, math.radians(b[0] - a[0]))


def main() -> None:
    filas, _ = leer_pdf(sys.argv[1])
    moviles = [f for f in filas if f["tipo"].startswith("m") and f["fin"] is not None]
    limite = int(sys.argv[2]) if len(sys.argv) > 2 else len(moviles)
    print(f"tramos móviles: {len(moviles)} · se prueban {min(limite, len(moviles))}")
    crudo: list = []
    ambos = uno = ninguno = incoherentes = 0
    km_ok = km_total = 0.0
    fallos = Counter()
    inicio = time.time()
    for i, f in enumerate(moviles[:limite]):
        a = situar(f["via"], f["ini"], f["prov"], crudo)
        b = situar(f["via"], f["fin"], f["prov"], crudo)
        km = abs(f["fin"] - f["ini"])
        km_total += km
        if a and b and dist_m(a, b) > 1.2 * km * 1000 + 2000:
            incoherentes += 1
            a = b = None
        if a and b:
            ambos += 1
            km_ok += km
        elif a or b:
            uno += 1
        else:
            ninguno += 1
            fallos[f["via"].split("-")[0]] += 1
        if i == 3:
            print("respuestas de muestra:")
            for q, r in crudo:
                print(f"   {q} → {json.dumps(r, ensure_ascii=False)[:700]}")
        time.sleep(0.05)
    n = max(ambos + uno + ninguno, 1)
    print(f"situados los dos extremos: {ambos} ({100 * ambos / n:.0f} %) · {km_ok:.0f} de {km_total:.0f} km ({100 * km_ok / max(km_total, 1):.0f} %)")
    print(f"solo un extremo: {uno} ({100 * uno / n:.0f} %) · ninguno: {ninguno} ({100 * ninguno / n:.0f} %)")
    print(f"descartados por extremos incoherentes (más lejos que el tramo): {incoherentes}")
    print("sin situar por tipo de vía (prefijo):", fallos.most_common(15))
    print(f"tiempo: {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    main()
