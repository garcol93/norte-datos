import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from radar_movil import Grafo, normal_ref, trazar  # noqa: E402
from sondeo_cartociudad import coincide  # noqa: E402


class RadarMovilTest(unittest.TestCase):
    def test_ref(self):
        self.assertEqual(normal_ref("cm 220"), normal_ref("CM-220"))
        self.assertNotEqual(normal_ref("CM-2120"), normal_ref("CM-220"))

    def test_coincidencia_exacta_y_provincia(self):
        c = {"address": "CM-220 km 35 (Tarazona de la Mancha)", "province": "Albacete"}
        self.assertTrue(coincide(c, "CM-220", 35, "Albacete"))
        self.assertFalse(coincide(c, "CM-220", 35, "Cuenca"))
        self.assertFalse(coincide({"address": "CM-2120 km 35", "province": "Albacete"}, "CM-220", 35, "Albacete"))

    def test_traza_por_la_carretera(self):
        # Carretera en L: 0,0 → 0,0.01 → 0.01,0.01 (≈ 1,1 km + 1,1 km)
        lineas = [[(0.0, 0.0), (0.0, 0.005), (0.0, 0.01)], [(0.0, 0.01), (0.005, 0.01), (0.01, 0.01)]]
        puntos, aprox = trazar(Grafo(lineas), (0.0, 0.0), (0.01, 0.01), 2200)
        self.assertFalse(aprox)
        self.assertEqual(puntos[0], (0.0, 0.0))
        self.assertEqual(puntos[-1], (0.01, 0.01))
        self.assertIn((0.0, 0.01), puntos)

    def test_une_trozos_cortados_por_una_rotonda(self):
        # Dos trozos de la misma carretera separados ~100 m (rotonda sin «ref»)
        lineas = [[(0.0, 0.0), (0.0, 0.01)], [(0.0, 0.0109), (0.0, 0.02)]]
        g = Grafo(lineas)
        self.assertEqual(g.puentes, 1)
        puntos, aprox = trazar(g, (0.0, 0.0), (0.0, 0.02), 2200)
        self.assertFalse(aprox)

    def test_no_une_trozos_lejanos(self):
        g = Grafo([[(0.0, 0.0), (0.0, 0.01)], [(0.0, 0.02), (0.0, 0.03)]])
        self.assertEqual(g.puentes, 0)

    def test_sin_carretera_cerca_linea_recta(self):
        puntos, aprox = trazar(Grafo([[(1.0, 1.0), (1.0, 1.01)]]), (0.0, 0.0), (0.01, 0.01), 2200)
        self.assertTrue(aprox)
        self.assertEqual(puntos, [(0.0, 0.0), (0.01, 0.01)])


if __name__ == "__main__":
    unittest.main()
