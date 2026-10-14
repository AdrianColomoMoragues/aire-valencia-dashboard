"""Esquema SQLite y consultas usadas por el dashboard."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .config import MIN_HORAS_DIA

SCHEMA = """
CREATE TABLE IF NOT EXISTS estaciones (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS mediciones (
    estacion_id  INTEGER NOT NULL REFERENCES estaciones(id),
    fecha_hora   TEXT    NOT NULL,          -- ISO 8601: 'YYYY-MM-DD HH:MM:SS'
    contaminante TEXT    NOT NULL,
    valor        REAL    NOT NULL,
    PRIMARY KEY (estacion_id, fecha_hora, contaminante)
);

CREATE INDEX IF NOT EXISTS idx_med_cont_fecha
    ON mediciones (contaminante, fecha_hora);

-- Vista con agregados diarios: es la base de casi todos los gráficos.
CREATE VIEW IF NOT EXISTS medias_diarias AS
SELECT e.nombre              AS estacion,
       m.contaminante        AS contaminante,
       date(m.fecha_hora)    AS fecha,
       AVG(m.valor)          AS media,
       MAX(m.valor)          AS maximo,
       COUNT(*)              AS n_horas
FROM mediciones m
JOIN estaciones e ON e.id = m.estacion_id
GROUP BY e.nombre, m.contaminante, date(m.fecha_hora);

-- Episodios marcados por el control de calidad (aire/calidad.py).
CREATE TABLE IF NOT EXISTS incidencias_calidad (
    estacion_id  INTEGER NOT NULL REFERENCES estaciones(id),
    contaminante TEXT    NOT NULL,
    inicio       TEXT    NOT NULL,
    fin          TEXT    NOT NULL,
    regla        TEXT    NOT NULL,
    n_horas      INTEGER NOT NULL,
    excluir      INTEGER NOT NULL,          -- 1 = se puede excluir; 0 = solo aviso
    detalle      TEXT
);
CREATE INDEX IF NOT EXISTS idx_qc ON incidencias_calidad (estacion_id, contaminante);

-- Igual que medias_diarias, pero sin las horas de episodios con excluir = 1.
CREATE VIEW IF NOT EXISTS medias_diarias_qc AS
SELECT e.nombre              AS estacion,
       m.contaminante        AS contaminante,
       date(m.fecha_hora)    AS fecha,
       AVG(m.valor)          AS media,
       MAX(m.valor)          AS maximo,
       COUNT(*)              AS n_horas
FROM mediciones m
JOIN estaciones e ON e.id = m.estacion_id
WHERE NOT EXISTS (
    SELECT 1 FROM incidencias_calidad q
    WHERE q.estacion_id = m.estacion_id AND q.contaminante = m.contaminante
      AND q.excluir = 1 AND m.fecha_hora BETWEEN q.inicio AND q.fin)
GROUP BY e.nombre, m.contaminante, date(m.fecha_hora);
"""

# Condición para excluir horas marcadas en consultas sobre `mediciones m`.
_NO_EXCLUIDA = """
          AND NOT EXISTS (
              SELECT 1 FROM incidencias_calidad q
              WHERE q.estacion_id = m.estacion_id AND q.contaminante = m.contaminante
                AND q.excluir = 1 AND m.fecha_hora BETWEEN q.inicio AND q.fin)"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def load_measurements(conn: sqlite3.Connection, df: pd.DataFrame) -> int:
    """Carga un DataFrame largo (estacion, fecha_hora, contaminante, valor).

    Devuelve el número de filas insertadas o actualizadas.
    """
    init_db(conn)
    conn.executemany(
        "INSERT OR IGNORE INTO estaciones (nombre) VALUES (?)",
        [(s,) for s in sorted(df["estacion"].unique())],
    )
    ids = dict(conn.execute("SELECT nombre, id FROM estaciones").fetchall())

    rows = zip(
        df["estacion"].map(ids),
        df["fecha_hora"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        df["contaminante"],
        df["valor"].astype(float),
    )
    cur = conn.executemany(
        "INSERT OR REPLACE INTO mediciones (estacion_id, fecha_hora, contaminante, valor) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return cur.rowcount


def load_quality_flags(conn: sqlite3.Connection, flags: pd.DataFrame) -> int:
    """Sustituye las incidencias de calidad por las de `flags` (ver aire/calidad.py)."""
    init_db(conn)
    conn.execute("DELETE FROM incidencias_calidad")
    if not flags.empty:
        ids = dict(conn.execute("SELECT nombre, id FROM estaciones").fetchall())
        fmt = "%Y-%m-%d %H:%M:%S"
        conn.executemany(
            "INSERT INTO incidencias_calidad (estacion_id, contaminante, inicio, fin, regla, "
            "n_horas, excluir, detalle) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            zip(flags["estacion"].map(ids), flags["contaminante"],
                pd.to_datetime(flags["inicio"]).dt.strftime(fmt),
                pd.to_datetime(flags["fin"]).dt.strftime(fmt),
                flags["regla"], flags["n_horas"].astype(int), flags["excluir"].astype(int),
                flags["detalle"]),
        )
    conn.commit()
    return len(flags)


def quality_flags(conn, pollutant: str, stations: list[str], start: str, end: str) -> pd.DataFrame:
    """Incidencias de calidad que se solapan con el periodo y las estaciones elegidas."""
    cols = ["estacion", "regla", "inicio", "fin", "n_horas", "excluir", "detalle"]
    if not stations:
        return pd.DataFrame(columns=cols)
    try:
        sql = f"""
            SELECT e.nombre AS estacion, q.regla, q.inicio, q.fin, q.n_horas, q.excluir, q.detalle
            FROM incidencias_calidad q JOIN estaciones e ON e.id = q.estacion_id
            WHERE q.contaminante = ?
              AND e.nombre IN ({_in_clause(stations)})
              AND date(q.fin) >= ? AND date(q.inicio) <= ?
            ORDER BY q.inicio
        """
        return pd.read_sql_query(sql, conn, params=[pollutant, *stations, start, end])
    except pd.errors.DatabaseError:       # base creada antes de existir la tabla
        return pd.DataFrame(columns=cols)


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #

def _in_clause(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def list_stations(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT nombre FROM estaciones ORDER BY nombre")]


def list_pollutants(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT contaminante FROM mediciones ORDER BY contaminante")]


def date_range(conn: sqlite3.Connection) -> tuple[str, str]:
    return conn.execute(
        "SELECT date(MIN(fecha_hora)), date(MAX(fecha_hora)) FROM mediciones").fetchone()


def daily_means(conn, pollutant: str, stations: list[str], start: str, end: str,
                excluir_qc: bool = False) -> pd.DataFrame:
    """Medias diarias válidas (>= MIN_HORAS_DIA horas) por estación.

    Con `excluir_qc`, se descartan antes las horas marcadas por el control de calidad.
    """
    if not stations:
        return pd.DataFrame(columns=["estacion", "fecha", "media", "maximo", "n_horas"])
    sql = f"""
        SELECT estacion, fecha, media, maximo, n_horas
        FROM {"medias_diarias_qc" if excluir_qc else "medias_diarias"}
        WHERE contaminante = ?
          AND estacion IN ({_in_clause(stations)})
          AND fecha BETWEEN ? AND ?
          AND n_horas >= ?
        ORDER BY fecha
    """
    df = pd.read_sql_query(sql, conn, params=[pollutant, *stations, start, end, MIN_HORAS_DIA])
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def hourly_values(conn, pollutant: str, stations: list[str], start: str, end: str,
                  excluir_qc: bool = False) -> pd.DataFrame:
    if not stations:
        return pd.DataFrame(columns=["estacion", "fecha_hora", "valor"])
    sql = f"""
        SELECT e.nombre AS estacion, m.fecha_hora, m.valor
        FROM mediciones m JOIN estaciones e ON e.id = m.estacion_id
        WHERE m.contaminante = ?
          AND e.nombre IN ({_in_clause(stations)})
          AND date(m.fecha_hora) BETWEEN ? AND ?{_NO_EXCLUIDA if excluir_qc else ""}
        ORDER BY m.fecha_hora
    """
    df = pd.read_sql_query(sql, conn, params=[pollutant, *stations, start, end])
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    return df


def weekly_profile(conn, pollutant: str, stations: list[str], start: str, end: str,
                   excluir_qc: bool = False) -> pd.DataFrame:
    """Media por día de la semana (0 = lunes) y hora del día."""
    if not stations:
        return pd.DataFrame(columns=["dia_semana", "hora", "media"])
    # strftime('%w') devuelve 0 = domingo; lo pasamos a 0 = lunes.
    sql = f"""
        SELECT (CAST(strftime('%w', m.fecha_hora) AS INTEGER) + 6) % 7 AS dia_semana,
               CAST(strftime('%H', m.fecha_hora) AS INTEGER)           AS hora,
               AVG(m.valor)                                            AS media
        FROM mediciones m JOIN estaciones e ON e.id = m.estacion_id
        WHERE m.contaminante = ?
          AND e.nombre IN ({_in_clause(stations)})
          AND date(m.fecha_hora) BETWEEN ? AND ?{_NO_EXCLUIDA if excluir_qc else ""}
        GROUP BY dia_semana, hora
        ORDER BY dia_semana, hora
    """
    return pd.read_sql_query(sql, conn, params=[pollutant, *stations, start, end])
