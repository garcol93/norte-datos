#!/usr/bin/env python3
"""Recorridos grabados para el modo de simulación de Norte.

Elige radares reales y construye un recorrido por carreteras reales de
OpenStreetMap (encadenando vías) que pasa por ellos:

- «Radar fijo en autovía»: unos 3 km antes del radar y 1 km después.
- «Radar en la calzada contraria»: el mismo tramo por la otra calzada (no
  debe avisar).
- «Radar de tramo»: desde 1,5 km antes del inicio hasta pasado el final.
- «Cataluña»: un radar de OSM en Cataluña (mensaje «Solo OpenStreetMap»).

Uso:
    python3 scripts/simulaciones.py --dgt build/dgt.geojson --osm build/osm.geojson \\
        --vias vias.geojsonseq --salida build/simulaciones.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from osm_radares import diferencia_angulo, distancia_a_segmento, leer_secuencia, rumbo_segmento, sentido_unico  # noqa: E402

RADIO_BUSQUEDA_M = 6000
VIAS_PRINCIPALES = {"motorway", "trunk", "motorway_link", "trunk_link", "primary"}


def metros(a, b) -> float:
    lat0 = math.radians((a[1] + b[1]) / 2)
    return math.hypot((b[0] - a[0]) * 111_320 * math.cos(lat0), (b[1] - a[1]) * 110_540)


def longitud(puntos) -> float:
    return sum(metros(a, b) for a, b in zip(puntos, puntos[1:]))


class Grafo:
    """Vías en el sentido de marcha cerca de los radares, unidas por cualquier vértice común."""

    def __init__(self):
        self.vias: list[list[list[float]]] = []
        self.tipo: list[str] = []
        self.por_vertice: dict[tuple, list[tuple[int, int]]] = {}

    def anadir(self, coords, tags):
        sentido = sentido_unico(tags)
        if sentido == -1:
            coords = list(reversed(coords))
        # Las de doble sentido se añaden en los dos sentidos
        variantes = [coords] if sentido != 0 else [coords, list(reversed(coords))]
        for c in variantes:
            i = len(self.vias)
            self.vias.append(c)
            self.tipo.append(tags.get("highway", ""))
            for k, p in enumerate(c):
                self.por_vertice.setdefault(tuple(p), []).append((i, k))

    def mas_cercana(self, p, rumbo=None, excluir_rumbo=None):
        """(vía, índice de tramo) más cercana a p, opcionalmente con un rumbo dado."""
        mejor = None
        for i, c in enumerate(self.vias):
            if self.tipo[i] not in VIAS_PRINCIPALES:
                continue
            for k, (a, b) in enumerate(zip(c, c[1:])):
                d = distancia_a_segmento(p, a, b)
                if d > 80:
                    continue
                r = rumbo_segmento(a, b)
                if rumbo is not None and diferencia_angulo(r, rumbo) > 45:
                    continue
                if excluir_rumbo is not None and diferencia_angulo(r, excluir_rumbo) < 135:
                    continue
                if mejor is None or d < mejor[0]:
                    mejor = (d, i, k)
        return None if mejor is None else (mejor[1], mejor[2])

    def continuar(self, via: int, vertice: int, adelante: bool):
        """(vía, vértice) por donde seguir desde ese vértice, con el menor giro.

        Hacia delante busca vías que pasen por el vértice y sigan después; hacia
        atrás, vías que lleguen a él. Así se unen también empalmes a mitad de vía.
        """
        c = self.vias[via]
        p = c[vertice]
        if adelante:
            rumbo = rumbo_segmento(c[vertice - 1], p) if vertice > 0 else rumbo_segmento(p, c[vertice + 1])
        else:
            rumbo = rumbo_segmento(p, c[vertice + 1]) if vertice + 1 < len(c) else rumbo_segmento(c[vertice - 1], p)
        mejor = None
        for j, k in self.por_vertice.get(tuple(p), []):
            if j == via:
                continue
            otra = self.vias[j]
            if adelante and k + 1 < len(otra):
                giro = diferencia_angulo(rumbo_segmento(otra[k], otra[k + 1]), rumbo)
            elif not adelante and k > 0:
                giro = diferencia_angulo(rumbo_segmento(otra[k - 1], otra[k]), rumbo)
            else:
                continue
            if giro > 60:
                continue
            coste = giro + (0 if self.tipo[j] == self.tipo[via] else 30)
            if mejor is None or coste < mejor[0]:
                mejor = (coste, j, k)
        return None if mejor is None else (mejor[1], mejor[2])


def recorrido(grafo: Grafo, via: int, tramo: int, antes_m: float, despues_m: float, hasta=None):
    """Puntos desde [antes_m] antes del tramo dado hasta [despues_m] después (o hasta pasar [hasta])."""
    c = grafo.vias[via]
    atras = list(reversed(c[: tramo + 1]))
    v, k = via, 0
    vistas = {via}
    while longitud(atras) < antes_m:
        sig = grafo.continuar(v, k, adelante=False)
        if sig is None or sig[0] in vistas:
            break
        v, k = sig
        vistas.add(v)
        atras += list(reversed(grafo.vias[v][:k]))
        k = 0  # se sigue hacia atrás desde el primer vértice de esa vía
    delante = c[tramo + 1:]
    v, k = via, len(c) - 1
    vistas = {via}
    recorrido_tras = 0.0
    pasado = hasta is None
    for _ in range(400):
        if not pasado and any(metros(p, hasta) < 60 for p in delante[-80:]):
            pasado = True
            recorrido_tras = longitud(delante)
        if pasado and longitud(delante) - recorrido_tras >= despues_m:
            break
        sig = grafo.continuar(v, k, adelante=True)
        if sig is None or sig[0] in vistas:
            break
        v, k = sig
        vistas.add(v)
        delante += grafo.vias[v][k + 1:]
        k = len(grafo.vias[v]) - 1
    puntos = list(reversed(atras)) + delante
    return [[round(x, 6), round(y, 6)] for x, y in puntos]


def elegir(radares, condicion):
    for r in radares:
        if condicion(r["properties"]):
            return r
    return None


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--dgt", type=Path, required=True)
    a.add_argument("--osm", type=Path, required=True)
    a.add_argument("--vias", type=Path, required=True)
    a.add_argument("--salida", type=Path, required=True)
    o = a.parse_args()

    dgt = json.loads(o.dgt.read_text(encoding="utf-8"))["features"]
    osm = json.loads(o.osm.read_text(encoding="utf-8"))["features"]

    # Radar fijo en autovía con límite exacto y sentido conocido; tramo de 3 a 8 km con límite
    fijo = elegir(dgt, lambda p: p["tipo"] == "fijo" and p.get("limite") and p.get("doble_sentido") is False
                  and p.get("tipo_osm") == "motorway" and (p.get("limite") or 0) >= 100)
    tramo = elegir(dgt, lambda p: p["tipo"] == "tramo" and p.get("limite") and p.get("doble_sentido") is False
                   and 3 <= abs((p.get("pk_fin") or 0) - (p.get("pk_inicio") or 0)) <= 8)
    catalan = elegir(osm, lambda p: p.get("zona") == "cataluna" and p.get("limite") and p.get("doble_sentido") is False)
    elegidos = [r for r in (fijo, tramo, catalan) if r]
    centros = [r["geometry"]["coordinates"] if r["geometry"]["type"] == "Point" else r["geometry"]["coordinates"][0]
               for r in elegidos]

    grafo = Grafo()
    for via in leer_secuencia(o.vias):
        g = via.get("geometry") or {}
        if g.get("type") != "LineString":
            continue
        coords = g["coordinates"]
        if any(metros(coords[0], c) < RADIO_BUSQUEDA_M or metros(coords[-1], c) < RADIO_BUSQUEDA_M for c in centros):
            grafo.anadir(coords, via.get("properties") or {})
    print(f"vías cerca de los radares elegidos: {len(grafo.vias)}", file=sys.stderr)

    salida = []

    def anadir(ident, nombre, descripcion, carretera, kmh, puntos):
        if len(puntos) < 2 or longitud(puntos) < 500:
            print(f"recorrido {ident} descartado (muy corto)", file=sys.stderr)
            return
        salida.append({"id": ident, "nombre": nombre, "descripcion": descripcion, "carretera": carretera,
                       "velocidad_kmh": kmh, "longitud_m": round(longitud(puntos)), "puntos": puntos})

    if fijo:
        p = fijo["properties"]
        pos = fijo["geometry"]["coordinates"]
        ida = grafo.mas_cercana(pos, rumbo=p["rumbo"])
        if ida:
            lim = p["limite"]
            anadir("fijo", "Radar fijo en autovía",
                   f"{p.get('carretera') or 'Autovía'} a {lim + 20} km/h: aviso a la distancia elegida, pitido y límite superado",
                   p.get("carretera"), lim + 20, recorrido(grafo, *ida, 3000, 1000))
        vuelta = grafo.mas_cercana(pos, excluir_rumbo=p["rumbo"])
        if vuelta:
            anadir("contraria", "Radar en la calzada contraria",
                   f"{p.get('carretera') or 'Autovía'} en sentido contrario: no debe avisar",
                   p.get("carretera"), p["limite"], recorrido(grafo, *vuelta, 3000, 1000))
    if tramo:
        p = tramo["properties"]
        ini, fin = tramo["geometry"]["coordinates"][0], tramo["geometry"]["coordinates"][-1]
        ida = grafo.mas_cercana(ini, rumbo=p["rumbo"])
        if ida:
            anadir("tramo", "Radar de tramo",
                   f"{p.get('carretera') or 'Tramo'}: aviso de inicio, velocidad media y fin del tramo",
                   p.get("carretera"), p["limite"] - 5, recorrido(grafo, *ida, 1500, 500, hasta=fin))
    if catalan:
        p = catalan["properties"]
        pos = catalan["geometry"]["coordinates"]
        ida = grafo.mas_cercana(pos, rumbo=p["rumbo"])
        if ida:
            anadir("cataluna", "Cataluña",
                   "Mensaje «Solo OpenStreetMap» y un radar de OpenStreetMap",
                   p.get("carretera"), p["limite"], recorrido(grafo, *ida, 3000, 800))

    o.salida.parent.mkdir(parents=True, exist_ok=True)
    o.salida.write_text(json.dumps({"recorridos": salida}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for r in salida:
        print(f"recorrido {r['id']}: {r['longitud_m']} m, {len(r['puntos'])} puntos, {r['velocidad_kmh']} km/h", file=sys.stderr)


if __name__ == "__main__":
    main()
