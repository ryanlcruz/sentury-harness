"""Consulta parametrizada para exercitar o dispatcher do motor."""


async def executar(store, ferramenta, argumentos):
    if ferramenta != "consultar_medida":
        raise ValueError(f"ferramenta desconhecida: {ferramenta}")
    grupo = argumentos.get("grupo")
    sql = "SELECT grupo, medida FROM registros"
    parametros = ()
    if grupo is not None:
        sql += " WHERE grupo = ?"
        parametros = (grupo,)
    return [
        {"grupo": linha[0], "medida": linha[1]}
        for linha in store.get_sqlite_conn().execute(sql, parametros).fetchall()
    ]
