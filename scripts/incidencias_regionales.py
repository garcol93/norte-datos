"""Incidencias de Cataluña y País Vasco, que la DGT no incluye en su DATEX 3.

Fuentes:
  - Servei Català de Trànsit (GML): https://www.gencat.cat/transit/opendata/incidenciesGML.xml
  - Dirección de Tráfico del Gobierno Vasco (DATEX II 1.0, republicado por la DGT):
    https://nap.dgt.es/datex2/dt-gv/SituationPublication/all/content.xml
    (solo las que traen coordenadas; las demás usan tablas que no se pueden situar)
Salida: JSON comprimido con la misma forma que las incidencias de la app (en
castellano), para que la radio baje un archivo pequeño en vez de ~1 MB.
"""
import argparse
import gzip
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


def local(tag: str) -> str:
    return tag.split("}")[-1]


# --- Cataluña -----------------------------------------------------------------

DETALLE_SCT = {
    "calçada tallada": "Calzada cortada",
    "carretera tallada": "Vía cortada",
    "un carril tallat": "Un carril cortado",
    "dos carrils tallats": "Dos carriles cortados",
    "carril tallat": "Carril cortado",
    "pas alternatiu": "Paso alternativo",
    "circulació intensa": "Circulación intensa",
    "circulació lenta": "Circulación lenta",
    "circulació aturada": "Circulación detenida",
    "calçada restringida": "Calzada restringida",
    "desviament": "Desvío",
    "desviaments": "Desvíos",
    "circulació amb retencions": "Circulación con retenciones",
    "retencions": "Retenciones",
}


def traducir(texto: str) -> str:
    """«Calçada restringida. Desviaments» → «Calzada restringida. Desvíos» (lo que no se conoce, tal cual)."""
    partes = [p.strip() for p in texto.split(".") if p.strip()]
    return ". ".join(DETALLE_SCT.get(p.lower(), p) for p in partes)


def tipo_sct(tipo: str, causa: str, detalle: str) -> tuple[str, str]:
    t, c, d = tipo.lower(), causa.lower(), detalle.lower()
    if "tallada" in d and "carril" not in d:
        return "Cortada", "Vía cortada" if "carretera" in d else "Calzada cortada"
    if "accident" in c:
        return "Accidente", "Accidente"
    if "retenci" in t:
        return "Retencion", "Retención"
    if "obres" in t or "obra" in c or "treball" in c or "manteniment" in c:
        return "Obras", "Obras"
    if "meteor" in t or "neu" in c or "boira" in c or "gel" in c:
        return "Meteorologia", "Meteorología adversa"
    return "Peligro", "Incidencia"


def cataluna(xml: str) -> list[dict]:
    salida = []
    raiz = ET.fromstring(xml)
    for f in raiz.iter():
        if local(f.tag) != "mct2_v_afectacions_data":
            continue
        campos = {local(e.tag): (e.text or "").strip() for e in f.iter()}
        coords = campos.get("coordinates", "")
        try:
            lon, lat = (float(x) for x in coords.split(",")[:2])
        except ValueError:
            continue
        tipo, titulo = tipo_sct(campos.get("descripcio_tipus", ""), campos.get("causa", ""), campos.get("descripcio", ""))
        original = campos.get("descripcio", "")
        detalle = traducir(original)
        pk = lambda k: float(campos[k]) if campos.get(k) else None
        salida.append({
            "id": "sct-" + campos.get("identificador", ""), "tipo": tipo, "titulo": titulo,
            "detalle": detalle, "via": campos.get("carretera", ""),
            "pkDesde": pk("pk_inici"), "pkHasta": pk("pk_fi"),
            "lat": round(lat, 6), "lon": round(lon, 6), "latHasta": round(lat, 6), "lonHasta": round(lon, 6),
            "rumbo": None, "ambos": campos.get("sentit", "").lower().startswith("ambd"),
            "municipio": "", "fuente": "Servei Català de Trànsit",
        })
    return salida


# --- País Vasco (DATEX II 1.0) ------------------------------------------------

RUMBOS = {"northBound": 0, "northEastBound": 45, "eastBound": 90, "southEastBound": 135,
          "southBound": 180, "southWestBound": 225, "westBound": 270, "northWestBound": 315}


