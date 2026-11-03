import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from radares_dgt import parsear  # noqa: E402

MUESTRA = RAIZ / "tests" / "fixtures" / "radares_dgt_muestra.xml"


class RadaresDgtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.radares, cls.publicado = parsear(MUESTRA.read_bytes())
        cls.por_id = {r["properties"]["id"]: r for r in cls.radares}

    def test_cuenta_y_fecha(self):
        self.assertEqual(len(self.radares), 3)
        self.assertEqual(self.publicado, "2025-12-18T09:56:52.406+01:00")

    def test_radar_fijo(self):
        r = self.por_id["dgt:CABINACINEMOMETRO_120001"]
        self.assertEqual(r["geometry"], {"type": "Point", "coordinates": [-1.94488, 41.30326]})
        p = r["properties"]
        self.assertEqual(p["tipo"], "fijo")
        self.assertEqual(p["carretera"], "A-2")
        self.assertEqual(p["pk"], 202.33)
        self.assertEqual(p["sentido"], "creciente")
        self.assertEqual(p["hacia"], "ZARAGOZA")
        self.assertEqual(p["provincia"], "ZARAGOZA")
        self.assertEqual(p["ine"], "50")
        self.assertIsNone(p["limite"])

    def test_tramo_inicio_es_from(self):
        r = self.por_id["dgt:CVM_161274"]
        self.assertEqual(r["geometry"]["type"], "LineString")
        self.assertEqual(r["geometry"]["coordinates"], [[-0.915697, 41.6088], [-0.9496, 41.6192]])
        p = r["properties"]
        self.assertEqual((p["tipo"], p["carretera"], p["pk_inicio"], p["pk_fin"]), ("tramo", "Z-40", 26.6, 29.7))
        self.assertEqual(p["hacia"], "MADRID")

    def test_tramo_decreciente_entre_provincias(self):
        p = self.por_id["dgt:CVM_161340"]["properties"]
        self.assertEqual(p["sentido"], "decreciente")
        self.assertEqual((p["provincia_inicio"], p["provincia_fin"]), ("SEGOVIA", "MADRID"))
        self.assertEqual((p["pk_inicio"], p["pk_fin"]), (56.815, 49.263))
        self.assertIsNone(p["hacia"])
        # El inicio (from) está en Segovia, más al norte que el fin
        inicio, fin = self.por_id["dgt:CVM_161340"]["geometry"]["coordinates"]
        self.assertGreater(inicio[1], fin[1])


if __name__ == "__main__":
    unittest.main()
