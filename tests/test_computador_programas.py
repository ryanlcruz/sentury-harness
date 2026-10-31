"""Que programas rodam e quais estão instalados: o que o agente precisa para
escolher entre trazer para a frente e abrir."""
import pytest

from sentury.tools import computador, computador_programas as cp
from tests.test_computador import Falso, _aprovar, _no_turno, _state


def _menu(tmp_path, *nomes):
    pasta = tmp_path / "Programs"
    for nome in nomes:
        (pasta / nome).parent.mkdir(parents=True, exist_ok=True)
        (pasta / nome).write_bytes(b"")
    return [pasta]


class TestInstalados:
    def test_acha_pelo_nome_sem_acento_e_sem_caixa_e_o_igual_vem_primeiro(self, tmp_path):
        pastas = _menu(tmp_path, "Antigravity/Antigravity Tools.lnk", "Antigravity/Antigravity.lnk",
                       "Antigravity/Uninstall Antigravity.lnk", "Música.lnk")
        assert [i["nome"] for i in cp.instalados("ANTIGRAVITY", pastas)] == ["Antigravity", "Antigravity Tools"]
        assert [i["nome"] for i in cp.instalados("musica", pastas)] == ["Música"]

    def test_apps_da_loja_entram_pelo_nome_e_pelo_identificador(self, tmp_path):
        """Bloco de notas não tem atalho na pasta do menu: vem da lista de apps."""
        apps = ["Bloco de notas|Microsoft.WindowsNotepad_8wekyb3d8bbwe!App", "Calculadora|Microsoft.WindowsCalculator!App"]
        vazio = _menu(tmp_path)
        assert [i["nome"] for i in cp.instalados("bloco de notas", vazio, apps)] == ["Bloco de notas"]
        assert [i["nome"] for i in cp.instalados("notepad", vazio, apps)] == ["Bloco de notas"]
        assert cp.instalados("paint", vazio, apps) == []

    def test_abre_pelo_menu_iniciar_e_espera_a_janela(self, tmp_path):
        """Como a pessoa: Win, o nome, Enter; depois espera a janela e a traz."""
        pastas = _menu(tmp_path, "Antigravity.lnk")
        gestos, focadas, tentativas = [], [], []

        def janela(nome):
            tentativas.append(nome)
            return "Antigravity - Agent" if len(tentativas) >= 3 else ""

        feito = cp.abrir_pelo_menu("antigravity", apertar=lambda t: gestos.append(("tecla", t)),
                                   escrever=lambda t: gestos.append(("escrever", t)), janela_do_programa=janela,
                                   esperar=lambda s: None, focar=focadas.append, pastas=pastas)
        assert gestos == [("tecla", "win"), ("escrever", "Antigravity"), ("tecla", "enter")]
        assert focadas == ["Antigravity - Agent"] and "na frente" in feito

    def test_sem_janela_no_prazo_diz_para_conferir_antes_de_abrir_de_novo(self, tmp_path):
        feito = cp.abrir_pelo_menu("antigravity", apertar=lambda t: None, escrever=lambda t: None,
                                   janela_do_programa=lambda n: "", esperar=lambda s: None, focar=lambda t: None,
                                   pastas=_menu(tmp_path, "Antigravity.lnk"), prazo=3)
        assert "não apareceu" in feito and "antes de abrir de novo" in feito

    def test_nao_instalado_nao_digita_nada(self, tmp_path):
        gestos = []
        with pytest.raises(LookupError, match="menu Iniciar"):
            cp.abrir_pelo_menu("cmd.exe", apertar=gestos.append, escrever=gestos.append,
                               janela_do_programa=lambda n: "", esperar=lambda s: None, focar=lambda t: None,
                               pastas=_menu(tmp_path, "Antigravity.lnk"))
        assert gestos == []


class ComProgramas(Falso):
    def __init__(self):
        super().__init__()
        self.abertos = []

    def programas(self, nome=""):
        dados = {"abertos": [{"programa": "Code.exe", "janelas": [
            {"titulo": "Sentury - Visual Studio Code", "em_foco": True, "minimizada": False}]}]}
        if nome:
            dados.update(sem_janela=[], instalados=["Antigravity"])
        return dados

    def abrir(self, nome, interromper=lambda: False):
        self.abertos.append(nome)
        return "Antigravity"


@pytest.fixture
def programas(monkeypatch):
    monkeypatch.setattr(computador, "_ESPERA_DEPOIS_DO_GESTO", 0)
    backend = ComProgramas()
    computador.usar_backend(backend)
    yield backend
    computador._limpar_para_testes()
    computador.usar_backend(None)


class TestNoComputador:
    async def test_programas_e_leitura_e_nao_pede_aprovacao(self, programas):
        r = await _no_turno(computador.executar({"acao": "programas", "nome": "antigravity"}, _state()))
        assert r["ok"] and r["instalados"] == ["Antigravity"] and "abrir" in r["nota"]
        assert programas.gestos == []

    async def test_abrir_e_gesto_e_diz_onde_caiu(self, programas):
        _aprovar("s1")
        r = await _no_turno(computador.executar({"acao": "abrir", "nome": "antigravity"}, _state()))
        assert r["executado"] and programas.abertos == ["antigravity"] and "(Antigravity)" in r["feito"]
        assert r["na_janela"] == "Pokemon"

    async def test_abrir_sem_nome_nao_age(self, programas):
        r = await _no_turno(computador.executar({"acao": "abrir"}, _state()))
        assert "`nome`" in r["erro"] and programas.abertos == []

    def test_o_yaml_oferece_as_acoes(self):
        from sentury.tools.registry import TOOL_REGISTRY

        propriedades = TOOL_REGISTRY["computador"]["parametros"]["properties"]
        assert {"programas", "abrir"} <= set(propriedades["acao"]["enum"]) and "nome" in propriedades
