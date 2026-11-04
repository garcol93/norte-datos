"""Recorridos de simulación con ruta: salidas, enlaces y bifurcaciones.

Para cada caso, Valhalla (el mismo motor y datos que la radio) calcula la
ruta; su forma es el recorrido y su final, el destino. Así, al simular, la
radio calcula la misma ruta y se ven los carriles y el esquema de cada cruce.
Entrada: carpeta con <id>.nativo.json y <id>.osrm.json de cada caso.
"""
import argparse
import json
import math
import sys
from pathlib import Path

CASOS = [
    # id, nombre, descripción, origen (lat, lon), destino (lat, lon), nombre del destino, km/h
    ("cruce-a6", "Salidas de la A-6", "Moncloa → Las Rozas: bifurcaciones y carriles", (40.4352, -3.7191), (40.4925, -3.8730), "Las Rozas", 90),
    ("cruce-a1", "Enlaces de la A-1", "Plaza de Castilla → Alcobendas: M-30, M-40 y M-11", (40.4669, -3.6890), (40.5373, -3.6372), "Alcobendas", 80),
    ("cruce-ap6", "A-6 y AP-6", "Las Rozas → Guadarrama: salida hacia la AP-6", (40.4925, -3.8730), (40.6720, -4.0890), "Guadarrama", 100),
    ("cruce-se30", "SE-30 y A-4", "Sevilla → Dos Hermanas: enlaces de la SE-30", (37.3891, -5.9845), (37.2836, -5.9209), "Dos Hermanas", 80),
]


def decodificar(s: str, precision: int = 6) -> list[tuple[float, float]]:
    i = lat = lon = 0
    puntos = []
    while i < len(s):
        for k in (0, 1):
            res = sh = 0
            while True:
                b = ord(s[i]) - 63
                i += 1
                res |= (b & 0x1F) << sh
                sh += 5
                if b < 0x20:
                    break
            d = ~(res >> 1) if res & 1 else res >> 1
            if k == 0:
                lat += d
            else:
                lon += d
        puntos.append((lat / 10 ** precision, lon / 10 ** precision))
    return puntos


def distancia(a, b) -> float:
    r = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def remuestrear(puntos, paso: float = 60.0):
    """Un punto cada ~60 m, conservando las curvas (como los demás recorridos)."""
    salida = [puntos[0]]
    acumulado = 0.0
    for a, b in zip(puntos, puntos[1:]):
        acumulado += distancia(a, b)
        if acumulado >= paso:
            salida.append(b)
            acumulado = 0.0
    if salida[-1] != puntos[-1]:
        salida.append(puntos[-1])
    return salida


def contar(osrm: dict) -> tuple[int, int]:
    """(cruces con carriles, cruces con varias ramas) de la ruta en formato OSRM."""
    carriles = ramas = 0
    for leg in osrm.get("routes", [{}])[0].get("legs", []):
        for paso in leg.get("steps", []):
            i = (paso.get("intersections") or [{}])[0]
            if any(not l.get("valid") for l in i.get("lanes", [])) and any(l.get("valid") for l in i.get("lanes", [])):
                carriles += 1
            entradas = [e for k, e in enumerate(i.get("entry", [])) if e and k != i.get("in")]
            if len(entradas) >= 2:
                ramas += 1
    return carriles, ramas


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--rutas", type=Path, required=True)
    a.add_argument("--salida", type=Path, required=True)
    o = a.parse_args()
    recorridos = []
    for ident, nombre, desc, origen, destino, nombre_destino, kmh in CASOS:
        try:
            nativo = json.loads((o.rutas / f"{ident}.nativo.json").read_text())
            osrm = json.loads((o.rutas / f"{ident}.osrm.json").read_text())
            forma = [p for leg in nativo["trip"]["legs"] for p in decodificar(leg["shape"])]
        except (OSError, KeyError, ValueError) as e:
            print(f"{ident}: sin ruta ({e})", file=sys.stderr)
            continue
        carriles, ramas = contar(osrm)
        puntos = remuestrear(forma)
        largo = sum(distancia(a, b) for a, b in zip(forma, forma[1:]))
        print(f"{ident}: {largo / 1000:.1f} km, {len(puntos)} puntos, {carriles} cruces con carriles, {ramas} con varias ramas", file=sys.stderr)
        fin = forma[-1]
        recorridos.append({
            "id": ident, "nombre": nombre, "descripcion": desc, "carretera": None,
            "velocidad_kmh": kmh, "longitud_m": round(largo),
            "puntos": [[round(lon, 6), round(lat, 6)] for lat, lon in puntos],
            "destino": {"nombre": nombre_destino, "lat": round(fin[0], 6), "lon": round(fin[1], 6)},
        })
    o.salida.write_text(json.dumps({"recorridos": recorridos}, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