def tipo_dtgv(xsi: str) -> tuple[str, str]:
    t = xsi.split(":")[-1]
    return {
        "ConstructionWorks": ("Obras", "Obras"),
        "MaintenanceWorks": ("Obras", "Obras"),
        "Accident": ("Accidente", "Accidente"),
        "AbnormalTraffic": ("Retencion", "Retención"),
        "PoorEnvironmentConditions": ("Meteorologia", "Meteorología adversa"),
        "WeatherRelatedRoadConditions": ("Meteorologia", "Meteorología adversa"),
        "NetworkManagement": ("Cortada", "Restricción de circulación"),
    }.get(t, ("Peligro", "Incidencia"))


def instante(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None


def pais_vasco(xml: str, ahora: datetime) -> list[dict]:
    salida = []
    xsi_type = "{http://www.w3.org/2001/XMLSchema-instance}type"
    raiz = ET.fromstring(xml)
    for s in raiz.iter():
        if local(s.tag) != "situation":
            continue
        for r in s:
            if local(r.tag) != "situationRecord":
                continue
            fin = next((instante(e.text or "") for e in r.iter() if local(e.tag) == "overallEndTime"), None)
            if fin and fin < ahora:
                continue
            puntos, via, municipio, direccion = {}, "", "", None
            for e in r.iter():
                n = local(e.tag)
                if n in ("from", "to", "point"):
                    lat = next((float(x.text) for x in e.iter() if local(x.tag) == "latitude" and x.text), None)
                    lon = next((float(x.text) for x in e.iter() if local(x.tag) == "longitude" and x.text), None)
                    if lat is not None and lon is not None:
                        puntos[n] = (lat, lon)
                    for nombre in e.iter():
                        if local(nombre.tag) != "name":
                            continue
                        valor = next((x.text for x in nombre.iter() if local(x.tag) == "value"), "") or ""
                        clase = next((x.text for x in nombre.iter() if local(x.tag) == "tpegDescriptorType"), "")
                        if clase == "linkName" and not via:
                            via = valor
                        elif clase == "townName" and not municipio:
                            municipio = valor
                elif n == "tpegDirection":
                    direccion = e.text
            if not puntos:
                continue
            desde = puntos.get("from") or puntos.get("point") or puntos.get("to")
            hasta = puntos.get("to") or desde
            tipo, titulo = tipo_dtgv(r.get(xsi_type, ""))
            carriles = next((e.text for e in r.iter() if local(e.tag) == "numberOfLanesRestricted"), None)
            salida.append({
                "id": "dtgv-" + r.get("id", ""), "tipo": tipo, "titulo": titulo,
                "detalle": f"{carriles} carril{'es' if carriles != '1' else ''} cortado{'s' if carriles != '1' else ''}" if carriles else "",
                "via": via, "pkDesde": None, "pkHasta": None,
                "lat": desde[0], "lon": desde[1], "latHasta": hasta[0], "lonHasta": hasta[1],
                "rumbo": RUMBOS.get(direccion or ""), "ambos": direccion in (None, "unknown", "bothWays"),
                "municipio": municipio, "fuente": "Gobierno Vasco",
            })
    return salida


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--sct", type=Path)
    a.add_argument("--dtgv", type=Path)
    a.add_argument("--salida", type=Path, required=True)
    o = a.parse_args()
    todas = []
    if o.sct and o.sct.exists():
        try:
            todas += cataluna(o.sct.read_text(encoding="utf-8", errors="replace"))
        except ET.ParseError as e:
            print(f"Cataluña ilegible: {e}", file=sys.stderr)
    if o.dtgv and o.dtgv.exists():
        try:
            todas += pais_vasco(o.dtgv.read_text(encoding="utf-8", errors="replace"), datetime.now(timezone.utc))
        except ET.ParseError as e:
            print(f"País Vasco ilegible: {e}", file=sys.stderr)
    datos = {"fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"), "incidencias": todas}
    with gzip.open(o.salida, "wt", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
    print(f"incidencias regionales: {len(todas)} · {o.salida.stat().st_size} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
