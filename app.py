"""Dashboard de calidad del aire de València (Streamlit).

Punto de entrada: define la navegación entre páginas.
En local, ejecuta primero el ETL (`python -m aire.etl`) y después `streamlit run app.py`.
En la nube, la base se crea sola a partir de `snapshot/` en el primer arranque.
"""
import streamlit as st

st.set_page_config(page_title="Calidad del aire · València", page_icon="🌬️", layout="wide")

paginas = [
    st.Page("paginas/explorador.py", title="Explorador", icon="🌬️", default=True),
    st.Page("paginas/confinamiento_2020.py", title="Confinamiento 2020", icon="🏠"),
]
st.navigation(paginas).run()
