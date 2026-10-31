"""Base pequena para testar leitura SQL sem serviço externo."""
import sqlite3

from sentury.data.store import SemDados


class StoreTeste(SemDados):
    def __init__(self, **_configuracao):
        super().__init__()
        self._conexao = sqlite3.connect(":memory:", check_same_thread=False)
        self._conexao.execute("CREATE TABLE registros (grupo TEXT, medida REAL)")
        self._conexao.executemany(
            "INSERT INTO registros VALUES (?, ?)", [("Alfa", 20.0), ("Beta", 40.0)]
        )
        self._conexao.commit()

    def get_sqlite_conn(self):
        return self._conexao

    def get_registros(self):
        import pandas as pd

        return pd.read_sql_query("SELECT * FROM registros", self._conexao)


InMemoryDataStore = StoreTeste
