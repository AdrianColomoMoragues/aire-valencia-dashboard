"""Utilidades compartidas por las páginas del dashboard (dependen de Streamlit)."""
from __future__ import annotations

import streamlit as st

from . import db, snapshot
from .config import DB_PATH


@st.cache_resource(show_spinner="Preparando los datos (solo en el primer arranque)…")
def preparar_datos() -> str:
    """Crea la base desde el extracto si no existe. Se ejecuta una vez por servidor."""
    return snapshot.ensure_db()


@st.cache_resource
def get_conn():
    return db.connect(DB_PATH)


def datos_o_parar() -> None:
    """Para la página con un mensaje claro si no hay datos disponibles."""
    if preparar_datos() == "sin datos":
        st.error("No hay datos. En local, ejecuta `python -m aire.etl` (o `python -m aire.etl --sample` "
                 "para datos sintéticos); para la nube, sube `snapshot/mediciones.parquet` "
                 "(`python -m aire.snapshot`).")
        st.stop()
