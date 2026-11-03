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


def rumbo_segmento(a, b) -> float:
    """Rumbo en grados (0 = norte, 90 = este) del tramo a → b."""
    lat0 = math.radians((a[1] + b[1]) / 2)
    dx = (b[0] - a[0]) * math.cos(lat0)
    dy = b[1] - a[1]
    return math.degrees(math.atan2(dx, dy)) % 360


def diferencia_angulo(x: float, y: float) -> float:
    d = abs(x - y) % 360
    return 360 - d if d > 180 else d


def sentido_unico(tags: dict) -> int:
    """1 si se circula en el sentido del trazado, -1 al revés, 0 si es doble sentido."""
    oneway = (tags.get("oneway") or "").lower()
    if oneway in ("yes", "true", "1"):
        return 1
    if oneway == "-1":
        return -1
    if oneway == "no":
        return 0
    if tags.get("highway") in ("motorway", "motorway_link") or tags.get("junction") in ("roundabout", "circular"):
        return 1
    return 0


def asignar_limites(radares: list[dict], vias: Path) -> dict:
    """Busca la vía más cercana a cada punto de radar: límite y dirección.

    Añade a cada radar `limite` (exacto, de maxspeed), `limite_aprox`
    (genérico por tipo de vía) y `rumbo` + `doble_sentido`: la dirección de la
    vía en el radar, para que la app descarte radares de la otra calzada.
    Si hay dos calzadas de sentido contrario igual de cerca, el sentido es
    dudoso y se marca como doble sentido (solo se comprueba el eje de la vía).
    """
    # Índice de puntos de radar por celda
    indice: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i, r in enumerate(radares):
        for j, p in enumerate(puntos_de_radar(r)):
            indice.setdefault(celda(*p), []).append((i, j))
    margen = DISTANCIA_MAXIMA_M / 100_000  # en grados, con holgura

    # Para cada punto: el mejor tramo de cada vía cercana (distancia, tags, rumbo)
    candidatos: dict[tuple[int, int], dict[int, tuple[float, dict, float]]] = {}
    for n, via in enumerate(leer_secuencia(vias)):
        g = via.get("geometry") or {}
        if g.get("type") != "LineString":
            continue
        coords = g["coordinates"]
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
                        if d > DISTANCIA_MAXIMA_M:
                            continue
                        delpunto = candidatos.setdefault((i, j), {})
                        if n not in delpunto or d < delpunto[n][0]:
                            delpunto[n] = (d, via.get("properties") or {}, rumbo_segmento(a, b))

    exactos = aproximados = con_rumbo = 0
    for i, r in enumerate(radares):
        props = r["properties"]
        direccion = props.pop("direccion_osm", None)
        # Para tramos manda el inicio; si no hay vía allí, el fin
        punto = next((candidatos[(i, j)] for j in range(2) if candidatos.get((i, j))), None)
        if not punto:
            props.setdefault("limite", None)
            props["limite_aprox"] = None
            props["rumbo"] = round(direccion, 1) if direccion is not None else None
            props["doble_sentido"] = direccion is None
            continue
        lista = sorted(punto.values(), key=lambda c: c[0])
        d0, tags, rumbo = lista[0]
        limite, exacto = limite_de_via(tags)
        if props.get("fuente") == "osm" and props.get("limite"):
            pass  # el propio radar de OSM ya trae su límite
        else:
            props["limite"] = limite if exacto else None
            props["limite_aprox"] = None if exacto else limite
        if tags.get("highway"):
            props["tipo_osm"] = tags["highway"]

        sentido = sentido_unico(tags)
        if sentido == -1:
            rumbo = (rumbo + 180) % 360
        # ¿Otra calzada en sentido contrario casi igual de cerca?
        ambigua = any(
            d <= d0 + 25 and sentido_unico(t) != 0 and diferencia_angulo(
                (rb + 180) % 360 if sentido_unico(t) == -1 else rb, rumbo) > 135
            for d, t, rb in lista[1:]
        )
        if direccion is not None:
            props["rumbo"] = round(direccion, 1)
            props["doble_sentido"] = False
        else:
            props["rumbo"] = round(rumbo, 1)
            props["doble_sentido"] = sentido == 0 or ambigua
        con_rumbo += 1
        if props.get("limite"):
            exactos += 1
        elif props.get("limite_aprox"):
            aproximados += 1
    return {
        "exactos": exactos,
        "aproximados": aproximados,
        "sin_limite": len(radares) - exactos - aproximados,
        "con_rumbo": con_rumbo,
        "sentido_unico": sum(1 for r in radares if r["properties"].get("doble_sentido") is False),
    }


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
        try:
            direccion = float(tags.get("direction", "")) % 360
        except ValueError:
            direccion = None
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
                "direccion_osm": direccion,
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
    zonas = leer_comunidades(o.comunidades, o.tolerancia)
    escribir(o.salida_zonas, {"type": "FeatureCollection", "features": zonas})
    osm = radares_osm(o.camaras, zonas)

    # Un solo recorrido del archivo de vías (es grande) para todos los radares
    estad = asignar_limites(dgt["features"] + osm, o.vias)
    dgt["metadata"]["limites"] = "OSM maxspeed (exacto) o genérico por tipo de vía (aprox.)"
    dgt["metadata"]["rumbo"] = "dirección de la vía OSM en el radar; doble_sentido si no se sabe el sentido"
    escribir(o.dgt, dgt)
    print(f"límites y rumbos: {estad}", file=sys.stderr)

    escribir(o.salida_osm, {
        "type": "FeatureCollection",
        "metadata": {"fuente": "© OpenStreetMap contributors (highway=speed_camera)"},
        "features": osm,
    })
    por_zona = {z: sum(1 for r in osm if r["properties"]["zona"] == z) for z in COMUNIDADES}
    print(f"radares OSM: {len(osm)} {por_zona}", file=sys.stderr)


if __name__ == "__main__":
    main()
