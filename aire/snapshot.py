"""Extracto compacto de los datos limpios para desplegar sin `data/`.

`data/` no se sube a GitHub (el CSV ocupa 48 MB y `aire.db`, 175 MB). Para la
nube se sube `snapshot/mediciones.parquet` (~5 MB): las mediciones ya limpias
(con las fechas corregidas), en formato largo. Al arrancar, si no existe
`aire.db`, la app la reconstruye a partir del extracto en pocos segundos y
vuelve a aplicar el control de calidad.

Uso:
    python -m aire.snapshot            # regenera el extracto desde data/aire.db
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from . import calidad, db
from .config import DB_PATH, ROOT

SNAPSHOT_PATH = ROOT / "snapshot" / "mediciones.parquet"
COLUMNAS = ["estacion", "fecha_hora", "contaminante", "valor"]

log = logging.getLogger("aire.snapshot")


def export_snapshot(db_path: Path = DB_PATH, out: Path = SNAPSHOT_PATH) -> Path:
    """Exporta las mediciones de `db_path` a Parquet (zstd, columnas categóricas)."""
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query(
            "SELECT e.nombre AS estacion, m.fecha_hora, m.contaminante, m.valor "
            "FROM mediciones m JOIN estaciones e ON e.id = m.estacion_id", conn)
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    df = (df.astype({"estacion": "category", "contaminante": "category"})
            .sort_values(["estacion", "contaminante", "fecha_hora"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, compression="zstd", index=False)
    log.info("Extracto: %s mediciones -> %s (%.1f MB)", f"{len(df):,}", out.name,
             out.stat().st_size / 1e6)
    return out


def build_db_from_snapshot(snapshot: Path = SNAPSHOT_PATH, db_path: Path = DB_PATH) -> int:
    """Crea `db_path` a partir del extracto y recalcula el control de calidad."""
    df = pd.read_parquet(snapshot)[COLUMNAS]
    df = df.astype({"estacion": "string", "contaminante": "string"})
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    with db.connect(tmp) as conn:
        n = db.load_measurements(conn, df)
        db.load_quality_flags(conn, calidad.detectar(df))
    conn.close()
    tmp.replace(db_path)          # atómico: nunca queda una base a medio crear
    log.info("Base creada desde el extracto: %s mediciones", f"{n:,}")
    return n


def ensure_db(db_path: Path = DB_PATH, snapshot: Path = SNAPSHOT_PATH) -> str:
    """Garantiza que existe la base de datos. Devuelve de dónde ha salido.

    - "existente": ya estaba (p. ej. en local, creada con el ETL).
    - "extracto": se ha creado ahora a partir de `snapshot/` (p. ej. en la nube).
    - "sin datos": no hay base ni extracto.
    """
    if db_path.exists():
        return "existente"
    if snapshot.exists():
        build_db_from_snapshot(snapshot, db_path)
        return "extracto"
    return "sin datos"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    export_snapshot()
