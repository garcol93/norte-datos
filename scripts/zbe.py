#!/usr/bin/env python3
"""Zonas de bajas emisiones (ZBE) de OpenStreetMap para Norte.

Lee los polígonos `boundary=low_emission_zone` exportados con osmium
(GeoJSON en secuencia) y escribe un GeoJSON pequeño con el contorno
simplificado, el nombre y, si los hay, las reglas y notas tal cual vienen
en OSM. La app avisa al acercarse y puede calcular rutas que las eviten;
no decide si un coche concreto puede entrar.

    python3 zbe.py --zbe zbe.geojsonseq --salida build/zbe.geojson
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TOLERANCIA = 0.0002  # ~20 m


def leer_secuencia(ruta: Path):
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip().lstrip("\x1e")
            if linea:
                yield json.loads(linea)


def nombre_de(tags: dict) -> str:
    for k in ("name:es", "name", "official_name", "name:ca", "name:eu", "name:gl"):
        if tags.get(k):
            return tags[k].strip()
    return "Zona de bajas emisiones"


def zona(feature: dict, tolerancia: float = TOLERANCIA) -> dict | None:
    from shapely.geometry import mapping, shape

    tags = feature.get("properties") or {}
    if tags.get("boundary") not in (None, "low_emission_zone"):
        return None
    geom = shape(feature["geometry"])
    if geom.is_empty or geom.area <= 0:
        return None
    geom = geom.simplify(tolerancia, preserve_topology=True)
    props = {"id": f"zbe-{tags.get('@id') or tags.get('@type', '') + str(tags.get('id', ''))}".rstrip("-"),
             "nombre": nombre_de(tags)}
    reglas = {k: v for k, v in tags.items() if k.endswith(":conditional") or k.startswith("access") or k.startswith("motor_vehicle")}
    if reglas:
        props["reglas"] = reglas
    if tags.get("short_name"):
        props["corto"] = tags["short_name"].strip()
    for k_osm, k_app in (("opening_hours", "horario"), ("note", "nota"), ("description", "descripcion"), ("start_date", "inicio"), ("website", "web")):
        if tags.get(k_osm):
            props[k_app] = tags[k_osm]
    geometria = mapping(geom)
    geometria = json.loads(json.dumps(geometria))

    def redondear(c):
        return [round(c[0], 5), round(c[1], 5)] if isinstance(c[0], (int, float)) else [redondear(x) for x in c]

    geometria["coordinates"] = redondear(geometria["coordinates"])
    return {"type": "Feature", "properties": props, "geometry": geometria}


def main() -> None:
    a = argparse.ArgumentParser()
    a.add_argument("--zbe", type=Path, required=True)
    a.add_argument("--salida", type=Path, required=True)
    o = a.parse_args()
    zonas = [z for z in (zona(f) for f in leer_secuencia(o.zbe)) if z]
    # Ids únicos (un mismo nombre puede salir en varias piezas)
    vistos: dict[str, int] = {}
    for z in zonas:
        base = re.sub(r"[^a-z0-9-]", "", z["properties"]["id"].lower()) or "zbe"
        vistos[base] = vistos.get(base, 0) + 1
        z["properties"]["id"] = base if vistos[base] == 1 else f"{base}-{vistos[base]}"
    o.salida.parent.mkdir(parents=True, exist_ok=True)
    o.salida.write_text(json.dumps({"type": "FeatureCollection", "features": zonas}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"zbe: {len(zonas)} zonas, {o.salida.stat().st_size // 1024} KB")
    if not zonas:
        raise SystemExit("No hay ninguna zona de bajas emisiones: algo ha fallado en el filtro de OSM")


if __name__ == "__main__":
    main()
