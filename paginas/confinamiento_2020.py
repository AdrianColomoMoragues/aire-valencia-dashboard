"""Página: efecto del confinamiento de 2020 (ver aire/confinamiento.py)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from aire import confinamiento as cf
from aire import db
from aire.app_utils import datos_o_parar, get_conn
from aire.config import GUIAS_OMS


AZUL, NARANJA, GRIS, GRIS_CLARO = "#2a78d6", "#eb6834", "#898781", "rgba(137,135,129,0.22)"
CONTAMINANTES = ["NO2", "PM10", "PM2.5", "O3"]
VEREDICTO = {"claro": "✅ Efecto claro", "no concluyente": "➖ No concluyente",
             "descriptiva": "ℹ️ Solo descriptiva", "sin datos suficientes": "— Sin datos suficientes"}


@st.cache_data
def cargar(pollutant: str):
    conn = get_conn()
    estaciones = db.list_stations(conn)
    daily = db.daily_means(conn, pollutant, estaciones, "2016-01-01", "2021-12-31", excluir_qc=True)
    return (cf.resumen(daily), cf.serie_semanal(daily, anio=2020),
            cf.serie_semanal(daily, anio=cf.PLACEBO))


datos_o_parar()

st.title("🏠 ¿Cuánto bajó la contaminación con el confinamiento de 2020?")
st.caption("Cada fase de 2020 se compara con las mismas fechas de 2016–2019, con las mismas estaciones, "
           "descontando la variación que ya había antes del 14 de marzo y sin los datos marcados por el "
           "control de calidad. El método se explica al final de la página.")

pollutant = st.selectbox("Contaminante", CONTAMINANTES, index=0)
res, s2020, s2021 = cargar(pollutant)
unidad = GUIAS_OMS[pollutant]["unidad"]

if res["n_estaciones"].fillna(0).eq(0).all():
    st.warning("No hay estaciones con datos suficientes en 2020 y en los años de referencia.")
    st.stop()

# ---- KPIs del confinamiento ------------------------------------------------- #
conf = res.set_index("fase").loc["Confinamiento"]
hib = res.set_index("fase").loc["Hibernación"]
k1, k2, k3 = st.columns(3)
k1.metric("Confinamiento (14 mar–17 may)", f"{conf['efecto']:+.0f} %",
          help="Efecto ajustado: variación frente a 2016–2019 menos la que ya había antes del 14 de marzo.")
k2.metric("Hibernación (30 mar–9 abr)", f"{hib['efecto']:+.0f} %",
          help="Solo trabajadores esenciales: la fase más estricta.")
k3.metric("Veredicto en el confinamiento", VEREDICTO.get(conf["veredicto"], conf["veredicto"]),
          help="Claro = la variación bruta y la ajustada salen del rango de un año normal, todas las "
               "estaciones van en el mismo sentido y 2021 (placebo) no muestra nada parecido.")

st.caption(f"Efecto ajustado. Sin ajustar (variación bruta frente a 2016–2019): "
           f"{conf['variacion_bruta']:+.0f} % en el confinamiento y {hib['variacion_bruta']:+.0f} % "
           f"en la hibernación.")

# ---- Serie semanal ---------------------------------------------------------- #
st.subheader(f"{pollutant} semanal: 2020 frente a 2016–2019")
mostrar_2021 = st.toggle("Mostrar también 2021 (prueba placebo)", value=False)


def _fechas(semanas: pd.Series, anio: int = 2020) -> list[pd.Timestamp]:
    return [pd.Timestamp.fromisocalendar(anio, int(w), 1) for w in semanas]


x = _fechas(s2020["semana"])
fig = go.Figure()
fig.add_trace(go.Scatter(x=x, y=s2020["ref_max"], line=dict(width=0), hoverinfo="skip", showlegend=False))
fig.add_trace(go.Scatter(x=x, y=s2020["ref_min"], fill="tonexty", fillcolor=GRIS_CLARO, line=dict(width=0),
                         name="Rango 2016–2019", hoverinfo="skip"))
fig.add_trace(go.Scatter(x=x, y=s2020["ref_media"], line=dict(color=GRIS, width=2, dash="dot"),
                         name="Media 2016–2019",
                         hovertemplate="%{y:.1f}<extra>Media 2016–2019</extra>"))
if mostrar_2021:
    fig.add_trace(go.Scatter(x=_fechas(s2021["semana"]), y=s2021["anio_valor"],
                             line=dict(color=NARANJA, width=2), name="2021 (placebo)",
                             hovertemplate="%{y:.1f}<extra>2021</extra>"))
fig.add_trace(go.Scatter(x=x, y=s2020["anio_valor"], line=dict(color=AZUL, width=2.5), name="2020",
                         hovertemplate="%{y:.1f}<extra>2020</extra>"))
for nombre, ini, fin, opacidad in [("Confinamiento", "2020-03-14", "2020-05-17", 0.16),
                                   ("Desescalada", "2020-05-18", "2020-06-20", 0.07)]:
    fig.add_vrect(x0=ini, x1=fin, fillcolor=AZUL, opacity=opacidad, line_width=0,
                  annotation_text=nombre, annotation_position="top left",
                  annotation_font=dict(size=11, color=GRIS))
fig.update_layout(height=420, hovermode="x unified", margin=dict(l=10, r=10, t=30, b=10),
                  legend=dict(orientation="h", y=-0.12), yaxis_title=f"{pollutant} ({unidad})",
                  xaxis=dict(tickformat="%b"), yaxis=dict(rangemode="tozero"))
st.plotly_chart(fig, width="stretch", theme="streamlit")
st.caption("Medias semanales de las estaciones con datos en 2020 y en los años de referencia. "
           "La banda gris es el rango entre el año más bajo y el más alto de 2016–2019.")

# ---- Tabla por fases -------------------------------------------------------- #
st.subheader("Efecto por fase")
tabla = pd.DataFrame({
    "Fase": res["fase"],
    "Fechas": res["inicio"].str[3:] + "/" + res["inicio"].str[:2] + " – " + res["fin"].str[3:] + "/"
    + res["fin"].str[:2],
    "Estaciones": res["n_estaciones"],
    "Variación bruta": res["variacion_bruta"].map("{:+.0f} %".format),
    "Efecto ajustado": res["efecto"].map("{:+.0f} %".format),
    "Rango por estación": [f"{a:+.0f} / {b:+.0f} %" for a, b in zip(res["efecto_min"], res["efecto_max"])],
    "Año normal": [f"{a:+.0f} / {b:+.0f} %" for a, b in zip(res["normal_min"], res["normal_max"])],
    "Placebo 2021": res["placebo_efecto"].map("{:+.0f} %".format),
    "Veredicto": res["veredicto"].map(VEREDICTO),
})
st.dataframe(tabla, hide_index=True, width="stretch")

with st.expander("Cómo se calcula y cómo leer la tabla"):
    st.markdown("""
