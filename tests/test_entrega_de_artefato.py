"""A fronteira da entrega de artefato, escrita e conferida.

A extracao do M3 tirou 511 linhas do `orchestrator.py` sem mudar nenhuma. O
que ela acrescentou foi uma lista: o que a entrega chama no orquestrador que a
hospeda. Antes isso so existia como `self.` espalhado; agora, se alguem
renomear `_html_attachment_message` no orquestrador, este teste diz onde
quebrou em vez de o anexo sumir na tela.
"""
import ast
import inspect

from sentury.harness import entrega_de_artefato as entrega
from sentury.harness.entrega_de_artefato import EXIGE_DO_HOSPEDEIRO, EntregaDeArtefato
from sentury.harness.orchestrator import SenturyOrchestrator


def _metodos_da_base():
    return {nome for nome, _ in inspect.getmembers(EntregaDeArtefato, callable) if not nome.startswith("__")}


def test_a_lista_do_que_a_base_exige_esta_completa():
    """Todo `self.X` que a base usa e nao define tem que estar na lista. Sem
    isto, a lista vira documentacao que apodrece."""
    arvore = ast.parse(inspect.getsource(entrega))
    classe = next(n for n in arvore.body if isinstance(n, ast.ClassDef) and n.name == "EntregaDeArtefato")
    usados = {
        no.attr for no in ast.walk(classe)
        if isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name) and no.value.id == "self"
    }
    faltando = usados - _metodos_da_base() - set(EXIGE_DO_HOSPEDEIRO)
    sobrando = set(EXIGE_DO_HOSPEDEIRO) - usados
    assert not faltando, f"a base usa e a lista nao declara: {sorted(faltando)}"
    assert not sobrando, f"a lista declara e a base nao usa mais: {sorted(sobrando)}"


def test_o_orquestrador_tem_tudo_que_a_base_exige():
    orquestrador = SenturyOrchestrator(planner=object(), responder=object(), store=object())
    ausentes = [nome for nome in EXIGE_DO_HOSPEDEIRO if not hasattr(orquestrador, nome)]
    assert not ausentes, ausentes


def test_a_entrega_nao_voltou_para_dentro_do_orquestrador():
    """Copiar um destes metodos de volta para o `orchestrator.py` sombrearia a
    base em silencio: as duas versoes divergiriam, e o teto do arquivo so
    pegaria se a copia fosse grande."""
    for nome in _metodos_da_base():
        assert nome not in SenturyOrchestrator.__dict__, (
            f"{nome} foi redefinido no orchestrator.py; ele mora em entrega_de_artefato.py"
        )
    assert issubclass(SenturyOrchestrator, EntregaDeArtefato)
