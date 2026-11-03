#!/usr/bin/env python3
"""Convierte el inventario de radares de la DGT (DATEX II v1.0) a GeoJSON.

Fuente: https://nap.dgt.es/dataset/radares-fijos-dgt
Cubre la red estatal salvo Cataluña y País Vasco. No incluye radares móviles
ni la velocidad límite.

Uso:
    python3 scripts/radares_dgt.py --salida build/radares_dgt.geojson
    python3 scripts/radares_dgt.py --entrada content.xml --salida radares.geojson
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# El NAP es el espejo fiable; infocar a veces responde 502.
URLS = [
    "https://nap.dgt.es/datex2/dgt/PredefinedLocationsPublication/radares/content.xml",
    "https://infocar.dgt.es/datex2/dgt/PredefinedLocationsPublication/radares/content.xml",
]

NS = "http://datex2.eu/schema/1_0/1_0"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# Si salen menos radares, algo ha cambiado en el formato: mejor fallar que
# publicar un archivo casi vacío.
MINIMO_RADARES = 300


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def texto(elem: ET.Element | None, ruta: str) -> str | None:
    if elem is None:
        return None
    hallado = elem.find(ruta, {"d": NS})
    if hallado is None or hallado.text is None:
        return None
    valor = hallado.text.strip()
    return valor or None


def coordenadas(elem: ET.Element | None) -> list[float] | None:
    lat = texto(elem, "d:pointCoordinates/d:latitude")
    lon = texto(elem, "d:pointCoordinates/d:longitude")
    if lat is None or lon is None:
        return None
    # GeoJSON usa [longitud, latitud]
    return [round(float(lon), 6), round(float(lat), 6)]


def punto_referencia(ref: ET.Element | None) -> dict:
    """Datos de carretera de un referencePoint (PK en km)."""
    if ref is None:
        return {}
    ext = "d:referencePointExtension/d:ExtendedReferencePoint/"
    pk_m = texto(ref, "d:referencePointDistance")
    sentido = texto(ref, "d:directionRelative")
    return {
        "carretera": texto(ref, "d:roadNumber") or texto(ref, "d:roadName/d:value"),
        "pk": round(float(pk_m) / 1000, 3) if pk_m else None,
        # positive = sentido de PK crecientes
        "sentido": {"positive": "creciente", "negative": "decreciente"}.get(sentido or ""),
        "hacia": texto(ref, ext + "d:directionNamed"),
        "provincia": texto(ref, "d:administrativeArea/d:value"),
        "ine": texto(ref, ext + "d:provinceINEIdentifier"),
        "tipo_via": texto(ref, ext + "d:singularity"),
    }


def tipo_xsi(elem: ET.Element) -> str:
    return (elem.get(XSI_TYPE) or "").split(":")[-1]


def parsear(xml: bytes) -> tuple[list[dict], str | None]:
    raiz = ET.fromstring(xml)
    publicado = texto(raiz, ".//d:publicationTime")
    radares: list[dict] = []

    for externo in raiz.iter(q("predefinedLocation")):
        ident = externo.get("id")
        if not ident:
            continue  # es el predefinedLocation interno
        interno = next((h for h in externo if h.tag == q("predefinedLocation")), None)
        if interno is None:
            continue
        nombre = texto(externo, "d:predefinedLocationName/d:value") or ident.removeprefix("GUID_")
        clase = tipo_xsi(interno)

        if clase == "Point":
            coords = coordenadas(interno.find("d:tpegpointLocation/d:point", {"d": NS}))
            if coords is None:
                continue
            datos = punto_referencia(interno.find("d:referencePoint", {"d": NS}))
            radares.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coords},
                "properties": {"id": f"dgt:{nombre}", "fuente": "dgt", "tipo": "fijo",
                               "limite": None, **datos},
            })

        elif clase == "Linear":
            lineal = interno.find("d:tpeglinearLocation", {"d": NS})
            # En el XML <to> va antes que <from>, pero from = inicio y to = fin.
            inicio = coordenadas(lineal.find("d:from", {"d": NS})) if lineal is not None else None
            fin = coordenadas(lineal.find("d:to", {"d": NS})) if lineal is not None else None
            if inicio is None or fin is None:
                continue
            ref = "d:referencePointLinear/d:referencePoint{}Location/d:referencePoint"
            ini = punto_referencia(interno.find(ref.format("Primary"), {"d": NS}))
            fn = punto_referencia(interno.find(ref.format("Secondary"), {"d": NS}))
            radares.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [inicio, fin]},
                "properties": {
                    "id": f"dgt:{nombre}", "fuente": "dgt", "tipo": "tramo", "limite": None,
                    "carretera": ini.get("carretera"),
                    "sentido": ini.get("sentido"),
                    "hacia": ini.get("hacia") or fn.get("hacia"),
                    "tipo_via": ini.get("tipo_via"),
                    "pk_inicio": ini.get("pk"), "pk_fin": fn.get("pk"),
                    "provincia_inicio": ini.get("provincia"), "provincia_fin": fn.get("provincia"),
                    "ine_inicio": ini.get("ine"), "ine_fin": fn.get("ine"),
                },
            })

    return radares, publicado


def descargar() -> bytes:
    errores = []
    for url in URLS:
        try:
            peticion = urllib.request.Request(url, headers={"User-Agent": "norte-datos"})
            with urllib.request.urlopen(peticion, timeout=120) as resp:
                return resp.read()
        except Exception as error:  # noqa: BLE001 - se prueba la siguiente URL
            errores.append(f"{url}: {error}")
    raise SystemExit("No se pudo descargar el XML de radares:\n" + "\n".join(errores))


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--entrada", type=Path, help="XML local (si no, se descarga)")
    args.add_argument("--salida", type=Path, required=True)
    args.add_argument("--minimo", type=int, default=MINIMO_RADARES,
                      help="Número mínimo de radares esperado")
    opciones = args.parse_args()

    xml = opciones.entrada.read_bytes() if opciones.entrada else descargar()
    radares, publicado = parsear(xml)

    if len(radares) < opciones.minimo:
        raise SystemExit(f"Solo {len(radares)} radares (mínimo {opciones.minimo}): "
                         "¿ha cambiado el formato de la DGT?")

    resultado = {
        "type": "FeatureCollection",
        "metadata": {
            "fuente": "DGT - Punto de Acceso Nacional (nap.dgt.es), radares fijos",
            "publicado_dgt": publicado,
        },
        "features": radares,
    }
    opciones.salida.parent.mkdir(parents=True, exist_ok=True)
    opciones.salida.write_text(json.dumps(resultado, ensure_ascii=False, separators=(",", ":")),
                               encoding="utf-8")
    fijos = sum(1 for r in radares if r["properties"]["tipo"] == "fijo")
    print(f"{len(radares)} radares DGT ({fijos} fijos, {len(radares) - fijos} tramos); "
          f"publicado por la DGT: {publicado}", file=sys.stderr)


if __name__ == "__main__":
    main()