- **Variación bruta:** media de 2020 en la fase frente a la media de las mismas fechas en 2016–2019.
- **Efecto ajustado (diferencia en diferencias):** la variación bruta menos la que ya había entre el
  1 de enero y el 13 de marzo. En 2020 el NO₂ ya estaba un ~20 % por debajo de lo habitual antes del
  confinamiento, y sin este ajuste esa caída se atribuiría al confinamiento.
- **Año normal:** el mismo cálculo con cada año de 2016–2019 frente a los demás. Es el rango de
  variación de un año cualquiera.
- **Placebo 2021:** el mismo cálculo tomando 2021 como si fuera el año del confinamiento. Si también
  saliera un efecto grande, la caída de 2020 no se podría atribuir al confinamiento.
- **Veredicto claro:** la variación bruta y la ajustada salen las dos del rango de un año normal,
  todas las estaciones van en el mismo sentido y el placebo no muestra un efecto parecido.
- **Nueva normalidad:** solo descriptiva. En seis meses se mezclan varias estaciones del año y un
  descenso persistente que también se ve en 2021.

**Meteorología:** en el confinamiento hubo **menos viento** que la media de 2016–2019, lo que suele
*subir* el NO₂, y llovió más, lo que suele *bajar* las partículas. La caída del NO₂ se produjo con una
dispersión desfavorable, así que la estimación es conservadora. En las partículas, la lluvia es una
explicación alternativa.

**Fechas:** estado de alarma desde el 14/03/2020; permiso retribuido recuperable ("hibernación")
del 30/03 al 09/04; la Comunitat Valenciana pasó a fase 1 el 18/05, a fase 2 el 01/06 y a fase 3
el 15/06; nueva normalidad desde el 21/06.
""")
