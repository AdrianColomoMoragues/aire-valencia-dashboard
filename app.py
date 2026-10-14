"""Dashboard de calidad del aire de València (Streamlit).

Ejecuta primero el ETL (`python -m aire.etl` o `python -m aire.etl --sample`)
y después: `streamlit run app.py`
"""
from __future__ import annotations

from datetime import date

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from aire import db
from aire.config import DATASET_PAGE, DB_PATH, GUIAS_OMS
from aire.indicadores import (
    daily_indicator,
    exceedance_summary,
    guia_en_escala,
    serie_diaria_continua,
    texto_guia_fuera_de_escala,
)

st.set_page_config(page_title="Calidad del aire · València", page_icon="🌬️", layout="wide")

# Colores fijos por estación (el color sigue a la estación, no a su posición en el ranking).
# 10 colores = 10 estaciones con contaminantes en el dataset real (validado para daltonismo).
PALETA = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
          "#8a5a00", "#0091b3"]
DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


@st.cache_resource
def get_conn():
    return db.connect(DB_PATH)


@st.cache_data
def catalog():
    conn = get_conn()
    return db.list_stations(conn), db.list_pollutants(conn), db.date_range(conn)


@st.cache_data
def load(pollutant: str, stations: tuple[str, ...], start: str, end: str, excluir_qc: bool = False):
    conn = get_conn()
    est = list(stations)
    daily = db.daily_means(conn, pollutant, est, start, end, excluir_qc)
    hourly = db.hourly_values(conn, pollutant, est, start, end, excluir_qc) if pollutant == "O3" else None
    profile = db.weekly_profile(conn, pollutant, est, start, end, excluir_qc)
    return daily, hourly, profile


@st.cache_data
def load_flags(pollutant: str, stations: tuple[str, ...], start: str, end: str):
    return db.quality_flags(get_conn(), pollutant, list(stations), start, end)


# --------------------------------------------------------------------------- #
if not DB_PATH.exists():
    st.error("No encuentro la base de datos. Ejecuta antes `python -m aire.etl` "
             "(o `python -m aire.etl --sample` para datos sintéticos).")
    st.stop()

stations, pollutants, (dmin, dmax) = catalog()
color_map = {s: PALETA[i % len(PALETA)] for i, s in enumerate(stations)}

st.title("🌬️ Calidad del aire en València")
st.caption(f"Datos horarios de la RVVCCA · [fuente]({DATASET_PAGE}) · licencia CC BY 4.0")

# Filtros en una sola fila
c1, c2, c3 = st.columns([1, 3, 2])
default_pol = "NO2" if "NO2" in pollutants else pollutants[0]
pollutant = c1.selectbox("Contaminante", pollutants, index=pollutants.index(default_pol))
selected = c2.multiselect("Estaciones", stations, default=stations[:4])
rango = c3.date_input(
    "Periodo",
    value=(date.fromisoformat(dmin), date.fromisoformat(dmax)),
    min_value=date.fromisoformat(dmin),
    max_value=date.fromisoformat(dmax),
)
if not selected or not isinstance(rango, tuple) or len(rango) != 2:
    st.info("Elige al menos una estación y un periodo completo.")
    st.stop()

start, end = (d.isoformat() for d in rango)
flags = load_flags(pollutant, tuple(selected), start, end)
horas_excluibles = int(flags.loc[flags["excluir"] == 1, "n_horas"].sum())
excluir_qc = st.toggle(
    f"Excluir datos sospechosos del control de calidad ({horas_excluibles:,} h en esta selección)",
    value=False, disabled=horas_excluibles == 0,
    help="Quita las horas con valores atascados (≥ 12 h iguales) y las derivas del O₃. "
         "Los picos aislados solo se avisan: pueden ser eventos reales, como la Cremà.",
)
daily, hourly, profile = load(pollutant, tuple(selected), start, end, excluir_qc)
if daily.empty:
    st.warning("No hay datos para esa combinación de filtros.")
    st.stop()

guia = GUIAS_OMS[pollutant]
indicator = daily_indicator(pollutant, daily, hourly)
summary = exceedance_summary(pollutant, indicator)

# ---- KPIs ------------------------------------------------------------------ #
k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Media del periodo ({guia['unidad']})", f"{indicator['valor'].mean():.1f}")
k2.metric("Peor día", f"{indicator['valor'].max():.1f}",
          help=f"Máximo de la métrica OMS ({guia['metrica']})")
k3.metric("Días sobre la guía OMS", int(summary["dias_sobre_guia"].sum()),
          help="Sumando todas las estaciones seleccionadas")
k4.metric("% de días sobre la guía",
          f"{100 * summary['dias_sobre_guia'].sum() / summary['dias_validos'].sum():.1f} %")

