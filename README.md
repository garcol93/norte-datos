# norte-datos

Datos abiertos para **Norte** (navegación offline para radios de coche Android): mapas por país, radares y catálogo de versiones. Aquí solo hay datos y los scripts que los generan; el código de la app es privado.

## Fuentes y licencias
- Radares fijos y de tramo: DGT, Punto de Acceso Nacional (https://nap.dgt.es). Datos abiertos; se cita la fuente.
- Mapas y radares de Cataluña y País Vasco: © OpenStreetMap contributors (ODbL).

## Scripts
- `scripts/radares_dgt.py`: convierte el inventario DATEX II de la DGT a GeoJSON.
- `scripts/osm_radares.py`: límites de velocidad de OSM para los radares DGT, radares OSM de Cataluña y País Vasco y contornos de esas comunidades.
- `scripts/simulaciones.py`: recorridos reales por radares para el modo de simulación de la app.
- `scripts/catalogo.py`: genera `catalogo.json` (lo que consulta la app) a partir de las releases.
- `scripts/regiones.json`: regiones de mapa descargables.
- `.github/workflows/datos.yml`: radares cada lunes y mapas el día 2 de cada mes (también a mano).

El catálogo está siempre en: https://github.com/garcol93/norte-datos/releases/download/catalogo/catalogo.json

Pruebas: `python3 -m unittest discover -s tests`
