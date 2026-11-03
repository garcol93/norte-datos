#!/usr/bin/env python3
"""Índice de búsqueda sin internet para Norte (SQLite con FTS4).

Lee GeoJSON en secuencia de `osmium export` y genera una base de datos con:
- `lugares`: poblaciones, calles (una por nombre y municipio) y sitios útiles
  (gasolineras, hospitales, supermercados…), con su municipio.
- `buscar`: índice de texto (FTS4, sin tildes) sobre nombre y municipio.
- `portales`: números de portal por calle (cuando OSM los tiene).

FTS4 con el tokenizador unicode61 funciona en el SQLite de Android 7 o superior.

Uso:
    python3 scripts/busqueda.py --poblaciones p.geojsonseq --calles c.geojsonseq \\
        --sitios s.geojsonseq --portales a.geojsonseq --salida build/iberia.busqueda.sqlite
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import unicodedata
from pathlib import Path

# Tipos: el orden también es la prioridad al ordenar resultados
POBLACION, CALLE, SITIO = 0, 1, 2

PESO_POBLACION = {"city": 0, "town": 1, "village": 2, "suburb": 3, "neighbourhood": 4, "hamlet": 5, "locality": 6}

SITIOS = {
    ("amenity", "fuel"): "Gasolinera",
    ("amenity", "charging_station"): "Punto de recarga",
    ("amenity", "hospital"): "Hospital",
    ("amenity", "clinic"): "Centro de salud",
    ("amenity", "pharmacy"): "Farmacia",
    ("amenity", "parking"): "Aparcamiento",
    ("amenity", "restaurant"): "Restaurante",
    ("amenity", "cafe"): "Cafetería",
    ("amenity", "police"): "Policía",
    ("amenity", "townhall"): "Ayuntamiento",
    ("amenity", "university"): "Universidad",
    ("amenity", "school"): "Colegio",
    ("shop", "supermarket"): "Supermercado",
    ("shop", "mall"): "Centro comercial",
    ("tourism", "hotel"): "Hotel",
    ("tourism", "camp_site"): "Camping",
    ("railway", "station"): "Estación",
    ("aeroway", "aerodrome"): "Aeropuerto",
    ("highway", "rest_area"): "Área de descanso",
    ("highway", "services"): "Área de servicio",
}

CELDA = 0.1  # ~10 km, para buscar el municipio más cercano


def leer(ruta: Path):
    with ruta.open(encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip().lstrip("\x1e")
            if linea:
                yield json.loads(linea)


def centro(geom: dict) -> tuple[float, float] | None:
    """Punto representativo (lon, lat) de cualquier geometría."""
    t = geom.get("type")
    c = geom.get("coordinates")
    if not c:
        return None
    if t == "Point":
        return c[0], c[1]
    if t == "LineString":
        p = c[len(c) // 2]
        return p[0], p[1]
    if t in ("Polygon", "MultiPolygon"):
        anillo = c[0] if t == "Polygon" else c[0][0]
        xs = [p[0] for p in anillo]
        ys = [p[1] for p in anillo]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    if t == "MultiLineString":
        p = c[0][len(c[0]) // 2]
        return p[0], p[1]
    return None


def normalizar(texto: str) -> str:
    """Minúsculas y sin tildes (para comparar nombres de calle)."""
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(ch for ch in t if not unicodedata.combining(ch)).strip()


class Municipios:
    """Población más cercana a un punto (ciudad, pueblo o aldea)."""

    def __init__(self):
        self.celdas: dict[tuple[int, int], list[tuple[float, float, str, int]]] = {}

    def anadir(self, lon, lat, nombre, peso):
        if peso > PESO_POBLACION["village"]:
            return
        self.celdas.setdefault((int(lon // CELDA), int(lat // CELDA)), []).append((lon, lat, nombre, peso))

    def cercano(self, lon, lat) -> str:
        cx, cy = int(lon // CELDA), int(lat // CELDA)
        mejor = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for plon, plat, nombre, peso in self.celdas.get((cx + dx, cy + dy), ()):
                    d = math.hypot((plon - lon) * math.cos(math.radians(lat)), plat - lat)
                    # Las ciudades «atraen» más: un barrio cerca de la ciudad es de la ciudad
                    d *= 1 + 0.35 * min(peso, 3)
                    if mejor is None or d < mejor[0]:
                        mejor = (d, nombre)
        return mejor[1] if mejor else ""


def crear(salida: Path) -> sqlite3.Connection:
    salida.parent.mkdir(parents=True, exist_ok=True)
    if salida.exists():
        salida.unlink()
    db = sqlite3.connect(salida)
    db.executescript("""
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        CREATE TABLE lugares (
            id INTEGER PRIMARY KEY,
            tipo INTEGER NOT NULL,
            peso INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            municipio TEXT NOT NULL,
            detalle TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL
        );
        CREATE TABLE portales (
            calle INTEGER NOT NULL,
            numero TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL
        );
        CREATE VIRTUAL TABLE buscar USING fts4(nombre, municipio, tokenize=unicode61 "remove_diacritics=1");
        CREATE TABLE info (clave TEXT PRIMARY KEY, valor TEXT);
    """)
    return db


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--poblaciones", type=Path, required=True)
    a.add_argument("--calles", type=Path, required=True)
    a.add_argument("--sitios", type=Path, required=True)
    a.add_argument("--portales", type=Path, required=True)
    a.add_argument("--salida", type=Path, required=True)
    a.add_argument("--version", default="")
    o = a.parse_args()

    db = crear(o.salida)
    municipios = Municipios()
    filas = []

    # Poblaciones
    for f in leer(o.poblaciones):
        t = f.get("properties") or {}
        nombre = t.get("name:es") or t.get("name")
        p = centro(f.get("geometry") or {})
        if not nombre or not p or t.get("place") not in PESO_POBLACION:
            continue
        peso = PESO_POBLACION[t["place"]]
        municipios.anadir(p[0], p[1], nombre, peso)
        filas.append((POBLACION, peso, nombre, "", t.get("is_in:province") or "", p[1], p[0]))
    # El municipio de un barrio es la población grande más cercana
    filas = [(tp, peso, n, municipios.cercano(lon, lat) if peso >= 3 else "", d, lat, lon)
             for tp, peso, n, _, d, lat, lon in filas]
    print(f"poblaciones: {len(filas)}", file=sys.stderr)

    # Calles: una por nombre y municipio
    calles: dict[tuple[str, str], tuple[str, str, float, float]] = {}
    for f in leer(o.calles):
        t = f.get("properties") or {}
        nombre = t.get("name")
        p = centro(f.get("geometry") or {})
        if not nombre or not p:
            continue
        mun = municipios.cercano(p[0], p[1])
        clave = (normalizar(nombre), normalizar(mun))
        if clave not in calles:
            calles[clave] = (nombre, mun, p[1], p[0])
    n_poblaciones = len(filas)
    for nombre, mun, lat, lon in calles.values():
        filas.append((CALLE, 10, nombre, mun, "", lat, lon))
    print(f"calles: {len(calles)}", file=sys.stderr)

    # Sitios útiles
    n_sitios = 0
    for f in leer(o.sitios):
        t = f.get("properties") or {}
        nombre = t.get("name") or t.get("brand")
        p = centro(f.get("geometry") or {})
        tipo = next((v for (k, val), v in SITIOS.items() if t.get(k) == val), None)
        if not p or not tipo:
            continue
        if not nombre:
            if tipo not in ("Gasolinera", "Punto de recarga", "Farmacia", "Área de servicio"):
                continue
            nombre = tipo
        filas.append((SITIO, 20, nombre, municipios.cercano(p[0], p[1]), tipo, p[1], p[0]))
        n_sitios += 1
    print(f"sitios: {n_sitios}", file=sys.stderr)

    db.executemany(
        "INSERT INTO lugares (tipo, peso, nombre, municipio, detalle, lat, lon) VALUES (?,?,?,?,?,?,?)", filas)
    db.execute("INSERT INTO buscar (docid, nombre, municipio) SELECT id, nombre, municipio FROM lugares")

    # Portales: se asocian a la calle con el mismo nombre en el municipio más cercano
    id_calle = {}
    for rid, nombre, mun in db.execute(f"SELECT id, nombre, municipio FROM lugares WHERE tipo = {CALLE}"):
        id_calle[(normalizar(nombre), normalizar(mun))] = rid
    lote = []
    n_portales = 0
    for f in leer(o.portales):
        t = f.get("properties") or {}
        numero = t.get("addr:housenumber")
        calle = t.get("addr:street")
        p = centro(f.get("geometry") or {})
        if not numero or not calle or not p:
            continue
        mun = municipios.cercano(p[0], p[1])
        rid = id_calle.get((normalizar(calle), normalizar(mun)))
        if rid is None:
            continue
        lote.append((rid, numero[:10], round(p[1], 6), round(p[0], 6)))
        if len(lote) >= 50_000:
            db.executemany("INSERT INTO portales VALUES (?,?,?,?)", lote)
            n_portales += len(lote)
            lote.clear()
    db.executemany("INSERT INTO portales VALUES (?,?,?,?)", lote)
    n_portales += len(lote)
    print(f"portales: {n_portales}", file=sys.stderr)

    db.execute("CREATE INDEX portales_calle ON portales (calle, numero)")
    db.executemany("INSERT INTO info VALUES (?, ?)", [
        ("version", o.version), ("formato", "1"),
        ("lugares", str(len(filas))), ("portales", str(n_portales)),
        ("poblaciones", str(n_poblaciones)), ("calles", str(len(calles))), ("sitios", str(n_sitios)),
    ])
    db.execute("INSERT INTO buscar(buscar) VALUES ('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()
    print(f"índice: {o.salida.stat().st_size / 1e6:.0f} MB", file=sys.stderr)


if __name__ == "__main__":
    main()
