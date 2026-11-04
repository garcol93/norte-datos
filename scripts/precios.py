"""Resume los precios de carburantes del Ministerio para la app.

Entrada: el JSON de «EstacionesTerrestres» (≈12 MB, todas las gasolineras de
España). Salida, en una carpeta:
  precios.csv.gz con todos los carburantes (≈175 KB):
    fecha en la primera línea («#04/11/2026 12:50:38»), y luego
    lat;lon;rótulo;g95;g98;diesel;diesel_plus;glp
  precios-<carburante>.csv.gz con uno solo (≈110 KB), para que la radio baje
  solo el de su coche: lat;lon;rótulo;precio
Los precios van en milésimas de euro (1489 = 1,489 €/l); vacío si no lo vende.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

# Carburante de la app → columnas del Ministerio, por orden de preferencia
CARBURANTES = {
    "g95": ["Precio Gasolina 95 E5", "Precio Gasolina 95 E10"],
    "g98": ["Precio Gasolina 98 E5", "Precio Gasolina 98 E10"],
    "diesel": ["Precio Gasoleo A"],
    "diesel_plus": ["Precio Gasoleo Premium"],
    "glp": ["Precio Gases licuados del petróleo"],
}


def numero(texto: str) -> float | None:
    texto = (texto or "").strip().replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def precio(estacion: dict, columnas: list[str]) -> str:
    for c in columnas:
        v = numero(estacion.get(c, ""))
        if v and 0.3 < v < 5:
            return str(round(v * 1000))
    return ""


def resumir(datos: dict) -> list[str]:
    lineas = ["#" + (datos.get("Fecha") or "")]
    for e in datos.get("ListaEESSPrecio", []):
        lat, lon = numero(e.get("Latitud")), numero(e.get("Longitud (WGS84)"))
        if lat is None or lon is None:
            continue
        precios = [precio(e, cols) for cols in CARBURANTES.values()]
        if not any(precios):
            continue
        rotulo = " ".join((e.get("Rótulo") or "").split()).replace(";", ",").title()
        lineas.append(";".join([f"{lat:.5f}", f"{lon:.5f}", rotulo, *precios]))
    return lineas


def escribir(ruta: Path, lineas: list[str]) -> None:
    with gzip.open(ruta, "wt", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print(f"{ruta.name}: {len(lineas) - 1} gasolineras · {ruta.stat().st_size} bytes", file=sys.stderr)


def main() -> None:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("entrada", type=Path)
    a.add_argument("salida", type=Path, help="carpeta de salida")
    o = a.parse_args()
    datos = json.loads(o.entrada.read_text(encoding="utf-8-sig"))
    lineas = resumir(datos)
    o.salida.mkdir(parents=True, exist_ok=True)
    escribir(o.salida / "precios.csv.gz", lineas)
    # Un archivo por carburante, solo con las gasolineras que lo venden
    for i, clave in enumerate(CARBURANTES):
        solo = [lineas[0]]
        for l in lineas[1:]:
            c = l.split(";")
            if c[3 + i]:
                solo.append(";".join(c[:3] + [c[3 + i]]))
        escribir(o.salida / f"precios-{clave}.csv.gz", solo)


if __name__ == "__main__":
    main()
