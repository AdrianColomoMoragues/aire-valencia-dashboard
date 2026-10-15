"""Efecto del confinamiento de 2020 sobre la calidad del aire.

Método
------
1. **Misma época del año.** Cada fase de 2020 se compara con las mismas fechas
   de los años de referencia (2016–2019), porque la contaminación tiene un ciclo
   anual muy marcado.
2. **Mismas estaciones.** Solo entran las estaciones con datos en 2020 y en al
   menos 3 de los 4 años de referencia, tanto en la fase como en el periodo previo.
3. **Diferencia en diferencias.** A la variación de cada fase se le descuenta la
   del periodo previo (1 ene–13 mar). En 2020 el NO₂ ya estaba un ~20 % por debajo
   de lo habitual antes del confinamiento (tendencia de fondo y meteorología), y
   sin este ajuste esa caída se atribuiría al confinamiento. En escala logarítmica:
   efecto = log(2020/ref)_fase − log(2020/ref)_previo.
4. **Comparación con un año normal.** El mismo cálculo se repite con cada año de
   referencia frente a los demás (dejando uno fuera), y da el rango de variación
   de un año cualquiera. El efecto se considera **claro** solo si la variación
   bruta y la ajustada salen las dos de su rango normal y todas las estaciones
   van en el mismo sentido. Exigir las dos protege frente a un periodo previo
   anómalo: en 2020, la calima de febrero subió las partículas y el ajuste habría
   "inventado" una caída. Con 4 años de referencia es una comprobación
   orientativa, no un contraste formal.
5. **Prueba placebo con 2021.** Se repite el análisis tomando 2021 como si fuera
   el año del confinamiento. Si 2021 muestra un efecto ajustado del mismo signo y
   al menos la mitad de grande, el efecto de 2020 no se puede atribuir al
   confinamiento, y el veredicto pasa a "no concluyente".
6. **Solo se evalúan las fases del estado de alarma.** La nueva normalidad
   (21 jun–31 dic) se muestra como descriptiva: en seis meses se mezclan varias
   estaciones del año y el descenso persistente que se ve también en 2021.

Fechas (Comunitat Valenciana): estado de alarma desde el 14/03/2020; permiso
retribuido recuperable ("hibernación") del 30/03 al 09/04; fase 1 el 18/05;
fase 2 el 01/06; fase 3 el 15/06; nueva normalidad desde el 21/06/2020.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANIO = 2020
REFERENCIA = (2016, 2017, 2018, 2019)
PREVIO = ("Antes", "01-01", "03-13")
PLACEBO = 2021
# (nombre, inicio MM-DD, fin MM-DD, se evalúa con veredicto)
FASES = [
    ("Confinamiento", "03-14", "05-17", True),
    ("Hibernación", "03-30", "04-09", True),
    ("Desescalada", "05-18", "06-20", True),
    ("Nueva normalidad", "06-21", "12-31", False),
]
MIN_ANIOS_REFERENCIA = 3

_COLS_RESUMEN = ["fase", "inicio", "fin", "n_estaciones", "variacion_bruta", "normal_bruta_min",
                 "normal_bruta_max", "efecto", "efecto_min", "efecto_max", "normal_min",
                 "normal_max", "placebo_bruta", "placebo_efecto", "veredicto"]


def _anual(daily: pd.DataFrame, desde: str, hasta: str) -> pd.DataFrame:
    """Media por estación (filas) y año (columnas) entre dos fechas MM-DD."""
    md = daily["fecha"].dt.strftime("%m-%d")
    w = daily[(md >= desde) & (md <= hasta)]
    return w.groupby(["estacion", w["fecha"].dt.year])["media"].mean().unstack()


def _estaciones_validas(fase: pd.DataFrame, previo: pd.DataFrame, anio: int, ref) -> list[str]:
    out = []
    for est in fase.index.intersection(previo.index):
        f, p = fase.loc[est], previo.loc[est]
        if pd.isna(f.get(anio)) or pd.isna(p.get(anio)):
            continue
        if f.reindex(ref).notna().sum() >= MIN_ANIOS_REFERENCIA and \
           p.reindex(ref).notna().sum() >= MIN_ANIOS_REFERENCIA:
            out.append(est)
    return out


def _log_did(fase, previo, est, anio, ref) -> pd.Series:
    """Diferencia en diferencias en escala log, por estación."""
    r_fase = np.log(fase.loc[est, anio] / fase.loc[est, list(ref)].mean(axis=1))
    r_prev = np.log(previo.loc[est, anio] / previo.loc[est, list(ref)].mean(axis=1))
    return r_fase - r_prev


def _pct(log_valor) -> float:
    return float(np.expm1(log_valor) * 100)


def efecto_por_estacion(daily: pd.DataFrame, fase: tuple, anio: int = ANIO,
                        ref=REFERENCIA) -> pd.DataFrame:
    """Variación bruta y efecto ajustado (%) de una fase, por estación."""
    _, desde, hasta = fase[:3]
    f = _anual(daily, desde, hasta)
    p = _anual(daily, PREVIO[1], PREVIO[2])
    ref = [y for y in ref if y in f.columns and y in p.columns]
    est = _estaciones_validas(f, p, anio, ref) if anio in f.columns and anio in p.columns else []
    if not est:
        return pd.DataFrame(columns=["estacion", "variacion_bruta", "efecto"])
    bruta = np.log(f.loc[est, anio] / f.loc[est, ref].mean(axis=1))
    did = _log_did(f, p, est, anio, ref)
    return pd.DataFrame({"estacion": est,
                         "variacion_bruta": np.expm1(bruta.values) * 100,
                         "efecto": np.expm1(did.values) * 100})


def _fuera(x: float, rango: list[float]) -> bool:
    return bool(rango) and (x < min(rango) or x > max(rango))


def _evaluar_fase(f, p, anio, refs):
    """Efecto de `anio` en una fase y rangos de un año normal (dejando uno fuera)."""
    est = _estaciones_validas(f, p, anio, refs) if anio in f.columns and anio in p.columns else []
    if not est:
        return None
    did = _log_did(f, p, est, anio, refs)
    bruta = np.log(f.loc[est, anio] / f.loc[est, refs].mean(axis=1))
    normales, normales_brutas = [], []
    for y in refs:
        otros = [z for z in refs if z != y]
        est_y = [e for e in est if pd.notna(f.loc[e, y]) and pd.notna(p.loc[e, y])]
        if est_y and otros:
            normales.append(_pct(_log_did(f, p, est_y, y, otros).mean()))
            normales_brutas.append(_pct(np.log(f.loc[est_y, y] / f.loc[est_y, otros].mean(axis=1)).mean()))
    return {"est": est, "did": did, "efecto": _pct(did.mean()), "bruta": _pct(bruta.mean()),
            "normales": normales, "normales_brutas": normales_brutas}


def resumen(daily: pd.DataFrame, anio: int = ANIO, ref=REFERENCIA, fases=FASES,
            placebo: int | None = PLACEBO) -> pd.DataFrame:
    """Efecto medio por fase (media geométrica entre estaciones) y veredicto.

    `daily`: columnas estacion, fecha (datetime) y media, como db.daily_means.
    Veredictos: "claro", "no concluyente", "descriptiva" (fase sin evaluar) o
    "sin datos suficientes".
    """
    p = _anual(daily, PREVIO[1], PREVIO[2])
    filas = []
    for nombre, desde, hasta, evaluable in fases:
        f = _anual(daily, desde, hasta)
        refs = [y for y in ref if y in f.columns and y in p.columns]
        r = _evaluar_fase(f, p, anio, refs)
        if r is None:
            filas.append({"fase": nombre, "inicio": desde, "fin": hasta, "n_estaciones": 0,
                          "veredicto": "sin datos suficientes"})
            continue
        pl = _evaluar_fase(f, p, placebo, refs) if placebo else None
        fila = {
            "fase": nombre, "inicio": desde, "fin": hasta, "n_estaciones": len(r["est"]),
            "variacion_bruta": r["bruta"],
            "normal_bruta_min": min(r["normales_brutas"], default=np.nan),
            "normal_bruta_max": max(r["normales_brutas"], default=np.nan),
            "efecto": r["efecto"], "efecto_min": _pct(r["did"].min()), "efecto_max": _pct(r["did"].max()),
            "normal_min": min(r["normales"], default=np.nan),
            "normal_max": max(r["normales"], default=np.nan),
            "placebo_bruta": pl["bruta"] if pl else np.nan,
            "placebo_efecto": pl["efecto"] if pl else np.nan,
        }
        if not evaluable:
            fila["veredicto"] = "descriptiva"
        else:
            did = r["did"]
            mismo_signo = bool((did < 0).all() or (did > 0).all())
            coherente = np.sign(r["efecto"]) == np.sign(r["bruta"])
            placebo_parecido = bool(pl) and np.sign(pl["efecto"]) == np.sign(r["efecto"]) \
                and abs(pl["efecto"]) >= abs(r["efecto"]) / 2
            claro = (_fuera(r["efecto"], r["normales"]) and _fuera(r["bruta"], r["normales_brutas"])
                     and mismo_signo and coherente and not placebo_parecido)
            fila["veredicto"] = "claro" if claro else "no concluyente"
        filas.append(fila)
    return pd.DataFrame(filas, columns=_COLS_RESUMEN)


def serie_semanal(daily: pd.DataFrame, anio: int = ANIO, ref=REFERENCIA) -> pd.DataFrame:
    """Medias semanales del año frente al rango de los años de referencia.

    Solo usa estaciones con datos en el año analizado y en algún año de
    referencia. Devuelve: semana, anio_valor, ref_media, ref_min, ref_max.
    """
    d = daily.assign(anio=daily["fecha"].dt.year,
                     semana=daily["fecha"].dt.isocalendar().week.astype(int).clip(upper=52))
    con_anio = set(d.loc[d["anio"] == anio, "estacion"])
    con_ref = set(d.loc[d["anio"].isin(ref), "estacion"])
    d = d[d["estacion"].isin(con_anio & con_ref) & d["anio"].isin([anio, *ref])]
    s = d.groupby(["anio", "semana"])["media"].mean().unstack(0)
    refs = [y for y in ref if y in s.columns]
    out = pd.DataFrame({
        "semana": s.index,
        "anio_valor": s[anio].values if anio in s.columns else np.nan,
        "ref_media": s[refs].mean(axis=1).values,
        "ref_min": s[refs].min(axis=1).values,
        "ref_max": s[refs].max(axis=1).values,
    })
    return out.reset_index(drop=True)
