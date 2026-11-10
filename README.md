# norte-datos

Datos abiertos para **Norte** (navegación offline para radios de coche Android): mapas por país, radares y catálogo de versiones. Aquí solo hay datos y los scripts que los generan; el código de la app es privado.

## Fuentes y licencias
- Radares fijos y de tramo: DGT, Punto de Acceso Nacional (https://nap.dgt.es). Datos abiertos; se cita la fuente.
- Zonas de posible radar móvil: tramos de la DGT (informe «Equipos y tramos de vigilancia» de dgt.es), situados con CartoCiudad © IGN/CNIG (CC BY 4.0) y trazados sobre OpenStreetMap (ODbL).
- Mapas, radares de Cataluña y País Vasco y zonas de bajas emisiones: © OpenStreetMap contributors (ODbL).

## Scripts
- `scripts/radares_dgt.py`: convierte el inventario DATEX II de la DGT a GeoJSON.
- `scripts/osm_radares.py`: límites de velocidad de OSM para los radares DGT, radares OSM de Cataluña y País Vasco y contornos de esas comunidades.
- `scripts/simulaciones.py`: recorridos reales por radares para el modo de simulación de la app.
- `scripts/busqueda.py`: índice de búsqueda sin internet (SQLite FTS4) de poblaciones, calles, sitios y portales.
- `scripts/radar_movil.py`: zonas de posible radar móvil (PDF de la DGT, puntos kilométricos de CartoCiudad con caché `movil-cache.json` y trazado por la carretera de OSM).
- `scripts/zbe.py`: zonas de bajas emisiones de OSM (contorno simplificado, nombre y reglas tal cual).
- `scripts/catalogo.py`: genera `catalogo.json` (lo que consulta la app) a partir de las releases.
- `scripts/regiones.json`: regiones de mapa descargables.
- `.github/workflows/datos.yml`: radares cada lunes y mapas el día 2 de cada mes (también a mano).

El catálogo está siempre en: https://github.com/garcol93/norte-datos/releases/download/catalogo/catalogo.json

Pruebas: `python3 -m unittest discover -s tests`