# ---- Serie temporal -------------------------------------------------------- #
st.subheader("Evolución diaria")
suavizar = st.toggle("Suavizar (media móvil de 7 días)", value=True)
plot_df = serie_diaria_continua(indicator, ventana_dias=7 if suavizar else None)
fig = px.line(plot_df, x="fecha", y="valor", color="estacion", color_discrete_map=color_map,
              labels={"fecha": "", "valor": f"{pollutant} ({guia['unidad']})", "estacion": "Estación"})
max_linea = plot_df["valor"].max()
if guia_en_escala(guia["valor"], max_linea):
    fig.add_hline(y=guia["valor"], line_dash="dash", line_color="#898781", line_width=1.5,
                  annotation_text=f"Guía OMS: {guia['valor']} ({guia['metrica']})",
                  annotation_position="top left")
else:
    # La guía aplastaría las series: el eje se ajusta a los datos y la guía va como texto.
    fig.update_yaxes(rangemode="tozero")
    fig.add_annotation(xref="paper", yref="paper", x=0, y=1.06, showarrow=False,
                       xanchor="left", font=dict(size=12, color="#898781"),
                       text="⬆ " + texto_guia_fuera_de_escala(guia["valor"], guia["unidad"],
                                                              guia["metrica"], max_linea))
fig.update_traces(line_width=2)
fig.update_layout(hovermode="x unified", legend_title_text="", height=420,
                  margin=dict(l=10, r=10, t=30, b=10))
st.plotly_chart(fig, width="stretch", theme="streamlit")

# ---- Ranking + perfil semanal --------------------------------------------- #
left, right = st.columns(2)

with left:
    st.subheader("Comparativa entre estaciones")
    bar = px.bar(summary.sort_values("media"), x="media", y="estacion", orientation="h",
                 color="estacion", color_discrete_map=color_map,
                 labels={"media": f"Media ({guia['unidad']})", "estacion": ""},
                 hover_data={"dias_sobre_guia": True, "pct_sobre_guia": ":.1f"})
    max_barra = summary["media"].max()
    if guia_en_escala(guia["valor"], max_barra):
        bar.add_vline(x=guia["valor"], line_dash="dash", line_color="#898781", line_width=1.5)
        margen_sup = 10
    else:
        bar.add_annotation(xref="paper", yref="paper", x=1, y=1.02, showarrow=False,
                           xanchor="right", yanchor="bottom", font=dict(size=12, color="#898781"),
                           text="➡ " + texto_guia_fuera_de_escala(guia["valor"], guia["unidad"],
                                                                  guia["metrica"], max_barra))
        margen_sup = 30
    bar.update_layout(showlegend=False, height=380, margin=dict(l=10, r=10, t=margen_sup, b=10))
    st.plotly_chart(bar, width="stretch", theme="streamlit")

with right:
    st.subheader("¿Cuándo se contamina más?")
    pivot = profile.pivot(index="dia_semana", columns="hora", values="media").reindex(range(7))
    heat = go.Figure(go.Heatmap(
        z=pivot.values, x=pivot.columns, y=DIAS, colorscale="Blues",
        colorbar=dict(title=guia["unidad"]),
        hovertemplate="%{y} %{x}:00h<br>%{z:.1f}<extra></extra>",
        xgap=2, ygap=2,
    ))
    heat.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                       xaxis_title="Hora del día", yaxis_autorange="reversed")
    st.plotly_chart(heat, width="stretch", theme="streamlit")

# ---- Control de calidad ---------------------------------------------------- #
REGLAS = {"valor_atascado": "Valor atascado", "pico_aislado": "Pico aislado",
          "deriva_regional": "Deriva respecto al resto"}
with st.expander(f"Control de calidad · {len(flags)} incidencias en esta selección"):
    if flags.empty:
        st.write("Ninguna regla ha marcado datos de este contaminante en la selección.")
    else:
        st.caption("Las incidencias se marcan pero no se borran. **Excluible** = se quita al activar "
                   "el interruptor de arriba; **aviso** = solo informativo (puede ser un evento real).")
        st.dataframe(
            flags.assign(regla=flags["regla"].map(REGLAS),
                         accion=flags["excluir"].map({1: "Excluible", 0: "Aviso"}))
                 .rename(columns={"estacion": "Estación", "regla": "Regla", "inicio": "Inicio",
                                  "fin": "Fin", "n_horas": "Horas", "accion": "Acción",
                                  "detalle": "Detalle"})
                 [["Estación", "Regla", "Inicio", "Fin", "Horas", "Acción", "Detalle"]],
            hide_index=True, width="stretch",
        )

# ---- Tabla ----------------------------------------------------------------- #
with st.expander("Ver tabla resumen por estación"):
    st.dataframe(
        summary.rename(columns={
            "estacion": "Estación", "media": f"Media ({guia['unidad']})",
            "dias_validos": "Días válidos", "dias_sobre_guia": "Días > guía OMS",
            "pct_sobre_guia": "% días > guía",
        }).round(1),
        hide_index=True, width="stretch",
    )
    st.download_button("Descargar CSV", indicator.to_csv(index=False).encode(),
                       file_name=f"{pollutant}_{start}_{end}.csv", mime="text/csv")
