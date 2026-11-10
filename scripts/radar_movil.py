#!/usr/bin/env python3
"""Zonas de posible radar móvil para Norte.

1. Lee el PDF de la DGT «INFORME_CINEMOMETROS…pdf» (provincia, carretera,
   PK inicial - PK final) y se queda con los tramos de radar móvil.
2. Sitúa cada extremo con el geocodificador de puntos kilométricos de
   CartoCiudad (IGN), con caché para no repetir consultas entre ejecuciones.
3. Traza el tramo por la carretera de OpenStreetMap con esa referencia
   (camino más corto entre los extremos); si no hay trazado, une los extremos
   en línea recta y lo marca como aproximado.

    python3 radar_movil.py --pdf informe.pdf --vias vias.geojsonseq \
        --cache movil-cache.json --salida build/movil.geojson
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
import re
import time
from collections import defaultdict
from pathlib import Path

from sondeo_cartociudad import coincide, coords, dist_m, pedir
from sondeo_radar_movil import leer_pdf, ref_normal

DISTANCIA_EXTREMO_M = 300.0  # un extremo se engancha a la carretera de OSM si está a menos de esto
SIMPLIFICAR = 0.00015  # ~15 m


def normal_ref(r: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", ref_normal(r))


# --- CartoCiudad con caché ---------------------------------------------------

def situar(via: str, km: float, provincia: str, cache: dict) -> tuple[float, float] | None:
    base = int(round(km))
    for k in (base, base + 1, base - 1):
        if k < 0:
            continue
        clave = f"{via}|{k}|{provincia}"
        if clave not in cache:
            cands = pedir("candidates", q=f"{via} {k}", limit=20, no_process="municipio,poblacion,toponimo,expendeduria,ngbe")
            punto = None
            if isinstance(cands, list):
                for c in cands:
                    if coincide(c, via, k, provincia) and (p := coords(c)):
                        punto = [round(p[0], 6), round(p[1], 6)]
                        break
            cache[clave] = punto
            time.sleep(0.05)
        if cache[clave]:
            return tuple(cache[clave])
    return None


# --- Carreteras de OSM -------------------------------------------------------

def leer_vias(ruta: Path, refs: set[str]) -> dict[str, list[list[tuple[float, float]]]]:
    """ref normalizada -> líneas ([(lat, lon)]) de las vías de OSM con esa ref."""
    salida: dict[str, list] = defaultdict(list)
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip().lstrip("\x1e")
            if not linea:
                continue
            e = json.loads(linea)
            ref = (e.get("properties") or {}).get("ref")
            if not ref or e["geometry"]["type"] != "LineString":
                continue
            for r in ref.split(";"):
                n = normal_ref(r)
                if n in refs:
                    salida[n].append([(c[1], c[0]) for c in e["geometry"]["coordinates"]])
    return salida


class Grafo:
    """Grafo de una carretera: nodos = puntos redondeados, aristas = segmentos."""

    def __init__(self, lineas: list[list[tuple[float, float]]]):
        self.ady: dict[tuple, list[tuple[tuple, float]]] = defaultdict(list)
        for l in lineas:
            pts = [(round(a, 6), round(b, 6)) for a, b in l]
            for p, q in zip(pts, pts[1:]):
                d = dist_m(p, q)
                self.ady[p].append((q, d))
                self.ady[q].append((p, d))
        self.nodos = list(self.ady)

    def cercano(self, p: tuple[float, float]) -> tuple[tuple, float] | None:
        if not self.nodos:
            return None
        n = min(self.nodos, key=lambda q: (q[0] - p[0]) ** 2 + ((q[1] - p[1]) * math.cos(math.radians(p[0]))) ** 2)
        return n, dist_m(n, p)

    def camino(self, a: tuple, b: tuple) -> list[tuple] | None:
        dist = {a: 0.0}
        previo: dict[tuple, tuple] = {}
        cola = [(0.0, a)]
        while cola:
            d, n = heapq.heappop(cola)
            if n == b:
                break
            if d > dist.get(n, math.inf):
                continue
            for m, w in self.ady[n]:
                nd = d + w
                if nd < dist.get(m, math.inf):
                    dist[m] = nd
                    previo[m] = n
                    heapq.heappush(cola, (nd, m))
        if b not in dist:
            return None
        ruta = [b]
        while ruta[-1] != a:
            ruta.append(previo[ruta[-1]])
        return ruta[::-1]


def trazar(grafo: Grafo | None, a: tuple, b: tuple, longitud_m: float) -> tuple[list[tuple], bool]:
    """Puntos (lat, lon) del tramo y si es aproximado (línea recta)."""
    if grafo:
        ca, cb = grafo.cercano(a), grafo.cercano(b)
        if ca and cb and ca[1] < DISTANCIA_EXTREMO_M and cb[1] < DISTANCIA_EXTREMO_M:
            ruta = grafo.camino(ca[0], cb[0])
            if ruta and len(ruta) > 1:
                largo = sum(dist_m(p, q) for p, q in zip(ruta, ruta[1:]))
                # Un rodeo mucho más largo que el tramo indica que no es la misma carretera
                if largo <= max(1.5 * longitud_m, longitud_m + 3000):
                    return ruta, False
    return [a, b], True


def simplificar(puntos: list[tuple]) -> list[tuple]:
    from shapely.geometry import LineString

    if len(puntos) < 3:
        return puntos
    l = LineString([(p[1], p[0]) for p in puntos]).simplify(SIMPLIFICAR, preserve_topology=False)
    return [(round(y, 5), round(x, 5)) for x, y in l.coords]


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--pdf", type=Path, required=True)
    a.add_argument("--vias", type=Path, required=True)
    a.add_argument("--cache", type=Path, required=True)
    a.add_argument("--salida", type=Path, required=True)
    o = a.parse_args()

    filas, _ = leer_pdf(str(o.pdf))
    tramos = [f for f in filas if f["tipo"].startswith("m") and f["fin"] is not None]
    if len(tramos) < 300:
        raise SystemExit(f"Solo {len(tramos)} tramos móviles en el PDF: ¿ha cambiado el formato?")
    cache = json.loads(o.cache.read_text()) if o.cache.exists() else {}
    antes = len(cache)

    refs = {normal_ref(t["via"]) for t in tramos}
    vias = leer_vias(o.vias, refs)
    grafos: dict[str, Grafo] = {}

    features, sin_situar, aprox = [], 0, 0
    for t in tramos:
        ini = situar(t["via"], t["ini"], t["prov"], cache)
        fin = situar(t["via"], t["fin"], t["prov"], cache)
        longitud = abs(t["fin"] - t["ini"]) * 1000
        if not ini or not fin or dist_m(ini, fin) > 1.2 * longitud + 2000:
            sin_situar += 1
            continue
        r = normal_ref(t["via"])
        if r not in grafos and r in vias:
            grafos[r] = Grafo(vias[r])
        puntos, es_aprox = trazar(grafos.get(r), ini, fin, longitud)
        aprox += es_aprox
        puntos = simplificar(puntos)
        features.append({
            "type": "Feature",
            "properties": {
                "id": f"movil:{t['via']}:{t['ini']:g}",
                "provincia": t["prov"].replace("�", ""),
                "carretera": t["via"],
                "pk_inicio": t["ini"],
                "pk_fin": t["fin"],
                "longitud_m": round(longitud),
                **({"aprox": True} if es_aprox else {}),
            },
            "geometry": {"type": "LineString", "coordinates": [[p[1], p[0]] for p in puntos]},
        })

    sha = hashlib.sha256(o.pdf.read_bytes()).hexdigest()
    salida = {
        "type": "FeatureCollection",
        "fuente": {"pdf_sha256": sha, "tramos_pdf": len(tramos)},
        "features": features,
    }
    o.salida.parent.mkdir(parents=True, exist_ok=True)
    o.salida.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    o.cache.write_text(json.dumps(cache, ensure_ascii=False))
    km = sum(f["properties"]["longitud_m"] for f in features) / 1000
    print(f"radar móvil: {len(features)} de {len(tramos)} tramos ({km:.0f} km), {aprox} en línea recta, "
          f"{sin_situar} sin situar · consultas nuevas a CartoCiudad: {len(cache) - antes} · {o.salida.stat().st_size // 1024} KB")
    if len(features) < 0.6 * len(tramos):
        raise SystemExit("Menos del 60 % de los tramos situados: no se publica")


if __name__ == "__main__":
    main()
