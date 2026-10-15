import numpy as np
import pandas as pd

from aire import confinamiento as cf

VENTANA = ("03-14", "05-17")


def _daily(factor_anio, factor_ventana, estaciones=("A", "B", "C", "D"), seed=0):
    """Medias diarias sintéticas 2016–2021 con ciclo anual.

    factor_anio[y]: multiplica todo el año; factor_ventana[y]: además, del 14/03 al 17/05.
    """
    rng = np.random.default_rng(seed)
    filas = []
    for k, est in enumerate(estaciones):
        nivel = 20 + 5 * k
        for y in range(2016, 2022):
            fechas = pd.date_range(f"{y}-01-01", f"{y}-12-31", freq="D")
            ciclo = 1 + 0.3 * np.cos(2 * np.pi * (fechas.dayofyear - 15) / 365)
            v = nivel * ciclo * factor_anio.get(y, 1.0) * rng.lognormal(0, 0.02, len(fechas))
            md = fechas.strftime("%m-%d")
            v = np.where((md >= VENTANA[0]) & (md <= VENTANA[1]), v * factor_ventana.get(y, 1.0), v)
            filas.append(pd.DataFrame({"estacion": est, "fecha": fechas, "media": v}))
    return pd.concat(filas, ignore_index=True)


NORMAL = {2016: 1.00, 2017: 1.06, 2018: 0.95, 2019: 1.02}


def _fase(res, nombre):
    return res.set_index("fase").loc[nombre]


def test_descuenta_la_tendencia_previa():
    # 2020: todo el año un 20 % más bajo (tendencia) y, además, la mitad en el confinamiento
    d = _daily({**NORMAL, 2020: 0.8, 2021: 0.8}, {2020: 0.5})
    conf = _fase(cf.resumen(d), "Confinamiento")
    assert conf["n_estaciones"] == 4
    assert -63 < conf["variacion_bruta"] < -57          # 0,8 × 0,5 → −60 %
    assert -53 < conf["efecto"] < -47                   # ajustado: solo el −50 % del confinamiento
    assert conf["veredicto"] == "claro"
    deses = _fase(cf.resumen(d), "Desescalada")
    assert abs(deses["efecto"]) < 5                     # fuera de la ventana no hay efecto
    assert deses["veredicto"] == "no concluyente"


def test_placebo_parecido_anula_el_veredicto():
    # 2021 muestra la misma caída en las mismas fechas: no es atribuible al confinamiento
    d = _daily({**NORMAL, 2020: 0.8, 2021: 0.8}, {2020: 0.5, 2021: 0.5})
    conf = _fase(cf.resumen(d), "Confinamiento")
    assert conf["placebo_efecto"] < -40
    assert conf["veredicto"] == "no concluyente"


def test_nueva_normalidad_es_descriptiva():
    d = _daily({**NORMAL, 2020: 0.5}, {})
    assert _fase(cf.resumen(d), "Nueva normalidad")["veredicto"] == "descriptiva"


def test_estacion_sin_referencia_suficiente_queda_fuera():
    d = _daily({**NORMAL, 2020: 0.8}, {2020: 0.5})
    # La estación D solo tiene 2 años de referencia
    d = d[~((d["estacion"] == "D") & d["fecha"].dt.year.isin([2016, 2017]))]
    assert _fase(cf.resumen(d), "Confinamiento")["n_estaciones"] == 3


def test_sin_datos_de_2020():
    d = _daily(NORMAL, {})
    d = d[d["fecha"].dt.year != 2020]
    assert (cf.resumen(d)["veredicto"] == "sin datos suficientes").all()


def test_serie_semanal():
    d = _daily({**NORMAL, 2020: 0.8}, {2020: 0.5})
    s = cf.serie_semanal(d)
    assert list(s.columns) == ["semana", "anio_valor", "ref_media", "ref_min", "ref_max"]
    assert s["semana"].between(1, 52).all()
    assert (s["ref_min"] <= s["ref_media"]).all() and (s["ref_media"] <= s["ref_max"]).all()
    abril = s[s["semana"].between(15, 18)]
    assert (abril["anio_valor"] < abril["ref_min"]).all()     # en abril de 2020, por debajo del rango
