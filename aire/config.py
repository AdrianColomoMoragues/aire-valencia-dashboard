"""Configuración central del proyecto."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "aire.db"

# Datos horarios de la Red Valenciana de Vigilancia y Control de la Contaminación
# Atmosférica (RVVCCA) para la ciudad de València, 2016-2021.
# Portal de datos abiertos del Ajuntament de València — licencia CC BY 4.0.
DATASET_URL = (
    "https://opendata.vlci.valencia.es/dataset/b5c2656c-6c1c-413d-a56e-549e52220502/"
    "resource/4be7248b-9597-4017-89af-82a9b6e2382f/download/"
    "rvvcca.-datos-horarios-valencia-2016-2021-curt-cas.csv"
)
DATASET_PAGE = (
    "https://opendata.vlci.valencia.es/en/dataset/hourly-air-quality-data-since-2016"
)

# Columnas de contaminantes que se cargan en la base de datos (nombre en el CSV -> código).
CONTAMINANTES = {
    "PM2.5": "PM2.5",
    "PM10": "PM10",
    "NO2": "NO2",
    "O3": "O3",
    "SO2": "SO2",
    "CO": "CO",
}

# Valores guía de la OMS (2021). Para O3 la guía se aplica a la media móvil de 8 h
# máxima diaria; para el resto, a la media diaria.
GUIAS_OMS = {
    "PM2.5": {"valor": 15, "unidad": "µg/m³", "metrica": "media diaria"},
    "PM10": {"valor": 45, "unidad": "µg/m³", "metrica": "media diaria"},
    "NO2": {"valor": 25, "unidad": "µg/m³", "metrica": "media diaria"},
    "O3": {"valor": 100, "unidad": "µg/m³", "metrica": "máx. diario media móvil 8 h"},
    "SO2": {"valor": 40, "unidad": "µg/m³", "metrica": "media diaria"},
    "CO": {"valor": 4, "unidad": "mg/m³", "metrica": "media diaria"},
}

# Un día se considera válido si tiene al menos el 75 % de las horas (criterio UE).
MIN_HORAS_DIA = 18
