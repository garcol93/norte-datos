#!/usr/bin/env python3
"""Completa los radares con datos de OpenStreetMap.

1. Asigna a cada radar de la DGT el límite de velocidad (`maxspeed`) de la vía
   de OSM más cercana. Si la vía no tiene `maxspeed`, deja un límite genérico
   por tipo de vía marcado como aproximado.
2. Saca los radares de OSM (`highway=speed_camera`) de Cataluña y País Vasco,
   que la DGT no publica.
3. Genera los contornos simplificados de esas dos comunidades para que la app
   sepa cuándo se circula por ellas.

Entradas (GeoJSON en secuencia, una entidad por línea, de `osmium export`):
    --vias        vías con highway=* (líneas)
    --camaras     nodos highway=speed_camera (puntos)
    --comunidades límites admin_level=4 (polígonos)
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# Límites genéricos en España por tipo de vía (Reglamento General de Circulación)
LIMITE_GENERICO = {
    "motorway": 120, "motorway_link": 60, "trunk": 100, "trunk_link": 60,
    "primary": 90, "secondary": 90, "tertiary": 90, "unclassified": 90,
    "primary_link": 60, "secondary_link": 60, "tertiary_link": 60,
    "residential": 50, "living_street": 20,
}

# Valores implícitos de OSM para España
IMPLICITOS = {
    "es:urban": 50, "es:rural": 90, "es:trunk": 100, "es:motorway": 120,
    "es:zone30": 30, "es:zone20": 20, "es:living_street": 20, "es:school": 20,
}

COMUNIDADES = {
    # nombre en OSM (o alternativas) -> id y nombre en la app
    "cataluna": ("Catalunya", "Cataluña"),
    "pais_vasco": ("Euskadi", "País Vasco"),
}

DISTANCIA_MAXIMA_M = 40.0
CELDA = 0.002  # ~200 m


def parsear_maxspeed(valor: str | None) -> int | None:
    if not valor:
        return None
    v = valor.strip().lower()
    if v in IMPLICITOS:
        return IMPLICITOS[v]
    m = re.match(r"^(\d{1,3})(\s*mph)?$", v)
    if not m:
        return None
    n = int(m.group(1))
    if m.group(2):
        n = round(n * 1.609)
    return n if 5 <= n <= 130 else None


def limite_de_via(tags: dict) -> tuple[int | None, bool]:
    """(límite, exacto). Exacto si viene de maxspeed; aproximado si es genérico."""
    exacto = parsear_maxspeed(tags.get("maxspeed"))
    if exacto is None:
        sentidos = [parsear_maxspeed(tags.get(k)) for k in ("maxspeed:forward", "maxspeed:backward")]
        sentidos = [s for s in sentidos if s]
        if sentidos:
            exacto = min(sentidos)
    if exacto is not None:
        return exacto, True
    return LIMITE_GENERICO.get(tags.get("highway", "")), False


def celda(lon: float, lat: float) -> tuple[int, int]:
    return int(math.floor(lon / CELDA)), int(math.floor(lat / CELDA))


def distancia_a_segmento(p, a, b) -> float:
    """Distancia en metros de p a [a, b] con proyección local equirectangular."""
    lat0 = math.radians(p[1])
    kx = 111_320.0 * math.cos(lat0)
    ky = 110_540.0
    px, py = p[0] * kx, p[1] * ky
    ax, ay = a[0] * kx, a[1] * ky
    bx, by = b[0] * kx, b[1] * ky
    dx, dy = bx - ax, by - ay
    largo2 = dx * dx + dy * dy
    t = 0.0 if largo2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / largo2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def puntos_de_radar(feature: dict) -> list[list[float]]:
    g = feature["geometry"]
    return [g["coordinates"]] if g["type"] == "Point" else [g["coordinates"][0], g["coordinates"][-1]]


def leer_secuencia(ruta: Path):
    with ruta.open(encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip().lstrip("\x1e")
            if linea:
                yield json.loads(linea)


def asignar_limites(radares: list[dict], vias: Path) -> dict:
    """Busca la vía más cercana a cada punto de radar. Devuelve estadísticas."""
    # Índice de puntos de radar por celda
    indice: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i, r in enumerate(radares):
        for j, p in enumerate(puntos_de_radar(r)):
            indice.setdefault(celda(*p), []).append((i, j))
    margen = DISTANCIA_MAXIMA_M / 100_000  # en grados, con holgura

    mejor: dict[tuple[int, int], tuple[float, dict]] = {}
    for via in leer_secuencia(vias):
        g = via.get("geometry") or {}
        if g.get("type") != "LineString":
            continue
        coords = g["coordinates"]
        tags = None
        # Cada tramo de la vía: celdas de su recuadro ampliado (los tramos
        # rectos de autovía pueden medir kilómetros entre vértices)
        for a, b in zip(coords, coords[1:]):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            cx0, cy0 = celda(x0 - margen, y0 - margen)
            cx1, cy1 = celda(x1 + margen, y1 + margen)
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    for (i, j) in indice.get((cx, cy), ()):
                        p = puntos_de_radar(radares[i])[j]
                        d = distancia_a_segmento(p, a, b)
                        if d <= DISTANCIA_MAXIMA_M and ((i, j) not in mejor or d < mejor[(i, j)][0]):
                            tags = tags if tags is not None else (via.get("properties") or {})
                            mejor[(i, j)] = (d, tags)

    exactos = aproximados = 0
    for i, r in enumerate(radares):
        props = r["properties"]
        # Para tramos manda el inicio; si no hay vía allí, el fin
        tags = next((mejor[(i, j)][1] for j in range(2) if (i, j) in mejor), None)
        limite, exacto = limite_de_via(tags) if tags else (None, False)
        props["limite"] = limite if exacto else None
        props["limite_aprox"] = None if exacto else limite
        if tags and tags.get("highway"):
            props["tipo_osm"] = tags["highway"]
        if exacto:
            exactos += 1
        elif limite:
            aproximados += 1
    return {"exactos": exactos, "aproximados": aproximados, "sin_limite": len(radares) - exactos - aproximados}


def dentro(poligono: list, lon: float, lat: float) -> bool:
    """Punto en polígono (anillo exterior; los huecos se ignoran)."""
    anillo = poligono[0]
    resultado = False
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:]):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            resultado = not resultado
    return resultado


def en_zona(zonas: list[dict], lon: float, lat: float) -> str | None:
    for z in zonas:
        g = z["geometry"]
        poligonos = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        if any(dentro(p, lon, lat) for p in poligonos):
            return z["properties"]["id"]
    return None


def leer_comunidades(ruta: Path, tolerancia: float) -> list[dict]:
    from shapely.geometry import mapping, shape

    zonas = []
    for f in leer_secuencia(ruta):
        tags = f.get("properties") or {}
        nombres = {tags.get(k, "") for k in ("name", "name:es", "name:ca", "name:eu")}
        for ident, (nombre_osm, nombre_app) in COMUNIDADES.items():
            if nombre_osm in nombres or nombre_app in nombres:
                geom = shape(f["geometry"]).simplify(tolerancia, preserve_topology=True)
                zonas.append({
                    "type": "Feature",
                    "properties": {"id": ident, "nombre": nombre_app},
                    "geometry": mapping(geom),
                })
    encontrados = {z["properties"]["id"] for z in zonas}
    faltan = set(COMUNIDADES) - encontrados
    if faltan:
        raise SystemExit(f"No se encontraron los contornos de: {', '.join(sorted(faltan))}")
    # Redondeo para que el archivo sea pequeño
    def redondear(c):
        return [round(c[0], 4), round(c[1], 4)] if isinstance(c[0], float) else [redondear(x) for x in c]
    for z in zonas:
        z["geometry"]["coordinates"] = redondear(json.loads(json.dumps(z["geometry"]["coordinates"])))
    return zonas


def radares_osm(camaras: Path, zonas: list[dict]) -> list[dict]:
    salida = []
    for f in leer_secuencia(camaras):
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        lon, lat = g["coordinates"]
        zona = en_zona(zonas, lon, lat)
        if zona is None:
            continue  # fuera de Cataluña y País Vasco ya avisa la DGT
        tags = f.get("properties") or {}
        ident = tags.get("@id") or f.get("id") or f"{lon:.5f},{lat:.5f}"
        salida.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {
                "id": f"osm:{ident}",
                "fuente": "osm",
                "tipo": "fijo",
                "limite": parsear_maxspeed(tags.get("maxspeed")),
                "limite_aprox": None,
                "carretera": tags.get("ref"),
                "zona": zona,
            },
        })
    return salida


def escribir(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--dgt", type=Path, required=True, help="dgt.geojson (se reescribe con los límites)")
    a.add_argument("--vias", type=Path, required=True)
    a.add_argument("--camaras", type=Path, required=True)
    a.add_argument("--comunidades", type=Path, required=True)
    a.add_argument("--salida-osm", type=Path, required=True)
    a.add_argument("--salida-zonas", type=Path, required=True)
    a.add_argument("--tolerancia", type=float, default=0.005, help="simplificación de contornos en grados")
    o = a.parse_args()

    dgt = json.loads(o.dgt.read_text(encoding="utf-8"))
    estad = asignar_limites(dgt["features"], o.vias)
    dgt["metadata"]["limites"] = "OSM maxspeed (exacto) o genérico por tipo de vía (aprox.)"
    escribir(o.dgt, dgt)
    print(f"límites DGT: {estad}", file=sys.stderr)

    zonas = leer_comunidades(o.comunidades, o.tolerancia)
    escribir(o.salida_zonas, {"type": "FeatureCollection", "features": zonas})

    osm = radares_osm(o.camaras, zonas)
    escribir(o.salida_osm, {
        "type": "FeatureCollection",
        "metadata": {"fuente": "© OpenStreetMap contributors (highway=speed_camera)"},
        "features": osm,
    })
    por_zona = {z: sum(1 for r in osm if r["properties"]["zona"] == z) for z in COMUNIDADES}
    print(f"radares OSM: {len(osm)} {por_zona}", file=sys.stderr)


if __name__ == "__main__":
    main()
