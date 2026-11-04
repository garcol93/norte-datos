import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import incidencias_regionales as ir  # noqa: E402

MUESTRAS = RAIZ / "tests" / "fixtures" / "regionales"


class RegionalesTest(unittest.TestCase):
    def test_cataluna(self):
        l = ir.cataluna((MUESTRAS / "sct.xml").read_text(encoding="utf-8"))
        self.assertEqual(len(l), 6)
        tipos = {i["tipo"] for i in l}
        self.assertIn("Obras", tipos)
        self.assertTrue(all(i["via"] and -1 < i["lon"] < 4 and 40 < i["lat"] < 43 for i in l))
        self.assertTrue(any(i["ambos"] for i in l))
        # Textos en castellano
        self.assertTrue(all(i["titulo"] in ("Obras", "Retención", "Accidente", "Calzada cortada", "Vía cortada", "Incidencia", "Meteorología adversa") for i in l))

    def test_pais_vasco_solo_con_coordenadas_y_vigentes(self):
        xml = (MUESTRAS / "dtgv.xml").read_text(encoding="utf-8")
        l = ir.pais_vasco(xml, datetime(2026, 11, 4, 12, tzinfo=timezone.utc))
        self.assertEqual(len(l), 5)
        self.assertTrue(all(42.4 < i["lat"] < 43.5 and -3.5 < i["lon"] < -1.7 for i in l))
        self.assertEqual(l[0]["via"], "N-634")
        # Dentro de diez años, todas las que tienen fin ya han acabado
        futuro = ir.pais_vasco(xml, datetime(2036, 1, 1, tzinfo=timezone.utc))
        self.assertLessEqual(len(futuro), len(l))

    def test_traduccion(self):
        self.assertEqual(ir.traducir("Calçada restringida. Desviaments"), "Calzada restringida. Desvíos")
        self.assertEqual(ir.traducir("Algo nuevo"), "Algo nuevo")


if __name__ == "__main__":
    unittest.main()
