"""`@plano` e `@workflow`: o badge ligado muda o turno.

A função nativa é uma ativação visível: vale enquanto o badge estiver ligado,
e não depende de a mensagem conter a palavra certa. `@image` é portão de
ferramenta; estas duas agem no contexto do turno.
"""
import json
import re
from pathlib import Path

import pytest

from sentury.harness.funcoes import SKILL_DO_WORKFLOW, ferramentas_ligadas, instrucoes_do_turno, skill_ligada

RAIZ = Path(__file__).resolve().parents[1]


class TestInstrucaoDoTurno:
    def test_sem_nada_ligado_nao_instrui_nada(self):
        assert instrucoes_do_turno(None) == []
        assert instrucoes_do_turno([]) == []
        assert instrucoes_do_turno(["image"]) == []

    def test_plano_explicita_a_preferencia_sem_forcar_em_conversa_simples(self):
        (texto,) = instrucoes_do_turno(["plano"])
        assert "@plano" in texto and "aguarde a aprovação" in texto
        assert "não crie plano só porque a função está disponível" in texto

    def test_workflow_e_processo_persistente_nao_plano_grande(self):
        """A diferença entre plano e workflow não é tamanho: plano roda uma vez
        e fecha; workflow persiste entre etapas e pode ou não ter agendamento."""
        (texto,) = instrucoes_do_turno(["workflow"])
        assert "criar_workflow" in texto and "gatilho" in texto.lower()
        assert "opcional" in texto and "não invente horário" in texto
        # E precisa mandar de volta quando NÃO for rotina, senão todo pedido
        # de trabalho longo vira agendamento.
        assert "criar_plano" in texto

    def test_workflow_absorve_plano(self):
        """Duas instruções dizendo a mesma coisa com palavras diferentes se
        diluem. Quem conduz até fechar também mostra o caminho antes."""
        assert instrucoes_do_turno(["plano", "workflow"]) == instrucoes_do_turno(["workflow"])

    def test_navegador_e_computador_sao_capacidades_separadas(self):
        # A separação é a mesa do turno, não uma frase mandando usar uma e não a outra.
        (texto,) = instrucoes_do_turno(["navegador"])
        assert "Continue no mesmo turno e na mesma sessão" in texto
        assert "semanticamente equivalente" in texto
        assert ferramentas_ligadas(["navegador"]) == {"browser"}
        assert ferramentas_ligadas(["computador"]) == {"computador"}

    def test_cada_badge_expoe_schemas_sem_interpretar_o_pedido(self):
        from sentury.llm.tool_schemas import build_tool_schemas
        from sentury.tools.registry import TOOL_REGISTRY

        esperado = {
            "image": {"gerar_imagem"}, "plano": {"criar_plano"},
            "workflow": {"criar_workflow", "criar_plano"}, "goal": {"goal"},
            "computador": {"computador"}, "navegador": {"browser"},
        }
        for badge, schemas in esperado.items():
            assert ferramentas_ligadas([badge]) == schemas
            assert schemas <= TOOL_REGISTRY.keys()
            oferecidas = {s["function"]["name"] for s in build_tool_schemas(schemas)}
            assert schemas <= oferecidas

    @pytest.mark.parametrize("entrada", [[" Workflow "], ["WORKFLOW"]])
    def test_nao_depende_de_caixa_nem_de_espaco(self, entrada):
        assert instrucoes_do_turno(entrada)


class TestSkillLigadaPeloBadge:
    def test_workflow_liga_a_skill(self):
        assert skill_ligada(["workflow"]) == SKILL_DO_WORKFLOW

    def test_plano_sozinho_nao_liga_skill(self):
        # `@plano` é do turno: instrução, não procedimento em disco.
        assert skill_ligada(["plano"]) is None
        assert skill_ligada(["image"]) is None

    def test_a_skill_apontada_existe_mesmo(self):
        caminho = RAIZ / "sentury" / "skills" / "cognitive" / SKILL_DO_WORKFLOW / "SKILL.md"
        assert caminho.is_file(), "a funcao aponta para uma skill que nao existe"

    def test_badge_apresenta_skill_sem_executar_e_desligar_remove_contexto(self):
        from sentury.harness.funcoes import aplicar_no_turno
        from sentury.harness.state import AnalysisState

        class Loader:
            def load_skill(self, nome, session_id=None):
                assert nome == SKILL_DO_WORKFLOW
                return type("Skill", (), {"to_context_block": lambda self: "=== SKILL: montar-workflow ==="})()

        estado = AnalysisState.new("workflow-badge", "dono")
        estado.funcoes_ativas = ["workflow"]
        estado.history.append({"role": "user", "content": "你好，请帮我一下"})
        aplicar_no_turno(estado, Loader())
        assert any("=== SKILL: montar-workflow ===" in str(m.get("content")) for m in estado.history)
        assert not any(m.get("role") == "tool" for m in estado.history)

        estado.funcoes_ativas = []
        aplicar_no_turno(estado, Loader())
        assert not any("=== SKILL: montar-workflow ===" in str(m.get("content")) for m in estado.history)


