"""Ferramentas próprias do setor: o que YAML não declara.

Exemplo do formato: uma empresa põe aqui o que fala com a API interna dela.
O host oferece `api.ferramenta(...)` e nada mais; o resto é código normal.

A ferramenta escolhe a assinatura. `f(argumentos)` basta quando ela não precisa
de dado; `f(argumentos, ctx)` recebe o contexto do turno: e é por ele que o
pacote chega ao banco da instalação, via `ctx.sql()` ou `ctx.store`.
"""


def registrar(api):
    async def contar_tabela(argumentos, ctx):
        """Quantas linhas uma tabela tem. Consulta de verdade.

        Existe para provar o contrato: antes o pacote não recebia nada além dos
        argumentos, então toda ferramenta de exemplo devolvia número inventado
        com um aviso pedindo desculpa.
        """
        tabela = str(argumentos.get("tabela") or "").strip()
        if not tabela:
            return {"ok": False, "erro": "diga o nome da tabela"}

        conexao = ctx.sql()
        if conexao is None:
            return {"ok": False, "erro": "esta instalacao nao expoe uma fonte SQL"}

        # Aspas no identificador: o nome vem de fora, e parametro SQL nao serve
        # para identificador.
        citada = '"' + tabela.replace('"', '""') + '"'
        try:
            total = conexao.execute(f"SELECT COUNT(*) FROM {citada}").fetchone()[0]
        except Exception as exc:
            return {"ok": False, "erro": f"{type(exc).__name__}: {exc}", "tabela": tabela}
        return {"ok": True, "tabela": tabela, "linhas": int(total), "setor": ctx.setor}

    api.ferramenta(
        "contar_tabela",
        contar_tabela,
        descricao="Quantas linhas uma tabela do banco tem. Consulta a fonte de dados da instalacao.",
        categoria="conhecimento",
        quando_usar=["quantas linhas tamanho da tabela volume de registros"],
    )
