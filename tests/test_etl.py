import pandas as pd
import pytest

from aire import db, etl
from aire.indicadores import (
    daily_indicator,
    exceedance_summary,
    guia_en_escala,
    o3_max_8h,
    serie_diaria_continua,
    texto_guia_fuera_de_escala,
)
from aire.sample import write_sample_csv


@pytest.fixture
def sample_csv(tmp_path):
    return write_sample_csv(tmp_path / "muestra.csv", days=20)


def test_read_raw_detecta_punto_y_coma(sample_csv):
    raw = etl.read_raw(sample_csv)
    assert {"Fecha", "Hora", "Estacion", "NO2"} <= set(raw.columns)


def test_transform_formato_largo(sample_csv):
    clean = etl.transform(etl.read_raw(sample_csv))
    assert list(clean.columns) == ["estacion", "fecha_hora", "contaminante", "valor"]
    assert clean["valor"].ge(0).all()
    assert not clean.duplicated(["estacion", "fecha_hora", "contaminante"]).any()


def test_transform_acepta_coma_decimal_y_hora_24(tmp_path):
    p = tmp_path / "mini.csv"
    p.write_text(
        "Fecha;Hora;Estacion;NO2;O3\n"
        "01/03/2020;07:00:00;Centre;12,5;40\n"
        "01/03/2020;24;Centre;-3;\n",
        encoding="utf-8",
    )
    clean = etl.transform(etl.read_raw(p))
    no2 = clean[clean["contaminante"] == "NO2"]
    assert no2["valor"].tolist() == [12.5]                       # el negativo se descarta
    assert no2["fecha_hora"].iloc[0] == pd.Timestamp("2020-03-01 07:00")
    o3 = clean[clean["contaminante"] == "O3"]
    assert o3["valor"].tolist() == [40.0]                        # el vacío se descarta


def test_transform_acepta_fecha_iso_y_coma(tmp_path):
    p = tmp_path / "iso.csv"
    p.write_text("Fecha,Hora,Estacion,PM10\n2021-12-31,23,Viveros,30.2\n", encoding="utf-8")
    clean = etl.transform(etl.read_raw(p))
    assert clean["fecha_hora"].iloc[0] == pd.Timestamp("2021-12-31 23:00")


def test_transform_error_si_faltan_columnas(tmp_path):
    p = tmp_path / "malo.csv"
    p.write_text("a;b\n1;2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Faltan columnas"):
        etl.transform(etl.read_raw(p))


def test_carga_y_consultas(sample_csv, tmp_path):
    db_path = tmp_path / "test.db"
    n = etl.run(sample_csv, db_path)
    assert n > 0
    conn = db.connect(db_path)
    stations = db.list_stations(conn)
    assert "Centre" in stations
    assert "NO2" in db.list_pollutants(conn)

    start, end = db.date_range(conn)
    daily = db.daily_means(conn, "NO2", stations[:2], start, end)
    assert set(daily["estacion"]) == set(stations[:2])
    assert (daily["n_horas"] >= 18).all()

    prof = db.weekly_profile(conn, "NO2", stations, start, end)
    assert prof["dia_semana"].between(0, 6).all()
    assert prof["hora"].between(0, 23).all()

    # Cargar dos veces no duplica filas
    etl.run(sample_csv, db_path)
    total = conn.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
    assert total == n


def test_o3_media_movil_8h():
    idx = pd.date_range("2020-07-01", periods=24, freq="h")
    hourly = pd.DataFrame({"estacion": "X", "fecha_hora": idx, "valor": range(24)})
    res = o3_max_8h(hourly)
    # La ventana de 8 h que acaba a las 23:00 es 16..23 -> media 19.5
    assert res["valor"].iloc[0] == pytest.approx(19.5)


def test_resumen_superaciones():
    ind = pd.DataFrame({"estacion": ["A"] * 4, "fecha": pd.date_range("2020-01-01", periods=4),
                        "valor": [10, 30, 30, 10]})
    res = exceedance_summary("NO2", ind)            # guía OMS NO2 = 25
    assert res.loc[0, "dias_sobre_guia"] == 2
    assert res.loc[0, "pct_sobre_guia"] == pytest.approx(50)
    assert daily_indicator("NO2", ind.rename(columns={"valor": "media"}).assign(n_horas=24)).shape[0] == 4


def test_read_raw_acepta_columnas_con_tilde(tmp_path):
    # Cabecera tal como viene en el CSV oficial (con BOM y tildes).
    p = tmp_path / "oficial.csv"
    p.write_text(
        "\ufeffFecha;Día de la semana;Hora;Estación;NO2\n"
        "2020-01-01T00:00:00;Miércoles;0:00:00;Avda. Francia;45\n",
        encoding="utf-8",
    )
    clean = etl.transform(etl.read_raw(p))
    assert clean["estacion"].tolist() == ["Avda. Francia"]
    assert clean["fecha_hora"].iloc[0] == pd.Timestamp("2020-01-01 00:00")