@pytest.mark.asyncio
async def test_workflow_ligado_nao_dispara_executar_skill_quando_modelo_responde(monkeypatch):
    from sentury.config import settings
    from sentury.harness.orchestrator import SenturyOrchestrator
    from sentury.harness.state import AnalysisState
    from tests.test_orchestrator import CapturePlanner, EchoResponder, _respond, _store

    monkeypatch.setattr(settings, "SENTURY_NATIVE_TOOLS", False)
    planner = CapturePlanner(_respond("Pode me contar o que precisa."))
    orq = SenturyOrchestrator(planner=planner, responder=EchoResponder(),
                              store=_store())
    estado = AnalysisState.new("workflow-sem-acao", "dono")
    estado.funcoes_ativas = ["workflow"]
    resultado = await orq.handle_message(estado, "你好，请帮我一下")

    assert planner.calls, "o badge deve chegar ao modelo antes de decidir"
    assert any("=== SKILL: montar-workflow ===" in str(m.get("content"))
               for m in planner.calls[0]["messages"])
    assert "executar_skill" not in resultado["harness"].get("ferramentas", [])


class TestClientOfereceAsFuncoes:
    """O badge só existe se a interface o listar: o backend sozinho não
    aparece para ninguém, que era exatamente o buraco: `@` só mostrava image."""

    @pytest.fixture(scope="class")
    def declaradas(self):
        fonte = (RAIZ / "sentury" / "client" / "src" / "runtime"
                 / "funcoes-nativas.ts").read_text(encoding="utf-8")
        return set(re.findall(r"id:\s*'([a-z_]+)'", fonte))

    def test_as_tres_estao_na_lista(self, declaradas):
        assert {"image", "plano", "workflow", "computador", "navegador"} <= declaradas

    def test_o_backend_entende_todas_as_que_o_client_oferece(self, declaradas):
        """Badge que a interface liga e o backend ignora é promessa quebrada."""
        from sentury.harness import policy

        entendidas = set()
        for nome in declaradas:
            if instrucoes_do_turno([nome]) or skill_ligada([nome]):
                entendidas.add(nome)
        # `image` age noutro lugar: é portão de ferramenta, não contexto.
        assert "image" in Path(policy.__file__).read_text(encoding="utf-8")
        entendidas.add("image")
        assert declaradas <= entendidas, f"a interface oferece o que ninguem le: {declaradas - entendidas}"


def test_cada_funcao_declara_se_e_intencao_ou_acesso():
    """Intenção vale só para a mensagem; acesso fica ligado na conversa. O tipo
    decide os dois comportamentos, então nenhuma função pode ficar sem ele, e
    acesso é só o que põe ferramenta de tela ou navegador à disposição."""
    fonte = (RAIZ / "sentury" / "client" / "src" / "runtime" / "funcoes-nativas.ts").read_text(encoding="utf-8")
    blocos = re.findall(r"id:\s*'([a-z_]+)',\s*rotulo:\s*'[^']*',\s*tipo:\s*'([a-z]+)'", fonte)
    declaradas = set(re.findall(r"id:\s*'([a-z_]+)'", fonte))
    tipos = dict(blocos)
    assert set(tipos) == declaradas, "toda função precisa declarar o tipo logo depois do rótulo"
    assert set(tipos.values()) <= {"intencao", "acesso"}
    assert {nome for nome, tipo in tipos.items() if tipo == "acesso"} == {"computador", "navegador"}
