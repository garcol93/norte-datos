import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from osm_radares import asignar_limites, en_zona, limite_de_via, parsear_maxspeed, radares_osm  # noqa: E402


def secuencia(entidades):
    f = tempfile.NamedTemporaryFile("w", suffix=".geojsonseq", delete=False, encoding="utf-8")
    for e in entidades:
        f.write("\x1e" + json.dumps(e) + "\n")
    f.close()
    return Path(f.name)


def via(coords, **tags):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": tags}


def radar_fijo(lon, lat):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"id": "dgt:x", "tipo": "fijo", "limite": None}}


class MaxspeedTest(unittest.TestCase):
    def test_valores(self):
        self.assertEqual(parsear_maxspeed("120"), 120)
        self.assertEqual(parsear_maxspeed("ES:urban"), 50)
        self.assertEqual(parsear_maxspeed("ES:rural"), 90)
        self.assertEqual(parsear_maxspeed("30 mph"), 48)
        self.assertIsNone(parsear_maxspeed("none"))
        self.assertIsNone(parsear_maxspeed("signals"))
        self.assertIsNone(parsear_maxspeed(None))

    def test_sentidos_y_generico(self):
        self.assertEqual(limite_de_via({"maxspeed:forward": "100", "maxspeed:backward": "80"}), (80, True))
        self.assertEqual(limite_de_via({"highway": "motorway"}), (120, False))
        self.assertEqual(limite_de_via({"highway": "footway"}), (None, False))


class LimitesTest(unittest.TestCase):
    def test_elige_la_via_mas_cercana(self):
        # Radar en (-3.7, 40.0); autovía a ~10 m al norte con 120 y vía de servicio a ~30 m al sur con 50
        vias = secuencia([
            via([[-3.71, 40.00009], [-3.69, 40.00009]], highway="motorway", maxspeed="120"),
            via([[-3.71, 39.99973], [-3.69, 39.99973]], highway="secondary", maxspeed="50"),
            via([[-3.71, 40.01], [-3.69, 40.01]], highway="primary", maxspeed="70"),
        ])
        radares = [radar_fijo(-3.7, 40.0)]
        estad = asignar_limites(radares, vias)
        self.assertEqual(radares[0]["properties"]["limite"], 120)
        self.assertEqual(estad["exactos"], 1)

    def test_sin_maxspeed_queda_aproximado(self):
        vias = secuencia([via([[-3.71, 40.0001], [-3.69, 40.0001]], highway="trunk")])
        radares = [radar_fijo(-3.7, 40.0)]
        asignar_limites(radares, vias)
        p = radares[0]["properties"]
        self.assertIsNone(p["limite"])
        self.assertEqual(p["limite_aprox"], 100)

    def test_lejos_no_asigna(self):
        vias = secuencia([via([[-3.71, 40.002], [-3.69, 40.002]], highway="motorway", maxspeed="120")])
        radares = [radar_fijo(-3.7, 40.0)]
        estad = asignar_limites(radares, vias)
        self.assertIsNone(radares[0]["properties"]["limite"])
        self.assertEqual(estad["sin_limite"], 1)


class ZonasTest(unittest.TestCase):
    zona = {"type": "Feature", "properties": {"id": "cataluna"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 40], [3, 40], [3, 43], [0, 43], [0, 40]]]}}

    def test_en_zona(self):
        self.assertEqual(en_zona([self.zona], 2.17, 41.38), "cataluna")
        self.assertIsNone(en_zona([self.zona], -3.7, 40.4))

    def test_radares_osm_solo_dentro(self):
        camaras = secuencia([
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.17, 41.38]},
             "properties": {"@id": 123, "highway": "speed_camera", "maxspeed": "80"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-3.7, 40.4]},
             "properties": {"@id": 456, "highway": "speed_camera"}},
        ])
        osm = radares_osm(camaras, [self.zona])
        self.assertEqual(len(osm), 1)
        self.assertEqual(osm[0]["properties"]["id"], "osm:123")
        self.assertEqual(osm[0]["properties"]["limite"], 80)


if __name__ == "__main__":
    unittest.main()
