# Guía de mejoras (para hacer tú)

La base ya funciona. Estas mejoras están ordenadas de más fácil a más ambiciosa. Haz al menos 2 o 3 antes de publicar: así el proyecto es tuyo y puedes defenderlo en una entrevista.

## 1. Primeros pasos (imprescindible)
- [x] Ejecuta `python -m aire.etl` con el **dataset real** y revisa los logs: cuántas filas se descartan y por qué. Si algún formato de fecha u hora no se reconoce, ajusta `_parse_date` / `_parse_hour` y añade un test con ese caso.
- [x] Haz una captura o GIF del dashboard, guárdala en `docs/` y enlázala en el README.
- [ ] Despliega en [Streamlit Community Cloud](https://streamlit.io/cloud). *(Preparado: la app crea la base desde `snapshot/mediciones.parquet` al arrancar; falta publicarla.)*

## 2. Análisis (lo que más luce en Ciencia de Datos)
- [x] **Efecto del confinamiento de 2020** (hecho: página `Confinamiento 2020`, `aire/confinamiento.py`): compara NO₂ de marzo a mayo de 2020 con la media de 2016-2019 en las mismas semanas. Añádelo como pestaña con un gráfico de antes y después.
- [ ] **Correlaciones** entre contaminantes y meteorología (el CSV trae viento, temperatura y humedad). Por ejemplo, ¿baja el NO₂ con viento fuerte?
- [ ] **Tendencia** a largo plazo con una descomposición STL (`statsmodels`) para separar tendencia, estacionalidad y ruido.

## 3. Predicción
- [ ] Predice la media diaria de NO₂ de mañana con un modelo sencillo (Prophet, SARIMA o un `GradientBoostingRegressor` con retardos y día de la semana). Muestra la predicción y su intervalo en el dashboard.
- [ ] Evalúalo con validación temporal (`TimeSeriesSplit`), nunca con un split aleatorio.

## 4. Ingeniería
- [ ] Añade la tabla de estaciones con **coordenadas** y un mapa (`px.scatter_mapbox`) coloreado por media.
- [ ] Cambia SQLite por **PostgreSQL** con `docker-compose` (solo cambia `db.connect` y la sintaxis de fechas).
- [ ] Ejecuta el ETL periódicamente con un workflow programado de GitHub Actions.
- [ ] Añade `ruff` al CI para el linting.

## 5. Visualización y calidad de datos (surgidas de la Fase 1)
- [x] **Escala del eje Y**: si la guía OMS supera en más de 3× los datos (CO, SO₂), el eje se ajusta a los datos y la guía se muestra como texto.
- [x] **Control de calidad de sensores** (`aire/calidad.py`): valores atascados, picos aislados (solo aviso) y deriva regional del O₃; se marcan sin borrar y se pueden excluir desde el dashboard.
- [ ] **Comparar en el periodo común** cuando las estaciones tienen periodos distintos (las del puerto).

## Ideas para el commit history
Haz commits pequeños y descriptivos, por ejemplo:
`feat: pestaña confinamiento 2020`, `test: caso hora 24 en ETL`, `docs: captura del dashboard`.
