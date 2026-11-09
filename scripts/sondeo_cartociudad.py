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


def es_pk(c: dict) -> bool:
    t = f"{c.get('type', '')} {c.get('tip_via', '')}".lower()
    return "kilom" in t or t.strip().startswith("pk") or "punto kilom" in t


def coords(c: dict) -> tuple[float, float] | None:
    for la, lo in (("lat", "lng"), ("lat", "lon"), ("latitude", "longitude")):
        if c.get(la) not in (None, "") and c.get(lo) not in (None, ""):
            try:
                return float(c[la]), float(c[lo])
            except (TypeError, ValueError):
                pass
    return None


def situar(via: str, km: float, crudo: list) -> tuple[float, float] | None:
    q = f"{via} {int(round(km))}"
    cands = pedir("candidates", q=q, limit=10, no_process="municipio,poblacion,toponimo,expendeduria,ngbe")
    if len(crudo) < 4:
        crudo.append((q, cands))
    if not isinstance(cands, list):
        return None
    via_n = via.replace("-", "").upper()
    for c in cands:
        if not es_pk(c):
            continue
        texto = json.dumps(c, ensure_ascii=False).replace("-", "").upper()
        if via_n not in texto:
            continue
        p = coords(c)
        if p:
            return p
        # Sin coordenadas en el candidato: se piden con «find»
        f = pedir("find", q=q, type=c.get("type", ""), id=c.get("id", ""))
        if len(crudo) < 6:
            crudo.append((f"find {q}", f))
        if isinstance(f, dict) and (p := coords(f)):
            return p
    return None


def main() -> None:
    filas, _ = leer_pdf(sys.argv[1])
    moviles = [f for f in filas if f["tipo"].startswith("m") and f["fin"] is not None]
    limite = int(sys.argv[2]) if len(sys.argv) > 2 else len(moviles)
    print(f"tramos móviles: {len(moviles)} · se prueban {min(limite, len(moviles))}")
    crudo: list = []
    ambos = uno = ninguno = 0
    km_ok = km_total = 0.0
    fallos = Counter()
    inicio = time.time()
    for i, f in enumerate(moviles[:limite]):
        a = situar(f["via"], f["ini"], crudo)
        b = situar(f["via"], f["fin"], crudo)
        km = abs(f["fin"] - f["ini"])
        km_total += km
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
    print("sin situar por tipo de vía (prefijo):", fallos.most_common(15))
    print(f"tiempo: {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    main()
