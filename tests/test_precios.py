import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


class PreciosTest(unittest.TestCase):
    def test_resumen(self):
        datos = {"Fecha": "04/11/2026 12:50:38", "ListaEESSPrecio": [
            {"Latitud": "39,211417", "Longitud (WGS84)": "-1,539167", "Rótulo": "REPSOL",
             "Precio Gasolina 95 E5": "1,699", "Precio Gasoleo A": "1,839", "Precio Gasolina 98 E10": "1,899"},
            # Sin ningún carburante de los que usa la app: fuera
            {"Latitud": "40,0", "Longitud (WGS84)": "-3,0", "Rótulo": "X", "Precio Adblue": "0,9"},
            {"Latitud": "", "Longitud (WGS84)": "-3,0", "Precio Gasoleo A": "1,5"},
        ]}
        d = Path(tempfile.mkdtemp())
        (d / "e.json").write_text(json.dumps(datos), encoding="utf-8")
        subprocess.run([sys.executable, str(RAIZ / "scripts" / "precios.py"), str(d / "e.json"), str(d / "p.csv.gz")],
                       check=True, capture_output=True)
        lineas = gzip.open(d / "p.csv.gz", "rt", encoding="utf-8").read().splitlines()
        self.assertEqual(lineas[0], "#04/11/2026 12:50:38")
        self.assertEqual(lineas[1:], ["39.21142;-1.53917;Repsol;1699;1899;1839;;"])


if __name__ == "__main__":
    unittest.main()
