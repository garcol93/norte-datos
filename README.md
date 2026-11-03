# norte-datos

Datos abiertos para **Norte** (navegación offline para radios de coche Android): mapas por país, radares y catálogo de versiones. Aquí solo hay datos y los scripts que los generan; el código de la app es privado.

## Fuentes y licencias
- Radares fijos y de tramo: DGT, Punto de Acceso Nacional (https://nap.dgt.es). Datos abiertos; se cita la fuente.
- Mapas y radares de Cataluña y País Vasco: © OpenStreetMap contributors (ODbL).

## Scripts
- `scripts/radares_dgt.py`: convierte el inventario DATEX II de la DGT a GeoJSON.

Pruebas: `python3 -m unittest discover -s tests`
