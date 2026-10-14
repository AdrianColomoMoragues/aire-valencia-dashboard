import numpy as np
import pandas as pd

from aire import calidad, db


def _serie(estacion, contaminante, valores, inicio="2020-01-01"):
    idx = pd.date_range(inicio, periods=len(valores), freq="h")
    return pd.DataFrame({"estacion": estacion, "contaminante": contaminante,
                         "fecha_hora": idx, "valor": np.asarray(valores, dtype=float)})


def _ruido(n, media=30, seed=0):
    rng = np.random.default_rng(seed)
    return np.round(media + 10 * rng.standard_normal(n), 1)


def test_valor_atascado_detecta_racha_larga():
    valores = list(_ruido(24)) + [1.0] * 15 + list(_ruido(24, seed=1))
    out = calidad.valores_atascados(_serie("A", "NO2", valores))
    assert len(out) == 1
    r = out.iloc[0]
    assert r.n_horas == 15 and r.excluir == 1 and r.regla == "valor_atascado"
    assert r.inicio == pd.Timestamp("2020-01-02 00:00")
    assert "valor constante 1" in r.detalle


def test_valor_atascado_ignora_rachas_cortas_y_huecos():
    corto = _serie("A", "NO2", list(_ruido(10)) + [5.0] * 11 + list(_ruido(10, seed=2)))
    assert calidad.valores_atascados(corto).empty           # 11 h < 12 h
    # 8 h iguales, un hueco de 1 día y otras 8 h iguales: no es una racha continua
    a = _serie("A", "NO2", [5.0] * 8)
    b = _serie("A", "NO2", [5.0] * 8, inicio="2020-01-02")
    assert calidad.valores_atascados(pd.concat([a, b])).empty


def test_valor_atascado_no_se_aplica_a_co_ni_so2():
    df = pd.concat([_serie("A", "CO", [0.1] * 200), _serie("A", "SO2", [3.0] * 200)])
    assert calidad.valores_atascados(df).empty


def test_pico_aislado_es_solo_aviso():
    base = _serie("A", "PM2.5", _ruido(500, media=10))
    base.loc[250, "valor"] = 400.0                          # muy por encima de vecinos y p99.9
    out = calidad.picos_aislados(base)
    assert len(out) == 1
    assert out.iloc[0].excluir == 0                           # puede ser real (p. ej. la Cremà)
    assert out.iloc[0].inicio == base.loc[250, "fecha_hora"]


def test_pico_no_aislado_no_se_marca():
    base = _serie("A", "PM10", _ruido(500, media=20))
    base.loc[250:252, "valor"] = 400.0                        # episodio de 3 h: no es aislado
    assert calidad.picos_aislados(base).empty


def test_deriva_regional_o3():
    dias = 200
    horas = dias * 24
    rng = np.random.default_rng(3)
    ciclo = 60 + 20 * np.sin(np.arange(horas) * 2 * np.pi / 24)
    partes = [_serie(f"E{i}", "O3", ciclo + rng.normal(0, 3, horas)) for i in range(4)]
    raro = ciclo + rng.normal(0, 3, horas)
    raro[100 * 24:160 * 24] *= 0.5                            # 60 días a la mitad
    partes.append(_serie("Raro", "O3", raro))
    out = calidad.deriva_regional(pd.concat(partes))
    assert list(out["estacion"]) == ["Raro"]
    r = out.iloc[0]
    assert r.excluir == 1 and r.regla == "deriva_regional"
    assert pd.Timestamp("2020-04-05") <= r.inicio <= pd.Timestamp("2020-04-30")
    assert pd.Timestamp("2020-06-01") <= r.fin <= pd.Timestamp("2020-06-30")


def test_carga_y_exclusion_en_sqlite(tmp_path):
    valores = list(_ruido(48)) + [1.0] * 24 + list(_ruido(48, seed=5))
    df = _serie("A", "NO2", valores)
    conn = db.connect(tmp_path / "t.db")
    db.load_measurements(conn, df)
    flags = calidad.detectar(df)
    assert db.load_quality_flags(conn, flags) == 1
    todos = db.hourly_values(conn, "NO2", ["A"], "2020-01-01", "2020-01-06")
    limpios = db.hourly_values(conn, "NO2", ["A"], "2020-01-01", "2020-01-06", excluir_qc=True)
    assert len(todos) - len(limpios) == 24
    assert (limpios["valor"] != 1.0).all()
    d_todos = db.daily_means(conn, "NO2", ["A"], "2020-01-01", "2020-01-06")
    d_limpios = db.daily_means(conn, "NO2", ["A"], "2020-01-01", "2020-01-06", excluir_qc=True)
    assert len(d_limpios) == len(d_todos) - 1                 # el día atascado ya no es válido
    inc = db.quality_flags(conn, "NO2", ["A"], "2020-01-01", "2020-01-06")
    assert inc["regla"].tolist() == ["valor_atascado"]
