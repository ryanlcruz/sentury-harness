

class TestRecusaNaoEFalha:
    """Para o laço as duas param o passo; para quem lê a tela são coisas
    diferentes: "o agente errou" e "a política barrou" pedem reações
    diferentes, e o triângulo vermelho dizia a primeira nos dois casos."""

    def test_recusa_do_shell_e_reconhecida(self):
        from sentury.harness.classificacao import falhou, recusado

        resultado = {"ok": False, "recusado": True, "erro": "comando nao liberado"}
        assert recusado(resultado) is True
        assert falhou(resultado) is True, "continua parando o passo"

    def test_erro_comum_nao_e_recusa(self):
        from sentury.harness.classificacao import recusado

        assert recusado({"ok": False, "erro": "arquivo nao existe"}) is False

    def test_sucesso_nao_e_recusa(self):
        from sentury.harness.classificacao import recusado

        assert recusado({"ok": True}) is False
        assert recusado("nao e dicionario") is False
