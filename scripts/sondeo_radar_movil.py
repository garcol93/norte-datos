#!/usr/bin/env python3
"""Sondeo: ¿se pueden situar los tramos de radar móvil del PDF de la DGT?

Lee el informe «INFORME_CINEMOMETROS…pdf» de la DGT (provincia, carretera,
tipo, km inicial - km final, sentido) y mide cuántos tramos móviles tienen
hitos kilométricos de OSM (highway=milestone) cerca de sus dos extremos.
Solo informa; no genera datos para la app.

    python3 sondeo_radar_movil.py informe.pdf hitos.geojsonseq vias.geojsonseq
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict

FILA = re.compile(
    r"^(?P<prov>[A-ZÁÉÍÓÚÑÜa-záéíóúñü�' .\-/]+?)\s+(?P<via>[A-Z]{1,3}-?\d{1,4}[A-Z]?)\s+(?:Radar\s+)?(?P<tipo>M[oó]vil|Fijo|Tramo)\s+"
    r"(?P<ini>\d+(?:[.,]\d+)?)(?:\s*-\s*(?P<fin>\d+(?:[.,]\d+)?))?\s*(?P<resto>.*)$",
    re.I,
)


def num(t: str) -> float:
    return float(t.replace(",", "."))


def ref_normal(r: str) -> str:
    r = r.upper().replace(" ", "")
    m = re.match(r"^([A-Z]+)-?(\d+[A-Z]?)$", r)
    return f"{m.group(1)}-{m.group(2)}" if m else r


def leer_pdf(ruta: str) -> tuple[list[dict], list[str]]:
    import pdfplumber

    filas, raras = [], []
    with pdfplumber.open(ruta) as pdf:
        for pagina in pdf.pages:
            for linea in (pagina.extract_text() or "").splitlines():
                linea = linea.strip()
                m = FILA.match(linea)
                if m:
                    filas.append({
                        "prov": m["prov"].strip(), "via": ref_normal(m["via"]), "tipo": m["tipo"].lower().replace("ó", "o"),
                        "ini": num(m["ini"]), "fin": num(m["fin"]) if m["fin"] else None, "resto": m["resto"].strip(),
                    })
                elif linea and not linea.upper().startswith("PROVINCIA"):
                    raras.append(linea)
    return filas, raras


def dist(lat1, lon1, lat2, lon2):
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371000 * math.hypot(x, y)


def hitos_por_via(hitos_geo: str, vias_geo: str) -> dict[str, list[tuple[float, float, float]]]:
    """ref -> [(km, lat, lon)]. La ref sale del propio hito o de la vía con ref más cercana (≤ 60 m)."""
    celdas: dict[tuple[int, int], list[tuple[str, list]]] = defaultdict(list)
    with open(vias_geo, encoding="utf-8") as f:
        for linea in f:
            e = json.loads(linea.lstrip("\x1e"))
            ref = (e.get("properties") or {}).get("ref")
            if not ref:
                continue
            refs = [ref_normal(r) for r in ref.split(";")]
            coords = e["geometry"]["coordinates"]
            for lon, lat in coords[:: max(1, len(coords) // 50)] + [coords[-1]]:
                for r in refs:
                    celdas[(int(lon / 0.01), int(lat / 0.01))].append((r, [lat, lon]))
    salida: dict[str, list] = defaultdict(list)
    with open(hitos_geo, encoding="utf-8") as f:
        for linea in f:
            e = json.loads(linea.lstrip("\x1e"))
            p = e.get("properties") or {}
            d = p.get("distance") or p.get("pk") or p.get("name")
            try:
                km = num(str(d).split()[0])
            except (ValueError, IndexError):
                continue
            lon, lat = e["geometry"]["coordinates"]
            refs = [ref_normal(r) for r in str(p.get("ref", "")).split(";") if r]
            if not refs:
                cx, cy = int(lon / 0.01), int(lat / 0.01)
                mejor = None
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for r, (la, lo) in celdas.get((cx + dx, cy + dy), []):
                            dd = dist(lat, lon, la, lo)
                            if dd < 300 and (mejor is None or dd < mejor[0]):
                                mejor = (dd, r)
                if mejor:
                    refs = [mejor[1]]
            for r in refs:
                salida[r].append((km, lat, lon))
    return salida


def main() -> None:
    pdf, hitos_geo, vias_geo = sys.argv[1:4]
    filas, raras = leer_pdf(pdf)
    print(f"filas leídas: {len(filas)} · líneas sin entender: {len(raras)}")
    print("tipos:", dict(Counter(f["tipo"] for f in filas)))
    for r in raras[:25]:
        print("   ?", r[:160])
    moviles = [f for f in filas if f["tipo"].startswith("m") and f["fin"] is not None]
    km_total = sum(abs(f["fin"] - f["ini"]) for f in moviles)
    print(f"tramos móviles con rango: {len(moviles)} · {km_total:.0f} km · provincias: {len({f['prov'] for f in moviles})}")
    print("muestra:", json.dumps(moviles[:5], ensure_ascii=False))
    print("sentidos:", dict(Counter(f["resto"][:20] for f in moviles).most_common(8)))

    hitos = hitos_por_via(hitos_geo, vias_geo)
    print(f"vías con hitos en OSM: {len(hitos)} · hitos: {sum(len(v) for v in hitos.values())}")
    ambos = uno = ninguno = 0
    km_ok = 0.0
    sin_via = Counter()
    for f in moviles:
        lista = hitos.get(f["via"], [])
        def cerca(k):
            return any(abs(h[0] - k) <= 2.0 for h in lista)
        a, b = cerca(f["ini"]), cerca(f["fin"])
        if a and b:
            ambos += 1
            km_ok += abs(f["fin"] - f["ini"])
        elif a or b:
            uno += 1
        else:
            ninguno += 1
            if not lista:
                sin_via[f["via"]] += 1
    n = max(len(moviles), 1)
    print(f"situables con hitos a ≤2 km de los dos extremos: {ambos} ({100*ambos/n:.0f} %), {km_ok:.0f} km")
    print(f"solo un extremo: {uno} ({100*uno/n:.0f} %) · ninguno: {ninguno} ({100*ninguno/n:.0f} %)")
    print("vías sin ningún hito:", sin_via.most_common(20))


if __name__ == "__main__":
    main()
