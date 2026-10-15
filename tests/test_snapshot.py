import pandas as pd

from aire import db, etl, snapshot
from aire.sample import write_sample_csv


def test_extracto_ida_y_vuelta(tmp_path):
    """data/aire.db -> Parquet -> nueva base: mismas mediciones y control de calidad recalculado."""
    origen = tmp_path / "origen.db"
    etl.run(write_sample_csv(tmp_path / "m.csv", days=15), origen)
    pq = snapshot.export_snapshot(origen, tmp_path / "snap" / "mediciones.parquet")
    destino = tmp_path / "nube" / "aire.db"
    n = snapshot.build_db_from_snapshot(pq, destino)

    a, b = db.connect(origen), db.connect(destino)
    q = ("SELECT e.nombre, m.fecha_hora, m.contaminante, m.valor FROM mediciones m "
         "JOIN estaciones e ON e.id = m.estacion_id ORDER BY 1, 2, 3")
    pd.testing.assert_frame_equal(pd.read_sql_query(q, a), pd.read_sql_query(q, b))
    assert n == a.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
    # la tabla de incidencias existe en la base nueva (aunque esté vacía)
    b.execute("SELECT COUNT(*) FROM incidencias_calidad").fetchone()
    assert not destino.with_suffix(".tmp").exists()


def test_ensure_db(tmp_path):
    destino = tmp_path / "aire.db"
    assert snapshot.ensure_db(destino, tmp_path / "no_existe.parquet") == "sin datos"
    origen = tmp_path / "origen.db"
    etl.run(write_sample_csv(tmp_path / "m.csv", days=3), origen)
    pq = snapshot.export_snapshot(origen, tmp_path / "s.parquet")
    assert snapshot.ensure_db(destino, pq) == "extracto"
    assert snapshot.ensure_db(destino, pq) == "existente"      # la segunda vez no la rehace
