import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from simulaciones import Grafo, longitud, recorrido  # noqa: E402

GRADO = 1 / 111_000  # ≈ 1 m en latitud


def norte(desde_m, hasta_m, lon=-3.7):
    return [[lon, 40 + m * GRADO] for m in range(desde_m, hasta_m + 1, 250)]


class RecorridoTest(unittest.TestCase):
    def setUp(self):
        self.g = Grafo()
        # Calzada hacia el norte en tres vías encadenadas y calzada hacia el sur al lado
        self.g.anadir(norte(0, 2000), {"highway": "motorway"})
        self.g.anadir(norte(2000, 4000), {"highway": "motorway"})
        self.g.anadir(norte(4000, 6000), {"highway": "motorway"})
        self.g.anadir(list(reversed(norte(0, 6000, lon=-3.6997))), {"highway": "motorway"})

    def test_encadena_antes_y_despues(self):
        via, tramo = self.g.mas_cercana([-3.7, 40 + 3100 * GRADO], rumbo=0)
        puntos = recorrido(self.g, via, tramo, 2500, 1000)
        self.assertGreater(longitud(puntos), 3400)
        # Va hacia el norte de principio a fin
        self.assertLess(puntos[0][1], puntos[-1][1])

    def test_calzada_contraria(self):
        via, tramo = self.g.mas_cercana([-3.7, 40 + 3100 * GRADO], excluir_rumbo=0)
        puntos = recorrido(self.g, via, tramo, 2000, 1000)
        self.assertGreater(puntos[0][1], puntos[-1][1])  # hacia el sur


if __name__ == "__main__":
    unittest.main()
