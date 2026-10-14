"""ETL: descarga el CSV de la RVVCCA, lo limpia y lo carga en SQLite.

Uso:
    python -m aire.etl                 # descarga el dataset oficial y lo carga
    python -m aire.etl --file mi.csv   # usa un CSV que ya tienes descargado
    python -m aire.etl --sample        # genera datos sintéticos (sin internet)
"""
from __future__ import annotations

import argparse
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

from . import calidad, db
from .config import CONTAMINANTES, DATASET_URL, DB_PATH, RAW_DIR, ROOT

log = logging.getLogger("aire.etl")


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #

def download(url: str = DATASET_URL, dest_dir: Path = RAW_DIR, force: bool = False) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    if dest.exists() and not force:
        log.info("Ya existe %s, no se vuelve a descargar", dest.name)
        return dest
    log.info("Descargando %s", url)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest


# --------------------------------------------------------------------------- #
# Transform
# --------------------------------------------------------------------------- #

def _sniff_separator(path: Path) -> str:
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        header = f.readline()
    return ";" if header.count(";") > header.count(",") else ","


def _to_number(s: pd.Series) -> pd.Series:
    """Convierte texto a número aceptando coma decimal ('12,5')."""
    s = s.astype("string").str.strip().str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _parse_hour(s: pd.Series) -> pd.Series:
    """Acepta '7', '07', '07:00' o '07:00:00'. Devuelve horas como entero."""
    return pd.to_numeric(
        s.astype("string").str.extract(r"^\s*(\d{1,2})", expand=False), errors="coerce"
    )


def _parse_date(s: pd.Series) -> pd.Series:
    s = s.astype("string").str.strip()
    # Si viene en formato ISO (2019-03-01) no es día primero; si no, sí (01/03/2019).
    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}").fillna(False)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[iso] = pd.to_datetime(s[iso].str[:10], format="%Y-%m-%d", errors="coerce")
    out[~iso] = pd.to_datetime(s[~iso], dayfirst=True, errors="coerce", format="mixed")
    return out.dt.normalize()


DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def _fix_day_month_swap(fecha: pd.Series, dia_mes: pd.Series) -> tuple[pd.Series, int]:
    """Corrige fechas con el día y el mes intercambiados.

    El CSV oficial escribe `Fecha` como AAAA-DD-MM cuando el día es <= 12
    (p. ej. el 2 de enero de 2020 aparece como 2020-02-01). La columna
    `Dia del mes` sí es correcta, así que se usa como referencia: si no coincide
    con el día pero sí con el mes, se intercambian día y mes.
    """
    dm = pd.to_numeric(dia_mes, errors="coerce")
    swap = fecha.notna() & dm.notna() & (fecha.dt.day != dm) & (fecha.dt.month == dm) & (fecha.dt.day <= 12)
    out = fecha.copy()
    if swap.any():
        out[swap] = pd.to_datetime(pd.DataFrame({
            "year": fecha[swap].dt.year, "month": fecha[swap].dt.day, "day": fecha[swap].dt.month,
        }))
    return out, int(swap.sum())


def _weekday_mismatches(fecha: pd.Series, dia_semana: pd.Series) -> int:
    """Filas cuyo día de la semana no coincide con la fecha (control de calidad)."""
    nombre = dia_semana.astype("string").str.strip().str.lower().map(
        lambda t: _strip_accents(t) if isinstance(t, str) else t)
    esperado = fecha.dt.dayofweek.map(dict(enumerate(DIAS_SEMANA)))
    valid = fecha.notna() & nombre.notna()
    return int((valid & (nombre != esperado)).sum())


