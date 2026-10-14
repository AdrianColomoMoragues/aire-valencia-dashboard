"""Control de calidad de sensores.

Las reglas marcan episodios sospechosos, pero no borran datos: una regla
automática no distingue un sensor roto de un evento real (la Cremà de las
Fallas da picos de PM2.5 que parecen errores). Cada episodio queda en la tabla
`incidencias_calidad`, y el dashboard permite excluir los que tienen
`excluir = 1`.

Reglas:
- valor_atascado: >= 12 horas seguidas con exactamente el mismo valor.
  No se aplica a CO ni a SO2: su resolución (0,1 mg/m³ y 1 µg/m³) y sus niveles
  tan bajos hacen que pasen cientos de horas en el valor mínimo sin que el sensor
  falle.
- pico_aislado: un valor más de 4 veces mayor que sus dos horas vecinas y por
  encima del percentil 99,9 del contaminante. Solo es un aviso (excluir = 0).
- deriva_regional (solo O3): el O3 es un contaminante secundario y regional,
  muy homogéneo en toda la ciudad a escala diaria. Si durante >= 30 días la
  relación de una estación con la mediana de las demás se aleja más de x1,5 de
  su relación habitual, se marca el periodo. En NO2 y PM no se aplica porque
  dependen de fuentes locales y las diferencias entre estaciones son reales.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

COLUMNAS = ["estacion", "contaminante", "inicio", "fin", "regla", "n_horas", "excluir", "detalle"]

CONT_ATASCADO = ("NO2", "O3", "PM10", "PM2.5")
CONT_PICOS = ("NO2", "O3", "PM10", "PM2.5")
MIN_HORAS_ATASCADO = 12
FACTOR_PICO = 4.0
CUANTIL_PICO = 0.999
FACTOR_DERIVA = 1.5
VENTANA_DERIVA = "30D"
MIN_DIAS_DERIVA = 30
MIN_ESTACIONES_REFERENCIA = 3
MIN_HORAS_DIA = 18


def _vacio() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNAS)


def _ordenado(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["estacion", "contaminante", "fecha_hora"]).reset_index(drop=True)


def valores_atascados(df: pd.DataFrame, min_horas: int = MIN_HORAS_ATASCADO,
                      contaminantes=CONT_ATASCADO) -> pd.DataFrame:
    """Rachas de horas consecutivas con exactamente el mismo valor."""
    d = _ordenado(df[df["contaminante"].isin(contaminantes)])
    if d.empty:
        return _vacio()
    g = d.groupby(["estacion", "contaminante"], sort=False)
    nueva = (d["valor"] != g["valor"].shift()) | \
            (d["fecha_hora"] - g["fecha_hora"].shift() != pd.Timedelta("1h"))
    d["racha"] = nueva.cumsum()
    r = d.groupby("racha").agg(
        estacion=("estacion", "first"), contaminante=("contaminante", "first"),
        inicio=("fecha_hora", "first"), fin=("fecha_hora", "last"),
        valor=("valor", "first"), n_horas=("valor", "size"),
    )
    r = r[r["n_horas"] >= min_horas]
    if r.empty:
        return _vacio()
    r = r.assign(
        regla="valor_atascado", excluir=1,
        detalle=r["valor"].map(lambda v: f"valor constante {v:g}") + " durante "
        + r["n_horas"].astype(str) + " h",
    )
    return r[COLUMNAS].reset_index(drop=True)


def picos_aislados(df: pd.DataFrame, factor: float = FACTOR_PICO, cuantil: float = CUANTIL_PICO,
                   contaminantes=CONT_PICOS) -> pd.DataFrame:
    """Valores muy por encima de sus dos horas vecinas y del percentil `cuantil`."""
    d = _ordenado(df[df["contaminante"].isin(contaminantes)])
    if d.empty:
        return _vacio()
    g = d.groupby(["estacion", "contaminante"], sort=False)
    prev, nxt = g["valor"].shift(1), g["valor"].shift(-1)
    contiguo = (d["fecha_hora"] - g["fecha_hora"].shift(1) == pd.Timedelta("1h")) & \
               (g["fecha_hora"].shift(-1) - d["fecha_hora"] == pd.Timedelta("1h"))
    umbral = d.groupby("contaminante")["valor"].transform(lambda s: s.quantile(cuantil))
    vecino = np.maximum(prev, nxt)
    es_pico = contiguo & (d["valor"] > factor * vecino) & (d["valor"] > umbral)
    p = d[es_pico]
    if p.empty:
        return _vacio()
    out = pd.DataFrame({
        "estacion": p["estacion"], "contaminante": p["contaminante"],
        "inicio": p["fecha_hora"], "fin": p["fecha_hora"],
        "regla": "pico_aislado", "n_horas": 1, "excluir": 0,
        "detalle": [f"{v:g} entre {a:g} y {b:g}" for v, a, b in
                    zip(p["valor"], prev[es_pico], nxt[es_pico])],
    })
    return out[COLUMNAS].reset_index(drop=True)


def deriva_regional(df: pd.DataFrame, contaminante: str = "O3", factor: float = FACTOR_DERIVA,
                    ventana: str = VENTANA_DERIVA, min_dias: int = MIN_DIAS_DERIVA) -> pd.DataFrame:
    """Periodos en que una estación se separa de forma sostenida del resto."""
    d = df[df["contaminante"] == contaminante]
    if d.empty:
        return _vacio()
    diaria = (d.assign(fecha=d["fecha_hora"].dt.floor("D"))
              .groupby(["estacion", "fecha"])["valor"].agg(["mean", "size"]).reset_index())
    diaria = diaria[diaria["size"] >= MIN_HORAS_DIA]
    w = diaria.pivot(index="fecha", columns="estacion", values="mean").sort_index()
    if w.shape[1] < MIN_ESTACIONES_REFERENCIA + 1:
        return _vacio()
    w = w.asfreq("D")
    umbral = np.log(factor)
    filas = []
    for est in w.columns:
        otras = w.drop(columns=est)
        ref = otras.median(axis=1).where(otras.notna().sum(axis=1) >= MIN_ESTACIONES_REFERENCIA)
        ratio = np.log(w[est] / ref).replace([np.inf, -np.inf], np.nan)
        habitual = ratio.median()
        desv = (ratio - habitual).rolling(ventana, min_periods=20).median()
        fuera = desv.abs() > umbral
        tramo = (fuera != fuera.shift()).cumsum()
        for _, seg in desv[fuera].groupby(tramo[fuera]):
            if len(seg) < min_dias:
                continue
            ini, fin = seg.index.min(), seg.index.max()
            rel = float(np.exp(seg.median()))
            horas = int(((d["estacion"] == est) & (d["fecha_hora"] >= ini)
                         & (d["fecha_hora"] < fin + pd.Timedelta("1D"))).sum())
            filas.append({
                "estacion": est, "contaminante": contaminante,
                "inicio": ini, "fin": fin + pd.Timedelta(hours=23),
                "regla": "deriva_regional", "n_horas": horas, "excluir": 1,
                "detalle": f"{len(seg)} días al {rel:.0%} de su nivel habitual respecto al resto",
            })
    return pd.DataFrame(filas, columns=COLUMNAS) if filas else _vacio()


def detectar(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica todas las reglas. `df` en formato largo: estacion, fecha_hora, contaminante, valor."""
    partes = [valores_atascados(df), picos_aislados(df), deriva_regional(df)]
    partes = [p for p in partes if not p.empty]
    if not partes:
        return _vacio()
    out = pd.concat(partes, ignore_index=True)
    return out.sort_values(["contaminante", "estacion", "inicio"]).reset_index(drop=True)
