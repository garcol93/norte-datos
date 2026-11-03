import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def seq(entidades):
    f = tempfile.NamedTemporaryFile("w", suffix=".geojsonseq", delete=False, encoding="utf-8")
    for e in entidades:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    f.close()
    return f.name


def punto(lon, lat, **tags):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": tags}


def linea(coords, **tags):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": tags}


class BusquedaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        salida = Path(tempfile.mkdtemp()) / "b.sqlite"
        subprocess.run([
            sys.executable, str(RAIZ / "scripts" / "busqueda.py"),
            "--poblaciones", seq([
                punto(-4.7245, 41.6523, place="city", name="Valladolid"),
                punto(-4.75, 41.66, place="suburb", name="Huerta del Rey"),
                punto(-3.7038, 40.4168, place="city", name="Madrid"),
            ]),
            "--calles", seq([
                linea([[-4.7240, 41.6520], [-4.7235, 41.6525]], highway="residential", name="Calle Mayor"),
                linea([[-3.7040, 40.4170], [-3.7035, 40.4172]], highway="residential", name="Calle Mayor"),
                linea([[-3.7040, 40.4180], [-3.7035, 40.4182]], highway="residential", name="Calle de Alcalá"),
            ]),
            "--sitios", seq([punto(-4.73, 41.65, amenity="fuel", brand="Repsol")]),
            "--portales", seq([punto(-4.7238, 41.6522, **{"addr:street": "Calle Mayor", "addr:housenumber": "12"})]),
            "--salida", str(salida),
        ], check=True, capture_output=True)
        cls.db = sqlite3.connect(salida)

    def buscar(self, consulta):
        return self.db.execute(
            "SELECT l.nombre, l.municipio, l.tipo FROM buscar b JOIN lugares l ON l.id = b.docid WHERE buscar MATCH ?",
            (consulta,)).fetchall()

    def test_calle_por_municipio(self):
        r = self.buscar("mayor valladolid")
        self.assertEqual(r, [("Calle Mayor", "Valladolid", 1)])

    def test_sin_tildes_y_prefijo(self):
        self.assertEqual(self.buscar("alcal*"), [("Calle de Alcalá", "Madrid", 1)])
        self.assertEqual(self.buscar("alcala"), [("Calle de Alcalá", "Madrid", 1)])

    def test_barrio_tiene_municipio(self):
        self.assertIn(("Huerta del Rey", "Valladolid", 0), self.buscar("huerta"))

    def test_sitio_y_portal(self):
        self.assertIn(("Repsol", "Valladolid", 2), self.buscar("repsol"))
        n = self.db.execute("SELECT numero FROM portales p JOIN lugares l ON l.id = p.calle WHERE l.municipio = 'Valladolid'").fetchall()
        self.assertEqual(n, [("12",)])


if __name__ == "__main__":
    unittest.main()
