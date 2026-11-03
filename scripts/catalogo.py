#!/usr/bin/env python3
"""Genera catalogo.json a partir de las releases publicadas en este repo.

La app de Norte descarga este catálogo (URL fija) para saber qué mapas y
radares hay, su versión y su tamaño.

Uso (en GitHub Actions): python3 scripts/catalogo.py --salida build/catalogo.json
Necesita GITHUB_TOKEN (o GH_TOKEN) y GITHUB_REPOSITORY en el entorno.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def api(ruta: str):
    url = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{ruta}"
    peticion = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN') or os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(peticion, timeout=60) as r:
        return json.load(r)


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--salida", type=Path, required=True)
    opciones = args.parse_args()

    nombres = {r["id"]: r["nombre"] for r in json.loads((RAIZ / "regiones.json").read_text())["regiones"]}
    releases = api("releases?per_page=100")

    # Para cada región, el archivo de la release de mapas más reciente que lo tenga
    mapas: dict[str, dict] = {}
    for rel in sorted((r for r in releases if r["tag_name"].startswith("mapas-")),
                      key=lambda r: r["tag_name"], reverse=True):
        version = rel["tag_name"].removeprefix("mapas-")
        for asset in rel["assets"]:
            if not asset["name"].endswith(".pmtiles"):
                continue
            ident = asset["name"].removesuffix(".pmtiles")
            if ident in mapas:
                continue
            mapas[ident] = {
                "id": ident,
                "nombre": nombres.get(ident, ident),
                "archivo": asset["name"],
                "url": asset["browser_download_url"],
                "bytes": asset["size"],
                "version": version,
            }

    radares = []
    for rel in releases:
        if rel["tag_name"] != "radares":
            continue
        for asset in rel["assets"]:
            if asset["name"].endswith(".geojson"):
                radares.append({
                    "id": asset["name"].removesuffix(".geojson"),
                    "url": asset["browser_download_url"],
                    "bytes": asset["size"],
                    "version": asset["updated_at"],
                })

    # Rutas (teselas de Valhalla troceadas): la release más reciente de cada región
    rutas: dict[str, dict] = {}
    for rel in sorted((r for r in releases if r["tag_name"].startswith("rutas-")),
                      key=lambda r: r["tag_name"], reverse=True):
        urls = {a["name"]: a["browser_download_url"] for a in rel["assets"]}
        for nombre_archivo, url in urls.items():
            if not nombre_archivo.endswith(".rutas.json"):
                continue
            with urllib.request.urlopen(url, timeout=60) as r:
                manifiesto = json.load(r)
            ident = manifiesto["id"]
            if ident in rutas:
                continue
            partes = [{"url": urls[p["archivo"]], "bytes": p["bytes"]} for p in manifiesto["partes"] if p["archivo"] in urls]
            if len(partes) != len(manifiesto["partes"]):
                continue  # release incompleta
            rutas[ident] = {
                "id": ident,
                "nombre": manifiesto["nombre"],
                "version": manifiesto["version"],
                "valhalla": manifiesto["valhalla"],
                "bytes": manifiesto["bytes"],
                "sha256": manifiesto["sha256"],
                "partes": partes,
            }

    # Índices de búsqueda sin internet: el más reciente de cada región
    busqueda: dict[str, dict] = {}
    for rel in sorted((r for r in releases if r["tag_name"].startswith("busqueda-")),
                      key=lambda r: r["tag_name"], reverse=True):
        for asset in rel["assets"]:
            if not asset["name"].endswith(".busqueda.sqlite"):
                continue
            ident = asset["name"].removesuffix(".busqueda.sqlite")
            if ident in busqueda:
                continue
            busqueda[ident] = {
                "id": ident,
                "nombre": "Península Ibérica (España, Portugal y Andorra)" if ident == "iberia" else ident,
                "archivo": asset["name"],
                "url": asset["browser_download_url"],
                "bytes": asset["size"],
                "version": rel["tag_name"].removeprefix("busqueda-"),
            }

    orden = list(nombres)
    catalogo = {
        "formato": 1,
        "generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "atribucion": "© OpenStreetMap contributors; radares: DGT (nap.dgt.es)",
        "mapas": sorted(mapas.values(), key=lambda m: orden.index(m["id"]) if m["id"] in orden else 99),
        "radares": radares,
        "rutas": list(rutas.values()),
        "busqueda": list(busqueda.values()),
    }
    opciones.salida.parent.mkdir(parents=True, exist_ok=True)
    opciones.salida.write_text(json.dumps(catalogo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"catálogo: {len(mapas)} mapas, {len(radares)} archivos de radares, {len(rutas)} paquetes de rutas")


if __name__ == "__main__":
    main()
