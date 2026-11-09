import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import datetime as dt  # noqa: E402

from zbe import nombre_de, vigente, zona  # noqa: E402


def cuadrado(lon, lat, lado=0.01, **tags):
    c = [[lon, lat], [lon + lado, lat], [lon + lado, lat + lado], [lon, lat + lado], [lon, lat]]
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [c]},
            "properties": {"boundary": "low_emission_zone", **tags}}


class ZbeTest(unittest.TestCase):
    def test_nombre(self):
        self.assertEqual(nombre_de({"name": "ZBE Madrid", "name:es": "Madrid ZBE"}), "Madrid ZBE")
        self.assertEqual(nombre_de({}), "Zona de bajas emisiones")

    def test_zona_con_reglas_y_nota(self):
        z = zona(cuadrado(-3.7, 40.4, name="ZBE Distrito Centro", note="Etiquetas B y C con restricciones",
                          **{"@id": 123, "motor_vehicle:conditional": "no @ (emission_class=none)"}))
        p = z["properties"]
        self.assertEqual(p["nombre"], "ZBE Distrito Centro")
        self.assertEqual(p["id"], "zbe-123")
        self.assertIn("motor_vehicle:conditional", p["reglas"])
        self.assertEqual(p["nota"], "Etiquetas B y C con restricciones")
        self.assertEqual(z["geometry"]["type"], "Polygon")

    def test_nombre_generico_se_salta(self):
        self.assertEqual(nombre_de({"name:es": "Zona de Bajas Emisiones", "name": "Emisio Gutxiko Ermua"}), "Emisio Gutxiko Ermua")

    def test_vigente(self):
        hoy = dt.date(2026, 11, 9)
        self.assertTrue(vigente({"start_date": "2025"}, hoy))
        self.assertFalse(vigente({"start_date": "2028"}, hoy))
        self.assertFalse(vigente({"opening_date": "2027-01-01"}, hoy))
        self.assertFalse(vigente({"status": "supended"}, hoy))
        self.assertTrue(vigente({}, hoy))

    def test_descarta_lo_que_no_es_zbe_o_vacio(self):
        self.assertIsNone(zona(cuadrado(0, 0, boundary="administrative")))
        self.assertIsNone(zona(cuadrado(0, 0, lado=0)))


if __name__ == "__main__":
    unittest.main()
