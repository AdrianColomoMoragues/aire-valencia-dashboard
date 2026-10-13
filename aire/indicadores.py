"""Indicadores diarios comparables con las guías de la OMS."""
from __future__ import annotations

import pandas as pd

from .config import GUIAS_OMS, MIN_HORAS_DIA


def o3_max_8h(hourly: pd.DataFrame) -> pd.DataFrame:
    """Máximo diario de la media móvil de 8 horas para O3, por estación.

    Una media de 8 h solo es válida si tiene al menos 6 valores (75 %).
    """
    out = []
    for est, g in hourly.groupby("estacion"):
        s = g.set_index("fecha_hora")["valor"].asfreq("h")
        m8 = s.rolling(8, min_periods=6).mean()
        daily = m8.resample("D").max().dropna()
        out.append(pd.DataFrame({"estacion": est, "fecha": daily.index, "valor": daily.values}))
    if not out:
        return pd.DataFrame(columns=["estacion", "fecha", "valor"])
    return pd.concat(out, ignore_index=True)


def daily_indicator(pollutant: str, daily: pd.DataFrame, hourly: pd.DataFrame | None = None) -> pd.DataFrame:
    """Devuelve (estacion, fecha, valor) con la métrica que usa la OMS para ese contaminante."""
    if pollutant == "O3":
        if hourly is None:
            raise ValueError("El O3 necesita los datos horarios")
        return o3_max_8h(hourly)
    d = daily[daily["n_horas"] >= MIN_HORAS_DIA]
    return d.rename(columns={"media": "valor"})[["estacion", "fecha", "valor"]]


def exceedance_summary(pollutant: str, indicator: pd.DataFrame) -> pd.DataFrame:
    """Por estación: valor medio, días válidos, días por encima de la guía OMS y %."""
    limit = GUIAS_OMS[pollutant]["valor"]
    g = indicator.groupby("estacion")["valor"]
    res = pd.DataFrame({
        "media": g.mean(),
        "dias_validos": g.size(),
        "dias_sobre_guia": g.apply(lambda s: int((s > limit).sum())),
    })
    res["pct_sobre_guia"] = 100 * res["dias_sobre_guia"] / res["dias_validos"]
    return res.sort_values("media", ascending=False).reset_index()


def serie_diaria_continua(indicator: pd.DataFrame, ventana_dias: int | None = None) -> pd.DataFrame:
    """Prepara (estacion, fecha, valor) para dibujar una línea por estación.

    Rellena con NaN los días sin dato para que el gráfico corte la línea en los
    huecos en vez de unir puntos separados por meses. Si se pide suavizado, la
    media móvil usa una ventana de `ventana_dias` días de calendario, no de filas,
    y necesita al menos 4 días con dato.
    """
    out = []
    for est, g in indicator.groupby("estacion"):
        s = g.set_index("fecha")["valor"].sort_index().asfreq("D")
        if ventana_dias:
            s = s.rolling(f"{ventana_dias}D", min_periods=4).mean().where(s.notna())
        out.append(pd.DataFrame({"estacion": est, "fecha": s.index, "valor": s.values}))
    if not out:
        return pd.DataFrame(columns=["estacion", "fecha", "valor"])
    return pd.concat(out, ignore_index=True)
