"""Genera un CSV sintético con el mismo formato que el dataset oficial.

Sirve para probar el proyecto sin conexión y para los tests. Los patrones son
realistas a grandes rasgos (picos de NO2 en hora punta, O3 alto en tardes de
verano, menos tráfico en fin de semana), pero los valores NO son reales.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ESTACIONES = {
    # nombre: factor de tráfico (más alto = más NO2, menos O3)
    "Avda. Francia": 1.0,
    "Bulevard Sud": 1.2,
    "Molí del Sol": 0.8,
    "Pista Silla": 1.4,
    "Politècnic": 0.6,
    "Viveros": 0.9,
    "Centre": 1.3,
}


def generate(start: str = "2020-01-01", days: int = 365, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=days * 24, freq="h")
    hour = idx.hour.to_numpy()
    doy = idx.dayofyear.to_numpy()
    weekend = np.asarray(idx.dayofweek >= 5)

    traffic = (np.exp(-((hour - 8) ** 2) / 6) + 0.8 * np.exp(-((hour - 20) ** 2) / 8))
    traffic = traffic * np.where(weekend, 0.55, 1.0)
    winter = 0.5 + 0.5 * np.cos(2 * np.pi * (doy - 15) / 365)   # 1 en enero, 0 en julio
    sun = np.clip(np.sin(np.pi * (hour - 6) / 14), 0, None) * (1 - winter)

    frames = []
    for name, f in ESTACIONES.items():
        n = len(idx)
        no2 = 12 + 35 * f * traffic * (0.7 + 0.6 * winter) + rng.gamma(2, 3, n)
        o3 = 30 + 70 * sun / f + rng.normal(0, 8, n) - 0.3 * no2
        pm10 = 15 + 10 * winter + 8 * f * traffic + rng.gamma(2, 4, n)
        # Episodios de intrusión sahariana: unos pocos días con PM muy alto.
        dust = np.isin(doy, rng.choice(365, 8, replace=False)) * rng.uniform(40, 90)
        pm10 = pm10 + dust
        pm25 = 0.55 * pm10 + rng.normal(0, 2, n)
        so2 = 2 + 2 * f * traffic + rng.gamma(1.5, 1, n)
        co = 0.2 + 0.3 * f * traffic * (0.7 + 0.6 * winter) + rng.gamma(2, 0.03, n)

        df = pd.DataFrame({
            "Fecha": idx.strftime("%d/%m/%Y"),
            "Dia de la semana": idx.day_name(),
            "Dia del mes": idx.day,
            "Hora": idx.strftime("%H:%M:%S"),
            "Estacion": name,
            "PM2.5": np.clip(pm25, 1, None).round(1),
            "PM10": np.clip(pm10, 1, None).round(1),
            "NO2": np.clip(no2, 1, None).round(1),
            "O3": np.clip(o3, 1, None).round(1),
            "SO2": np.clip(so2, 0.5, None).round(1),
            "CO": np.clip(co, 0.05, None).round(2),
        })
        # Huecos aleatorios (~2 %) como en los datos reales.
        mask = rng.random((n, 6)) < 0.02
        cols = ["PM2.5", "PM10", "NO2", "O3", "SO2", "CO"]
        df[cols] = df[cols].mask(mask)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def write_sample_csv(path: Path, **kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = generate(**kwargs)
    # Formato "español": separador ';' y coma decimal.
    df.to_csv(path, sep=";", decimal=",", index=False)
    return path
