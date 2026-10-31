"""Permite verificar alertas com uma única métrica."""
METRICAS = {"medida": "Medida"}


async def medir(store, metrica, rompeu):
    if metrica != "medida":
        return []
    linhas = store.get_sqlite_conn().execute("SELECT grupo, medida FROM registros")
    return [f"Medida {grupo}: {valor:g}%" for grupo, valor in linhas if rompeu(valor)]