def test_report_cuenta_cada_descarte(tmp_path):
    p = tmp_path / "sucio.csv"
    p.write_text(
        "Fecha;Hora;Estacion;NO2;O3\n"
        "01/03/2020;07:00:00;Centre;12,5;40\n"     # 2 válidas
        "01/03/2020;08:00:00;Centre;-3;n/d\n"      # 1 negativa, 1 texto
        "xx/03/2020;09:00:00;Centre;10;\n"         # fecha mala: 1 sin clave, 1 vacía
        "01/03/2020;07:00:00;Centre;13;\n"         # NO2 duplicada, 1 vacía
        "01/03/2020;10:00:00;Meteo;;\n",            # estación sin contaminantes: 2 vacías
        encoding="utf-8",
    )
    rep = etl.TransformReport()
    clean = etl.transform(etl.read_raw(p), rep)
    assert rep.filas == 5 and rep.celdas_total == 10
    assert rep.filas_sin_fecha_hora == 1
    assert rep.celdas_vacias == 4
    assert rep.celdas_no_numericas == 1
    assert rep.celdas_sin_clave == 1
    assert rep.celdas_negativas == 1
    assert rep.celdas_duplicadas == 1
    assert rep.mediciones == len(clean) == 2
    # las celdas cuadran: todo lo que entra o se carga o se descarta por un motivo
    assert rep.celdas_total == (rep.mediciones + rep.celdas_vacias + rep.celdas_no_numericas
                                + rep.celdas_sin_clave + rep.celdas_negativas + rep.celdas_duplicadas)
    assert rep.estaciones_sin_contaminantes == ["Meteo"]
    assert clean.loc[clean.contaminante == "NO2", "valor"].tolist() == [13.0]   # gana la última


def test_corrige_dia_y_mes_intercambiados(tmp_path):
    p = tmp_path / "swap.csv"
    p.write_text(
        "Fecha;Dia de la semana;Dia del mes;Hora;Estacion;NO2\n"
        "2020-02-01T00:00:00;Jueves;2;7:00:00;Centre;10\n"     # en realidad 2 de enero
        "2020-01-02T00:00:00;Sábado;1;7:00:00;Centre;20\n"     # en realidad 1 de febrero
        "2020-02-29T00:00:00;Sábado;1;7:00:00;Centre;30\n"     # fecha buena, 'Dia del mes' erróneo
        "2020-03-15T00:00:00;Domingo;15;7:00:00;Centre;40\n",  # día > 12: nunca se intercambia
        encoding="utf-8",
    )
    rep = etl.TransformReport()
    clean = etl.transform(etl.read_raw(p), rep).set_index("valor")["fecha_hora"]
    assert clean[10.0] == pd.Timestamp("2020-01-02 07:00")
    assert clean[20.0] == pd.Timestamp("2020-02-01 07:00")
    assert clean[30.0] == pd.Timestamp("2020-02-29 07:00")
    assert clean[40.0] == pd.Timestamp("2020-03-15 07:00")
    assert rep.fechas_dia_mes_corregidas == 2
    assert rep.dias_semana_incoherentes == 0


def test_serie_continua_corta_la_linea_en_los_huecos():
    ind = pd.DataFrame({
        "estacion": "A",
        "fecha": pd.to_datetime(["2020-01-01", "2020-01-02", "2020-03-01"]),
        "valor": [10.0, 20.0, 30.0],
    })
    s = serie_diaria_continua(ind).set_index("fecha")["valor"]
    assert len(s) == 61                                  # un punto por día de calendario
    assert s.loc["2020-01-03":"2020-02-29"].isna().all()  # el hueco queda vacío, no se une
    suav = serie_diaria_continua(ind, ventana_dias=7).set_index("fecha")["valor"]
    assert suav.loc["2020-03-01"] != 25.0                 # no mezcla valores separados por meses


@pytest.mark.parametrize(("guia", "max_dato", "esperado"), [
    (4, 0.4, False),     # CO: la guía es 10 veces el máximo -> fuera de escala
    (40, 9.8, False),    # SO2: 4 veces
    (25, 83.8, True),    # NO2: la guía está dentro de los datos
    (45, 21.5, True),    # PM10 en barras: ~2 veces, se sigue dibujando
    (30, 10, True),      # justo en el límite (3x) se dibuja
    (4, float("nan"), True),   # sin datos: no se oculta la guía
])
def test_guia_en_escala(guia, max_dato, esperado):
    assert guia_en_escala(guia, max_dato) is esperado


def test_texto_guia_fuera_de_escala():
    texto = texto_guia_fuera_de_escala(4, "mg/m³", "media diaria", 0.4)
    assert texto == "Guía OMS: 4 mg/m³ (media diaria) · fuera de escala, 10× el máximo mostrado"