def _strip_accents(text: str) -> str:
    """'Estación' -> 'Estacion'. El CSV oficial usa tildes; el código no."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [_strip_accents(re.sub(r"\s+", " ", c).strip()) for c in df.columns]
    return df


def read_raw(path: Path) -> pd.DataFrame:
    sep = _sniff_separator(path)
    log.info("Leyendo %s (separador %r)", path.name, sep)
    df = pd.read_csv(path, sep=sep, dtype=str, encoding="utf-8-sig", encoding_errors="replace")
    return _normalize_columns(df)


@dataclass
class TransformReport:
    """Cuenta qué se descarta en `transform` y por qué. Se vuelca en los logs."""

    filas: int = 0
    contaminantes: list[str] = field(default_factory=list)
    filas_sin_fecha_hora: int = 0
    fechas_dia_mes_corregidas: int = 0
    dias_semana_incoherentes: int = 0
    filas_sin_estacion: int = 0
    celdas_total: int = 0
    celdas_vacias: int = 0
    celdas_no_numericas: int = 0
    celdas_sin_clave: int = 0          # celdas con valor pero sin estación o fecha/hora válida
    celdas_negativas: int = 0
    celdas_duplicadas: int = 0
    mediciones: int = 0
    estaciones_sin_contaminantes: list[str] = field(default_factory=list)

    def log(self, logger: logging.Logger = log) -> None:
        f = "{:,}".format
        logger.info("Filas leídas: %s · contaminantes: %s", f(self.filas), ", ".join(self.contaminantes))
        nivel = logging.WARNING if self.filas_sin_fecha_hora else logging.INFO
        logger.log(nivel, "Filas con fecha u hora no interpretable: %s", f(self.filas_sin_fecha_hora))
        nivel = logging.WARNING if self.fechas_dia_mes_corregidas else logging.INFO
        logger.log(nivel, "Filas con día y mes intercambiados (corregidas): %s",
                   f(self.fechas_dia_mes_corregidas))
        nivel = logging.WARNING if self.dias_semana_incoherentes else logging.INFO
        logger.log(nivel, "Filas cuyo día de la semana no cuadra con la fecha: %s",
                   f(self.dias_semana_incoherentes))
        nivel = logging.WARNING if self.filas_sin_estacion else logging.INFO
        logger.log(nivel, "Filas sin estación: %s", f(self.filas_sin_estacion))
        logger.info("Celdas de contaminantes (filas × %d): %s", len(self.contaminantes), f(self.celdas_total))
        logger.info("  - vacías (sin dato o sin analizador):  %s", f(self.celdas_vacias))
        nivel = logging.WARNING if self.celdas_no_numericas else logging.INFO
        logger.log(nivel, "  - texto no numérico:                  %s", f(self.celdas_no_numericas))
        logger.info("  - sin estación o fecha válida:        %s", f(self.celdas_sin_clave))
        nivel = logging.WARNING if self.celdas_negativas else logging.INFO
        logger.log(nivel, "  - negativas (error de sensor):        %s", f(self.celdas_negativas))
        nivel = logging.WARNING if self.celdas_duplicadas else logging.INFO
        logger.log(nivel, "  - duplicadas (misma estación y hora): %s", f(self.celdas_duplicadas))
        logger.info("  = mediciones válidas:                 %s (%.1f %%)",
                    f(self.mediciones), 100 * self.mediciones / max(self.celdas_total, 1))
        if self.estaciones_sin_contaminantes:
            logger.info("Estaciones sin ningún contaminante (se excluyen): %s",
                        ", ".join(self.estaciones_sin_contaminantes))


def transform(raw: pd.DataFrame, report: TransformReport | None = None) -> pd.DataFrame:
    """Pasa del formato ancho del CSV a formato largo y limpio.

    Salida: columnas estacion, fecha_hora, contaminante, valor.
    Si se pasa `report`, se rellena con el recuento de lo descartado en cada paso.
    """
    rep = report if report is not None else TransformReport()
    required = {"Fecha", "Hora", "Estacion"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"Faltan columnas en el CSV: {sorted(missing)}")

    fecha = _parse_date(raw["Fecha"])
    if "Dia del mes" in raw.columns:
        fecha, rep.fechas_dia_mes_corregidas = _fix_day_month_swap(fecha, raw["Dia del mes"])
    if "Dia de la semana" in raw.columns:
        rep.dias_semana_incoherentes = _weekday_mismatches(fecha, raw["Dia de la semana"])
    hora = _parse_hour(raw["Hora"])
    # La hora 24 existe en algunos ficheros oficiales: se suma como timedelta.
    fecha_hora = fecha + pd.to_timedelta(hora, unit="h")

    present = [c for c in CONTAMINANTES if c in raw.columns]
    if not present:
        raise ValueError("El CSV no contiene ninguna columna de contaminantes conocida")

    estacion = raw["Estacion"].astype("string").str.strip().replace("", pd.NA)
    wide = pd.DataFrame({"estacion": estacion, "fecha_hora": fecha_hora})
    for col in present:
        texto = raw[col].astype("string").str.strip().replace("", pd.NA)
        wide[CONTAMINANTES[col]] = _to_number(raw[col])
        rep.celdas_vacias += int(texto.isna().sum())
        rep.celdas_no_numericas += int((texto.notna() & wide[CONTAMINANTES[col]].isna()).sum())

    rep.filas = len(raw)
    rep.contaminantes = [CONTAMINANTES[c] for c in present]
    rep.filas_sin_fecha_hora = int(fecha_hora.isna().sum())
    rep.filas_sin_estacion = int(estacion.isna().sum())
    rep.celdas_total = len(raw) * len(present)

    long = wide.melt(
        id_vars=["estacion", "fecha_hora"], var_name="contaminante", value_name="valor"
    )
    long = long.dropna(subset=["valor"])
    n = len(long)
    long = long.dropna(subset=["estacion", "fecha_hora"])
    rep.celdas_sin_clave = n - len(long)
    neg = long["valor"] < 0                    # negativos = errores de sensor
    rep.celdas_negativas = int(neg.sum())
    long = long[~neg]
    n = len(long)
    long = long.drop_duplicates(subset=["estacion", "fecha_hora", "contaminante"], keep="last")
    rep.celdas_duplicadas = n - len(long)
    rep.mediciones = len(long)

    con_dato = set(long["estacion"].unique())
    rep.estaciones_sin_contaminantes = sorted(set(estacion.dropna().unique()) - con_dato)
    return long.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #

def _display_path(p: Path) -> str:
    """Ruta relativa al proyecto para los logs (evita mostrar rutas locales)."""
    try:
        return Path(p).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return Path(p).name


def run(csv_path: Path, db_path: Path = DB_PATH) -> int:
    raw = read_raw(csv_path)
    report = TransformReport()
    clean = transform(raw, report)
    report.log()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db.connect(db_path) as conn:
        n = db.load_measurements(conn, clean)
        log.info("Cargadas %s mediciones en %s", f"{n:,}", _display_path(db_path))
        flags = calidad.detectar(clean)
        db.load_quality_flags(conn, flags)
    if flags.empty:
        log.info("Control de calidad: sin incidencias")
    else:
        resumen = flags.groupby("regla").agg(episodios=("n_horas", "size"), horas=("n_horas", "sum"))
        for regla, r in resumen.iterrows():
            log.info("Control de calidad · %-16s %4d episodios · %s h", regla, r.episodios,
                     f"{int(r.horas):,}")
    return n


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--file", type=Path, help="CSV ya descargado")
    g.add_argument("--sample", action="store_true", help="usar datos sintéticos")
    p.add_argument("--db", type=Path, default=DB_PATH)
    args = p.parse_args(argv)

    if args.sample:
        from .sample import write_sample_csv
        csv_path = write_sample_csv(RAW_DIR / "muestra_sintetica.csv")
    elif args.file:
        csv_path = args.file
    else:
        csv_path = download()
    run(csv_path, args.db)


if __name__ == "__main__":
    main()
